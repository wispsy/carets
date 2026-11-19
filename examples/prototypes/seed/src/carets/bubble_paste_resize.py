import asyncio
import codecs
from dataclasses import dataclass, replace
import os
import re
import signal
import sys
import termios
import tty
from typing import Callable, Optional


# =====================================================================
# 1. Message Types (KeyMsg, MouseMsg, PasteMsg, WindowSizeMsg)
# =====================================================================

class Msg:
    pass


@dataclass(frozen=True)
class KeyMsg(Msg):
    key: str


@dataclass(frozen=True)
class PasteMsg(Msg):
    text: str


@dataclass(frozen=True)
class WindowSizeMsg(Msg):
    width: int
    height: int


@dataclass(frozen=True)
class MouseMsg(Msg):
    x: int
    y: int
    button: str
    action: str
    shift: bool = False
    alt: bool = False
    ctrl: bool = False


# =====================================================================
# 2. ANSI Escape Sequence Constants & Tables
# =====================================================================

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"

# SGR Mouse: ESC [ < btn ; x ; y M (press/move) or m (release)
SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")
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
# 3. Streaming ANSI Parser with Bracketed Paste State Machine
# =====================================================================

class AnsiInputParser:
    ESC_TIMEOUT = 0.030  # 30ms timeout for ambiguous ESC sequences
    PASTE_TIMEOUT = 0.500  # 500ms safety fallback if terminal drops PASTE_END

    def __init__(self, loop: asyncio.AbstractEventLoop, emit: Callable[[Msg], None]):
        self.loop = loop
        self.emit = emit
        self.utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buf: str = ""
        self.in_paste: bool = False
        self.paste_buf: str = ""
        self.esc_timer: Optional[asyncio.TimerHandle] = None

    def feed(self, data: bytes) -> None:
        self.buf += self.utf8_decoder.decode(data, final=False)
        self._cancel_timer()
        self._process_buffer()

    def _cancel_timer(self) -> None:
        if self.esc_timer is not None:
            self.esc_timer.cancel()
            self.esc_timer = None

    def _on_timeout(self) -> None:
        self.esc_timer = None
        # Safety fallback if PASTE_END (\x1b[201~) was lost over SSH
        if self.in_paste:
            self.in_paste = False
            full_paste = (self.paste_buf + self.buf).replace("\r\n", "\n").replace("\r", "\n")
            self.paste_buf = ""
            self.buf = ""
            self.emit(PasteMsg(text=full_paste))
            return

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
            # ---------------------------------------------------------
            # State A: Currently inside a Bracketed Paste (\x1b[200~ ...)
            # ---------------------------------------------------------
            if self.in_paste:
                end_idx = self.buf.find(PASTE_END)
                if end_idx != -1:
                    # Found closing \x1b[201~ -> normalize line endings and emit PasteMsg
                    self.paste_buf += self.buf[:end_idx]
                    self.buf = self.buf[end_idx + len(PASTE_END):]
                    self.in_paste = False
                    normalized = self.paste_buf.replace("\r\n", "\n").replace("\r", "\n")
                    self.paste_buf = ""
                    self.emit(PasteMsg(text=normalized))
                    continue

                # Check if buffer ends with a partial prefix of "\x1b[201~"
                # (e.g. chunk boundary split right in the middle of "\x1b[20")
                keep_tail = 0
                for i in range(1, len(PASTE_END)):
                    if self.buf.endswith(PASTE_END[:i]):
                        keep_tail = i

                if keep_tail > 0:
                    self.paste_buf += self.buf[:-keep_tail]
                    self.buf = self.buf[-keep_tail:]
                else:
                    self.paste_buf += self.buf
                    self.buf = ""

                # Wait for next os.read() chunk containing the rest of the paste
                self.esc_timer = self.loop.call_later(self.PASTE_TIMEOUT, self._on_timeout)
                return

            # ---------------------------------------------------------
            # State B: Normal Input Mode
            # ---------------------------------------------------------
            if self.buf[0] == "\x1b":
                # Check if this is the start of a Bracketed Paste (\x1b[200~)
                if self.buf.startswith(PASTE_START):
                    self.buf = self.buf[len(PASTE_START):]
                    self.in_paste = True
                    self.paste_buf = ""
                    continue

                # If buffer is a prefix of PASTE_START (e.g., "\x1b[20"), wait for more bytes
                if PASTE_START.startswith(self.buf):
                    self.esc_timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                    return

                if len(self.buf) == 1:
                    self.esc_timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                    return

                second = self.buf[1]

                # CSI Sequences (\x1b[...)
                if second == "[":
                    mouse_match = SGR_MOUSE_RE.match(self.buf)
                    if mouse_match:
                        self.buf = self.buf[mouse_match.end():]
                        self.emit(self._parse_sgr_mouse(mouse_match))
                        continue

                    csi_match = CSI_RE.match(self.buf)
                    if csi_match:
                        body = csi_match.group(1)
                        self.buf = self.buf[csi_match.end():]
                        key_msg = self._parse_csi_key(body)
                        if key_msg:
                            self.emit(key_msg)
                        continue

                    self.esc_timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                    return

                # SS3 Sequences (\x1bO...)
                if second == "O":
                    if len(self.buf) < 3:
                        self.esc_timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                        return
                    third = self.buf[2]
                    self.buf = self.buf[3:]
                    self.emit(KeyMsg(SS3_KEYS.get(third, f"ss3+{third}")))
                    continue

                # Alt + Key
                self.buf = self.buf[2:]
                base_key = self._decode_single_char(second)
                self.emit(KeyMsg(f"alt+{base_key}"))
                continue

            # Single character or control character
            ch = self.buf[0]
            self.buf = self.buf[1:]
            self.emit(KeyMsg(self._decode_single_char(ch)))

    def _decode_single_char(self, ch: str) -> str:
        if ch in CONTROL_CHARS:
            return CONTROL_CHARS[ch]
        code = ord(ch)
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"
        return ch

    def _parse_csi_key(self, body: str) -> Optional[KeyMsg]:
        if body in CSI_KEYS:
            return KeyMsg(CSI_KEYS[body])
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
        cb, x, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        state = match.group(4)
        shift, alt, ctrl = bool(cb & 4), bool(cb & 8), bool(cb & 16)
        is_motion, is_wheel = bool(cb & 32), bool(cb & 64)
        low_bits = cb & 3

        if is_wheel:
            button = "wheel_up" if low_bits == 0 else "wheel_down"
            action = "scroll"
        else:
            button = {0: "left", 1: "middle", 2: "right", 3: "none"}[low_bits]
            action = "release" if state == "m" else ("motion" if is_motion else "press")

        return MouseMsg(x=x, y=y, button=button, action=action, shift=shift, alt=alt, ctrl=ctrl)


