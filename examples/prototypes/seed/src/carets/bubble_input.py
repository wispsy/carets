import asyncio
import codecs
from dataclasses import dataclass, replace
import os
import re
import sys
import termios
import tty
from typing import Callable, Optional


# =====================================================================
# 1. Message Types (tea.KeyMsg & tea.MouseMsg)
# =====================================================================

class Msg:
    pass

@dataclass(frozen=True)
class KeyMsg(Msg):
    key: str

@dataclass(frozen=True)
class MouseMsg(Msg):
    x: int
    y: int
    button: str   # "left", "middle", "right", "wheel_up", "wheel_down", "none"
    action: str   # "press", "release", "motion", "scroll"
    shift: bool = False
    alt: bool = False
    ctrl: bool = False

@dataclass(frozen=True)
class QuitMsg(Msg):
    pass


# =====================================================================
# 2. ANSI Escape Sequence Lookup Tables & Regexes
# =====================================================================

# SGR Mouse: ESC [ < btn ; x ; y M (press/move) or m (release)
SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")

# Standard CSI: ESC [ followed by optional parameters and a final byte (@ through ~)
CSI_RE = re.compile(r"^\x1b\[([\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])")

CSI_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "Z": "shift+tab",
    "1~": "home", "2~": "insert", "3~": "delete", "4~": "end",
    "5~": "pgup", "6~": "pgdn", "7~": "home", "8~": "end",
    "11~": "f1", "12~": "f2", "13~": "f3", "14~": "f4",
    "15~": "f5", "17~": "f6", "18~": "f7", "19~": "f8",
    "20~": "f9", "21~": "f10", "23~": "f11", "24~": "f12",
}

# SS3 sequences (ESC O ...) used by some terminals for F1-F4 and arrows
SS3_KEYS = {
    "P": "f1", "Q": "f2", "R": "f3", "S": "f4",
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
}

CONTROL_CHARS = {
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x00": "ctrl+space",
}

def format_modifiers(mod_param: int, base_key: str) -> str:
    """Decodes xterm modifier bitmask (param - 1): 1=Shift, 2=Alt, 4=Ctrl."""
    bits = mod_param - 1
    mods = []
    if bits & 4:
        mods.append("ctrl")
    if bits & 2:
        mods.append("alt")
    if bits & 1:
        mods.append("shift")
    return "+".join(mods + [base_key]) if mods else base_key


# =====================================================================
# 3. Streaming Non-Blocking ANSI Input Parser
# =====================================================================