# =====================================================================
# 4. Responsive Demo Model (Adapts Box Width to WindowSizeMsg)
# =====================================================================

@dataclass(frozen=True)
class WorkspaceModel:
    width: int = 80
    height: int = 24
    last_key: str = "None"
    last_mouse: str = "None"
    last_paste: str = "Paste multi-line text (Cmd+V / Ctrl+Shift+V) to test!"
    paste_lines: int = 0

    def update(self, msg: Msg) -> tuple["WorkspaceModel", bool]:
        if isinstance(msg, WindowSizeMsg):
            return replace(self, width=msg.width, height=msg.height), False

        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c"):
                return self, True
            return replace(self, last_key=msg.key), False

        if isinstance(msg, PasteMsg):
            lines = msg.text.split("\n")
            preview = " ↵ ".join(line.strip() for line in lines[:3])
            if len(lines) > 3:
                preview += f" ... (+{len(lines) - 3} more lines)"
            return replace(
                self,
                last_paste=preview or "(empty paste)",
                paste_lines=len(lines),
            ), False

        if isinstance(msg, MouseMsg):
            desc = f"{msg.button} ({msg.action}) @ ({msg.x}, {msg.y})"
            return replace(self, last_mouse=desc), False

        return self, False

    def view(self) -> str:
        # Dynamically scale box to current terminal width (clamped between 40 and 100)
        box_w = max(40, min(self.width - 2, 96))
        inner_w = box_w - 4
        horiz = "─" * (box_w - 2)

        def row(label: str, val: str, color: str = "37") -> str:
            text = f"{label} {val}"[:inner_w]
            padding = " " * max(0, inner_w - len(text))
            return f"\x1b[1;36m│\x1b[0m  \x1b[1m{label}\x1b[0m \x1b[1;{color}m{val[:inner_w - len(label) - 1]}\x1b[0m{padding}  \x1b[1;36m│\x1b[0m\x1b[K"

        return "\n".join([
            "\x1b[H",  # Cursor home
            f"\x1b[1;36m╭{horiz}╮\x1b[0m\x1b[K",
            row("Terminal Size:", f"{self.width} cols × {self.height} rows (Resize window to test!)", "35"),
            f"\x1b[1;36m├{horiz}┤\x1b[0m\x1b[K",
            row("Last Key:", self.last_key, "32"),
            row("Last Mouse:", self.last_mouse, "33"),
            row(f"Last Paste ({self.paste_lines}L):", self.last_paste, "36"),
            f"\x1b[1;36m╰{horiz}╯\x1b[0m\x1b[K",
            "\x1b[2mTry pasting a multi-line block of code, or resize your terminal window.\x1b[0m\x1b[K",
            "\x1b[2mPress 'q' or 'ctrl+c' to quit.\x1b[0m\x1b[J",
        ])