class AnsiInputParser:
    """
    Consumes raw bytes from os.read(), incrementally decodes UTF-8,
    parses ANSI escape sequences, and resolves standalone ESC via asyncio timer.
    """
    ESC_TIMEOUT = 0.030  # 30ms timeout to distinguish ESC key from escape sequences

    def __init__(self, loop: asyncio.AbstractEventLoop, emit: Callable[[Msg], None]):
        self.loop = loop
        self.emit = emit
        self.utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buf: str = ""
        self.esc_timer: Optional[asyncio.TimerHandle] = None

    def feed(self, data: bytes) -> None:
        """Called whenever os.read(stdin) yields raw bytes."""
        self.buf += self.utf8_decoder.decode(data, final=False)
        self._cancel_esc_timer()
        self._process_buffer()

    def _cancel_esc_timer(self) -> None:
        if self.esc_timer is not None:
            self.esc_timer.cancel()
            self.esc_timer = None

    def _on_esc_timeout(self) -> None:
        """Triggered when ESC sits incomplete for more than 30ms."""
        self.esc_timer = None
        if self.buf == "\x1b":
            self.buf = ""
            self.emit(KeyMsg("esc"))
        elif self.buf.startswith("\x1b") and len(self.buf) == 2:
            ch = self.buf[1]
            self.buf = ""
            self.emit(KeyMsg(f"alt+{self._decode_single_char(ch)}"))
        elif self.buf:
            ch = self.buf[0]
            self.buf = self.buf[1:]
            self.emit(KeyMsg(self._decode_single_char(ch)))
            self._process_buffer()

    def _process_buffer(self) -> None:
        while self.buf:
            # Case 1: Buffer starts with ESC (\x1b)
            if self.buf[0] == "\x1b":
                if len(self.buf) == 1:
                    self.esc_timer = self.loop.call_later(
                        self.ESC_TIMEOUT, self._on_esc_timeout
                    )
                    return

                second = self.buf[1]

                # 1A: CSI Sequence (\x1b[...)
                if second == "[":
                    # Check SGR Mouse first
                    mouse_match = SGR_MOUSE_RE.match(self.buf)
                    if mouse_match:
                        self.buf = self.buf[mouse_match.end():]
                        self.emit(self._parse_sgr_mouse(mouse_match))
                        continue

                    # Check standard CSI key sequence
                    csi_match = CSI_RE.match(self.buf)
                    if csi_match:
                        body = csi_match.group(1)
                        self.buf = self.buf[csi_match.end():]
                        key_msg = self._parse_csi_key(body)
                        if key_msg:
                            self.emit(key_msg)
                        continue

                    # Incomplete CSI sequence -> wait for remaining bytes
                    self.esc_timer = self.loop.call_later(
                        self.ESC_TIMEOUT, self._on_esc_timeout
                    )
                    return

                # 1B: SS3 Sequence (\x1bO...)
                if second == "O":
                    if len(self.buf) < 3:
                        self.esc_timer = self.loop.call_later(
                            self.ESC_TIMEOUT, self._on_esc_timeout
                        )
                        return
                    third = self.buf[2]
                    self.buf = self.buf[3:]
                    self.emit(KeyMsg(SS3_KEYS.get(third, f"ss3+{third}")))
                    continue

                # 1C: Alt + Key (\x1b followed by normal or control char)
                self.buf = self.buf[2:]
                base_key = self._decode_single_char(second)
                self.emit(KeyMsg(f"alt+{base_key}"))
                continue

            # Case 2: Normal character or Control character
            ch = self.buf[0]
            self.buf = self.buf[1:]
            self.emit(KeyMsg(self._decode_single_char(ch)))

    def _decode_single_char(self, ch: str) -> str:
        if ch in CONTROL_CHARS:
            return CONTROL_CHARS[ch]
        code = ord(ch)
        # Ctrl+A (1) through Ctrl+Z (26)
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"
        return ch

    def _parse_csi_key(self, body: str) -> Optional[KeyMsg]:
        if body in CSI_KEYS:
            return KeyMsg(CSI_KEYS[body])

        # Modified CSI keys: e.g., "1;5A" (Ctrl+Up) or "15;2~" (Shift+F5)
        if ";" in body:
            final_char = body[-1]
            params = body[:-1].split(";")
            if len(params) == 2 and params[1].isdigit():
                prefix, mod_str = params
                mod = int(mod_str)
                lookup = final_char if prefix == "1" else f"{prefix}{final_char}"
                base_key = CSI_KEYS.get(lookup, lookup)
                return KeyMsg(format_modifiers(mod, base_key))

        return KeyMsg(f"csi:{body}")

    def _parse_sgr_mouse(self, match: re.Match) -> MouseMsg:
        cb = int(match.group(1))
        x = int(match.group(2))
        y = int(match.group(3))
        state = match.group(4)  # 'M' = press/move, 'm' = release

        shift = bool(cb & 4)
        alt = bool(cb & 8)
        ctrl = bool(cb & 16)
        is_motion = bool(cb & 32)
        is_wheel = bool(cb & 64)

        low_bits = cb & 3

        if is_wheel:
            button = "wheel_up" if low_bits == 0 else "wheel_down"
            action = "scroll"
        else:
            btn_map = {0: "left", 1: "middle", 2: "right", 3: "none"}
            button = btn_map[low_bits]
            if state == "m":
                action = "release"
            elif is_motion:
                action = "motion"
            else:
                action = "press"

        return MouseMsg(
            x=x, y=y, button=button, action=action,
            shift=shift, alt=alt, ctrl=ctrl
        )


# =====================================================================
# 4. Demo Application & Runtime Loop
# =====================================================================

@dataclass(frozen=True)
class InspectorModel:
    last_key: str = "None yet (press any key, arrow, or Ctrl/Alt combo)"
    last_mouse: str = "None yet (move, click, or scroll mouse)"
    event_count: int = 0

    def update(self, msg: Msg) -> tuple["InspectorModel", bool]:
        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c"):
                return self, True
            return replace(
                self, last_key=msg.key, event_count=self.event_count + 1
            ), False

        if isinstance(msg, MouseMsg):
            mods = [
                m for m, active in (("ctrl", msg.ctrl), ("alt", msg.alt), ("shift", msg.shift))
                if active
            ]
            mod_prefix = "+".join(mods) + "+" if mods else ""
            desc = f"{mod_prefix}{msg.button} ({msg.action}) @ X={msg.x}, Y={msg.y}"
            return replace(
                self, last_mouse=desc, event_count=self.event_count + 1
            ), False

        return self, False

    def view(self) -> str:
        return (
            "\x1b[H"  # Move cursor to top-left (home)
            "\x1b[1;36m╭──────────────────────────────────────────────────────────────╮\x1b[0m\x1b[K\n"
            "\x1b[1;36m│\x1b[0m  \x1b[1;35mBubblePy Async Input & Mouse Inspector\x1b[0m                      \x1b[1;36m│\x1b[0m\x1b[K\n"
            "\x1b[1;36m├──────────────────────────────────────────────────────────────┤\x1b[0m\x1b[K\n"
            f"\x1b[1;36m│\x1b[0m  \x1b[1mLast Key:\x1b[0m     \x1b[1;32m{self.last_key:<46}\x1b[0m\x1b[1;36m│\x1b[0m\x1b[K\n"
            f"\x1b[1;36m│\x1b[0m  \x1b[1mLast Mouse:\x1b[0m   \x1b[1;33m{self.last_mouse:<46}\x1b[0m\x1b[1;36m│\x1b[0m\x1b[K\n"
            f"\x1b[1;36m│\x1b[0m  \x1b[1mTotal Events:\x1b[0m {self.event_count:<46}\x1b[1;36m│\x1b[0m\x1b[K\n"
            "\x1b[1;36m╰──────────────────────────────────────────────────────────────╯\x1b[0m\x1b[K\n"
            "\x1b[2mTry: Arrow keys, Shift+Arrows, Ctrl+Arrows, Esc, F1-F12, Mouse move/click/scroll.\x1b[0m\x1b[K\n"
            "\x1b[2mPress 'q' or 'ctrl+c' to exit.\x1b[0m\x1b[K"
        )


async def run_app():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Msg] = asyncio.Queue()
    parser = AnsiInputParser(loop, queue.put_nowait)

    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)

    def on_stdin_ready():
        # Crucial: os.read() reads all available bytes in the kernel buffer without blocking
        try:
            data = os.read(fd, 1024)
            if data:
                parser.feed(data)
        except BlockingIOError:
            pass

    try:
        # 1. Enter raw mode (captures Ctrl+C, Ctrl+S, disables echo & line buffering)
        tty.setraw(fd)
        # Re-enable output post-processing (\n -> \r\n) so multiline strings render cleanly
        new_term = termios.tcgetattr(fd)
        new_term[1] |= termios.OPOST
        termios.tcsetattr(fd, termios.TCSANOW, new_term)

        # 2. Enter Alternate Screen (?1049h) + Hide Cursor (?25l) + Enable SGR Mouse (?1003h?1006h)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b[2J")
        sys.stdout.flush()

        loop.add_reader(fd, on_stdin_ready)

        model = InspectorModel()
        sys.stdout.write(model.view())
        sys.stdout.flush()

        while True:
            msg = await queue.get()
            model, should_quit = model.update(msg)
            if should_quit:
                break
            sys.stdout.write(model.view())
            sys.stdout.flush()

    finally:
        loop.remove_reader(fd)
        # Disable mouse tracking, show cursor, and leave alternate screen
        sys.stdout.write("\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    asyncio.run(run_app())