# =====================================================================
# 5. Runtime Loop with SIGWINCH & Bracketed Paste Setup
# =====================================================================

async def run_app():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Msg] = asyncio.Queue()
    parser = AnsiInputParser(loop, queue.put_nowait)

    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)

    def on_stdin_ready():
        try:
            data = os.read(fd, 4096)
            if data:
                parser.feed(data)
        except BlockingIOError:
            pass

    def emit_window_size():
        try:
            size = os.get_terminal_size(fd)
            queue.put_nowait(WindowSizeMsg(width=size.columns, height=size.lines))
        except OSError:
            pass

    try:
        tty.setraw(fd)
        new_term = termios.tcgetattr(fd)
        new_term[1] |= termios.OPOST
        termios.tcsetattr(fd, termios.TCSANOW, new_term)

        # Enable:
        # ?1049h = Alternate screen
        # ?25l   = Hide cursor
        # ?1003h = Any-event mouse tracking
        # ?1006h = SGR extended mouse coordinates
        # ?2004h = Bracketed Paste mode (\x1b[200~ ... \x1b[201~)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b[?2004h\x1b[2J")
        sys.stdout.flush()

        # Register stdin reader and SIGWINCH resize listener
        loop.add_reader(fd, on_stdin_ready)
        loop.add_signal_handler(signal.SIGWINCH, emit_window_size)

        # Bubble Tea always dispatches an initial WindowSizeMsg on startup
        emit_window_size()

        model = WorkspaceModel()
        while True:
            msg = await queue.get()
            model, should_quit = model.update(msg)
            if should_quit:
                break
            sys.stdout.write(model.view())
            sys.stdout.flush()

    finally:
        loop.remove_reader(fd)
        loop.remove_signal_handler(signal.SIGWINCH)
        # Crucial: Always disable ?2004l on exit, or the user's shell will print
        # literal "200~" and "201~" around pasted text if their shell doesn't reset it!
        sys.stdout.write("\x1b[?2004l\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    asyncio.run(run_app())
