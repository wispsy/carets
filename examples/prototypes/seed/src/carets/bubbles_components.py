import asyncio
import codecs
from dataclasses import dataclass, field, replace
import os
import re
import signal
import sys
import termios
import tty
import unicodedata
from typing import Callable, Coroutine, List, Optional, Tuple


# =====================================================================
# 1. Core Tea Types & Command Batching
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

@dataclass(frozen=True)
class BatchMsg(Msg):
    cmds: Tuple[Callable[[], Coroutine[None, None, Optional[Msg]]], ...]

Cmd = Callable[[], Coroutine[None, None, Optional[Msg]]]

def batch(*cmds: Optional[Cmd]) -> Optional[Cmd]:
    """Combines multiple Cmds into one, just like tea.Batch()."""
    valid = tuple(c for c in cmds if c is not None)
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    async def _batch_cmd() -> Msg:
        return BatchMsg(cmds=valid)
    return _batch_cmd


# =====================================================================
# 2. Compact PyLipGloss Primitives (Visual Width + Box Styling)
# =====================================================================

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)

def char_width(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Cc", "Cf", "Mn", "Me"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1

def visual_width(text: str) -> int:
    return sum(char_width(ch) for ch in strip_ansi(text))

def pad_right(line: str, width: int) -> str:
    shortfall = max(0, width - visual_width(line))
    return line + (" " * shortfall)

def truncate_ansi(line: str, max_w: int) -> str:
    if visual_width(line) <= max_w:
        return line
    out, cur_w, i = [], 0, 0
    while i < len(line):
        m = ANSI_RE.match(line, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        w = char_width(line[i])
        if cur_w + w > max_w:
            break
        out.append(line[i])
        cur_w += w
        i += 1
    return "".join(out) + "\x1b[0m"

def fg_hex(hex_str: str) -> str:
    r, g, b = int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
    return f"\x1b[38;2;{r};{g};{b}m"

def bg_hex(hex_str: str) -> str:
    r, g, b = int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16)
    return f"\x1b[48;2;{r};{g};{b}m"

def render_box(
    content: str,
    width: int,
    border_color: str = "#6C5CE7",
    title: str = "",
    double_border: bool = False,
) -> str:
    """Renders a bordered box around content with an optional inline top title."""
    tl, tr, bl, br, h, v = (
        ("╔", "╗", "╚", "╝", "═", "║")
        if double_border
        else ("╭", "╮", "╰", "╯", "─", "│")
    )
    b_col = fg_hex(border_color)
    rst = "\x1b[0m"
    inner_w = max(1, width - 2)

    if title:
        title_str = f" {title} "
        title_w = visual_width(title_str)
        rem = max(0, inner_w - title_w - 1)
        top = f"{b_col}{tl}{h}{rst}{title_str}{b_col}{h * rem}{tr}{rst}"
    else:
        top = f"{b_col}{tl}{h * inner_w}{tr}{rst}"

    bot = f"{b_col}{bl}{h * inner_w}{br}{rst}"
    rows = [top]
    for line in content.split("\n"):
        clipped = pad_right(truncate_ansi(line, inner_w), inner_w)
        rows.append(f"{b_col}{v}{rst}{clipped}{b_col}{v}{rst}")
    rows.append(bot)
    return "\n".join(rows)


# =====================================================================
# 3. Bubble #1: Reusable `TextInput` Component (bubbles/textinput)
# =====================================================================

@dataclass(frozen=True)
class TextInput:
    prompt: str = "> "
    placeholder: str = "Type something..."
    value: str = ""
    cursor: int = 0
    offset: int = 0
    width: int = 40
    focused: bool = True

    def focus(self) -> "TextInput":
        return replace(self, focused=True)

    def blur(self) -> "TextInput":
        return replace(self, focused=False)

    def set_value(self, text: str) -> "TextInput":
        return replace(self, value=text, cursor=len(text))._sync_viewport()

    def reset(self) -> "TextInput":
        return replace(self, value="", cursor=0, offset=0)

    def _sync_viewport(self) -> "TextInput":
        """Scrolls the horizontal text window so the cursor is always visible."""
        text_w = max(1, self.width - visual_width(self.prompt) - 1)
        offset = self.offset
        if self.cursor < offset:
            offset = self.cursor
        elif self.cursor >= offset + text_w:
            offset = self.cursor - text_w + 1
        return replace(self, offset=max(0, offset))

    def update(self, msg: Msg) -> Tuple["TextInput", Optional[Cmd]]:
        if not self.focused:
            return self, None

        # Handle Bracketed Paste (strip newlines for single-line input)
        if isinstance(msg, PasteMsg):
            clean = msg.text.replace("\n", " ")
            new_val = self.value[:self.cursor] + clean + self.value[self.cursor:]
            return replace(self, value=new_val, cursor=self.cursor + len(clean))._sync_viewport(), None

        if isinstance(msg, KeyMsg):
            k = msg.key
            val = self.value
            cur = self.cursor

            if k == "left" or k == "ctrl+b":
                return replace(self, cursor=max(0, cur - 1))._sync_viewport(), None
            if k == "right" or k == "ctrl+f":
                return replace(self, cursor=min(len(val), cur + 1))._sync_viewport(), None
            if k == "home" or k == "ctrl+a":
                return replace(self, cursor=0)._sync_viewport(), None
            if k == "end" or k == "ctrl+e":
                return replace(self, cursor=len(val))._sync_viewport(), None
            if k == "backspace":
                if cur > 0:
                    new_val = val[:cur - 1] + val[cur:]
                    return replace(self, value=new_val, cursor=cur - 1)._sync_viewport(), None
                return self, None
            if k == "delete" or k == "ctrl+d":
                if cur < len(val):
                    new_val = val[:cur] + val[cur + 1:]
                    return replace(self, value=new_val)._sync_viewport(), None
                return self, None
            if k == "ctrl+u":  # Delete from cursor to start of line
                return replace(self, value=val[cur:], cursor=0)._sync_viewport(), None
            if k == "ctrl+k":  # Delete from cursor to end of line
                return replace(self, value=val[:cur])._sync_viewport(), None
            if k == "ctrl+w":  # Delete previous word
                stripped = val[:cur].rstrip()
                last_space = stripped.rfind(" ")
                new_cur = 0 if last_space == -1 else last_space + 1
                return replace(self, value=val[:new_cur] + val[cur:], cursor=new_cur)._sync_viewport(), None

            # Printable character insertion
            if len(k) == 1 and ord(k) >= 32:
                new_val = val[:cur] + k + val[cur:]
                return replace(self, value=new_val, cursor=cur + 1)._sync_viewport(), None

        return self, None

    def view(self) -> str:
        prompt_col = fg_hex("#00CEC9") if self.focused else fg_hex("#636E72")
        styled_prompt = f"{prompt_col}\x1b[1m{self.prompt}\x1b[0m"
        text_w = max(1, self.width - visual_width(self.prompt))

        # Placeholder when empty
        if not self.value:
            if self.focused:
                first = self.placeholder[0] if self.placeholder else " "
                rest = self.placeholder[1:text_w]
                cursor_cell = f"{bg_hex('#00CEC9')}{fg_hex('#1E272E')}{first}\x1b[0m"
                dim_rest = f"\x1b[2m{rest}\x1b[0m"
                return pad_right(styled_prompt + cursor_cell + dim_rest, self.width)
            return pad_right(f"{styled_prompt}\x1b[2m{self.placeholder[:text_w]}\x1b[0m", self.width)

        # Render visible horizontal window with block cursor
        vis_end = self.offset + text_w - 1
        before = self.value[self.offset:self.cursor]
        cursor_ch = self.value[self.cursor] if self.cursor < len(self.value) else " "
        after = self.value[self.cursor + 1:vis_end + 1] if self.cursor < len(self.value) else ""

        if self.focused:
            cur_rendered = f"{bg_hex('#00CEC9')}{fg_hex('#1E272E')}\x1b[1m{cursor_ch}\x1b[0m"
            line = f"{styled_prompt}{before}{cur_rendered}{after}"
        else:
            vis_slice = self.value[self.offset:self.offset + text_w]
            line = f"{styled_prompt}{vis_slice}"

        return pad_right(line, self.width)


# =====================================================================
# 4. Bubble #2: Reusable `Viewport` Component (bubbles/viewport)
# =====================================================================

@dataclass(frozen=True)
class Viewport:
    width: int = 60
    height: int = 10
    lines: Tuple[str, ...] = field(default_factory=tuple)
    y_offset: int = 0
    focused: bool = False
    mouse_wheel_enabled: bool = True
    mouse_wheel_delta: int = 3

    @property
    def max_y_offset(self) -> int:
        return max(0, len(self.lines) - self.height)

    @property
    def scroll_percent(self) -> float:
        if self.max_y_offset == 0:
            return 1.0
        return min(1.0, max(0.0, self.y_offset / self.max_y_offset))

    def set_content(self, content: str, auto_scroll_bottom: bool = False) -> "Viewport":
        new_lines = tuple(content.split("\n")) if content else ()
        new_max = max(0, len(new_lines) - self.height)
        new_offset = new_max if auto_scroll_bottom else min(self.y_offset, new_max)
        return replace(self, lines=new_lines, y_offset=new_offset)

    def goto_top(self) -> "Viewport":
        return replace(self, y_offset=0)

    def goto_bottom(self) -> "Viewport":
        return replace(self, y_offset=self.max_y_offset)

    def scroll_by(self, delta: int) -> "Viewport":
        clamped = max(0, min(self.max_y_offset, self.y_offset + delta))
        return replace(self, y_offset=clamped)

    def update(self, msg: Msg) -> Tuple["Viewport", Optional[Cmd]]:
        # Mouse wheel scrolling works even when unfocused if enabled
        if self.mouse_wheel_enabled and isinstance(msg, MouseMsg) and msg.action == "scroll":
            if msg.button == "wheel_up":
                return self.scroll_by(-self.mouse_wheel_delta), None
            if msg.button == "wheel_down":
                return self.scroll_by(self.mouse_wheel_delta), None

        if not self.focused:
            return self, None

        if isinstance(msg, KeyMsg):
            k = msg.key
            if k in ("up", "k"):
                return self.scroll_by(-1), None
            if k in ("down", "j"):
                return self.scroll_by(1), None
            if k in ("pgup", "b", "ctrl+u"):
                return self.scroll_by(-max(1, self.height // 2)), None
            if k in ("pgdn", "f", " ", "ctrl+d"):
                return self.scroll_by(max(1, self.height // 2)), None
            if k in ("home", "g"):
                return self.goto_top(), None
            if k in ("end", "G"):
                return self.goto_bottom(), None

        return self, None

    def view(self) -> str:
        vis = list(self.lines[self.y_offset:self.y_offset + self.height])
        while len(vis) < self.height:
            vis.append("")

        # Render a proportional right-hand scrollbar thumb
        content_w = max(1, self.width - 2)
        total = len(self.lines)
        out_rows = []

        thumb_size = max(1, int(round((self.height / max(total, self.height)) * self.height)))
        thumb_start = int(round(self.scroll_percent * (self.height - thumb_size)))

        for i, line in enumerate(vis):
            padded = pad_right(truncate_ansi(line, content_w), content_w)
            if total > self.height and thumb_start <= i < thumb_start + thumb_size:
                bar = f" {fg_hex('#00CEC9')}┃\x1b[0m"
            else:
                bar = f" {fg_hex('#2D3436')}│\x1b[0m"
            out_rows.append(padded + bar)

        return "\n".join(out_rows)


# =====================================================================
# 5. Root Parent Model Composing `Viewport` + `TextInput`
# =====================================================================

INITIAL_ENTRIES = [
    f"{fg_hex('#A29BFE')}[System]{'\x1b[0m'} Welcome to BubblePy Component Composer! 🚀",
    f"{fg_hex('#A29BFE')}[System]{'\x1b[0m'} Press \x1b[1mTab\x1b[0m to switch focus between the TextInput and Viewport.",
    f"{fg_hex('#A29BFE')}[System]{'\x1b[0m'} Use the \x1b[1mMouse Wheel\x1b[0m anytime to scroll the Viewport.",
] + [
    f"{fg_hex('#636E72')}[12:00:{i:02d}]{'\x1b[0m'} Event #{i:02d}: Cluster node health check passed (latency {10 + (i % 9)}ms)"
    for i in range(1, 26)
]


@dataclass(frozen=True)
class AppModel:
    width: int = 80
    height: int = 24
    entries: Tuple[str, ...] = tuple(INITIAL_ENTRIES)
    viewport: Viewport = field(default_factory=Viewport)
    text_input: TextInput = field(
        default_factory=lambda: TextInput(
            prompt="💬 Message > ",
            placeholder="Type a message (or paste text) and press Enter...",
            focused=True,
        )
    )

    def init_layout(self, w: int, h: int) -> "AppModel":
        box_w = max(44, min(w - 2, 96))
        vp_h = max(5, h - 10)
        vp = replace(
            self.viewport,
            width=box_w - 4,
            height=vp_h,
        ).set_content("\n".join(self.entries), auto_scroll_bottom=True)
        ti = replace(self.text_input, width=box_w - 4)._sync_viewport()
        return replace(self, width=w, height=h, viewport=vp, text_input=ti)

    def update(self, msg: Msg) -> Tuple["AppModel", Optional[Cmd], bool]:
        # 1. Global Resize Handling
        if isinstance(msg, WindowSizeMsg):
            return self.init_layout(msg.width, msg.height), None, False

        # 2. Global Keybindings (Quit, Focus Toggle, Submit Input)
        if isinstance(msg, KeyMsg):
            if msg.key == "ctrl+c" or (msg.key == "q" and not self.text_input.focused):
                return self, None, True

            if msg.key == "tab":
                flip_to_vp = self.text_input.focused
                return replace(
                    self,
                    text_input=self.text_input.blur() if flip_to_vp else self.text_input.focus(),
                    viewport=replace(self.viewport, focused=flip_to_vp),
                ), None, False

            if msg.key == "enter" and self.text_input.focused:
                raw = self.text_input.value.strip()
                if raw:
                    new_entry = f"{fg_hex('#00CEC9')}[You]{'\x1b[0m'} {raw}"
                    new_entries = self.entries + (new_entry,)
                    new_vp = self.viewport.set_content(
                        "\n".join(new_entries), auto_scroll_bottom=True
                    )
                    return replace(
                        self,
                        entries=new_entries,
                        viewport=new_vp,
                        text_input=self.text_input.reset(),
                    ), None, False
                return self, None, False

        # 3. Delegate Msg to Child Components and Batch Returned Cmds
        new_ti, cmd_ti = self.text_input.update(msg)
        new_vp, cmd_vp = self.viewport.update(msg)

        return (
            replace(self, text_input=new_ti, viewport=new_vp),
            batch(cmd_ti, cmd_vp),
            False,
        )

    def view(self) -> str:
        box_w = max(44, min(self.width - 2, 96))
        pct = int(round(self.viewport.scroll_percent * 100))

        # Viewport Box
        vp_border = "#00CEC9" if self.viewport.focused else "#6C5CE7"
        vp_focus_badge = f"{fg_hex('#00CEC9')}● FOCUSED\x1b[0m" if self.viewport.focused else "\x1b[2m○ Tab to focus\x1b[0m"
        vp_title = f"\x1b[1mActivity Feed\x1b[0m ({len(self.entries)} items • {pct:3d}%) [{vp_focus_badge}]"
        vp_box = render_box(
            f" {self.viewport.view().replace(chr(10), chr(10) + ' ')}",
            width=box_w,
            border_color=vp_border,
            title=vp_title,
            double_border=self.viewport.focused,
        )

        # TextInput Box
        ti_border = "#00CEC9" if self.text_input.focused else "#636E72"
        ti_badge = f"{fg_hex('#00CEC9')}● FOCUSED\x1b[0m" if self.text_input.focused else "\x1b[2m○ Tab to focus\x1b[0m"
        ti_title = f"\x1b[1mComposer\x1b[0m [{ti_badge}]"
        ti_box = render_box(
            f" {self.text_input.view()}",
            width=box_w,
            border_color=ti_border,
            title=ti_title,
            double_border=self.text_input.focused,
        )

        help_line = (
            f"\x1b[2mTab: Switch Focus • Enter: Send • Mouse Wheel / ↑↓ / PgUp / PgDn: Scroll • "
            f"Ctrl+W/U/K: Edit • Ctrl+C: Quit\x1b[0m"
        )

        out = "\n".join([vp_box, ti_box, help_line])
        # Append \x1b[K to each line and \x1b[J at the end for artifact-free redraws
        return "\x1b[H" + "\n".join(line + "\x1b[K" for line in out.split("\n")) + "\x1b[J"


# =====================================================================
# 6. Non-Blocking ANSI Input Parser & Runtime Loop
# =====================================================================

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"
SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")
CSI_RE = re.compile(r"^\x1b\[([\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])")

CSI_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "Z": "shift+tab",
    "1~": "home", "2~": "insert", "3~": "delete", "4~": "end",
    "5~": "pgup", "6~": "pgdn", "7~": "home", "8~": "end",
}

CONTROL_CHARS = {
    "\r": "enter", "\n": "enter", "\t": "tab",
    "\x7f": "backspace", "\x08": "backspace",
}


class AnsiInputParser:
    ESC_TIMEOUT = 0.030

    def __init__(self, loop: asyncio.AbstractEventLoop, emit: Callable[[Msg], None]):
        self.loop = loop
        self.emit = emit
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buf = ""
        self.in_paste = False
        self.paste_buf = ""
        self.timer: Optional[asyncio.TimerHandle] = None

    def feed(self, data: bytes) -> None:
        self.buf += self.decoder.decode(data, final=False)
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self._process()

    def _on_timeout(self) -> None:
        self.timer = None
        if self.in_paste:
            self.in_paste = False
            self.emit(PasteMsg((self.paste_buf + self.buf).replace("\r\n", "\n").replace("\r", "\n")))
            self.paste_buf = self.buf = ""
            return
        if self.buf == "\x1b":
            self.buf = ""
            self.emit(KeyMsg("esc"))
        elif self.buf:
            ch, self.buf = self.buf[0], self.buf[1:]
            self.emit(KeyMsg(self._decode_char(ch)))
            self._process()

    def _process(self) -> None:
        while self.buf:
            if self.in_paste:
                idx = self.buf.find(PASTE_END)
                if idx != -1:
                    self.paste_buf += self.buf[:idx]
                    self.buf = self.buf[idx + len(PASTE_END):]
                    self.in_paste = False
                    self.emit(PasteMsg(self.paste_buf.replace("\r\n", "\n").replace("\r", "\n")))
                    self.paste_buf = ""
                    continue
                self.paste_buf += self.buf
                self.buf = ""
                self.timer = self.loop.call_later(0.5, self._on_timeout)
                return

            if self.buf[0] == "\x1b":
                if self.buf.startswith(PASTE_START):
                    self.buf = self.buf[len(PASTE_START):]
                    self.in_paste = True
                    self.paste_buf = ""
                    continue
                if PASTE_START.startswith(self.buf) or len(self.buf) == 1:
                    self.timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                    return
                if self.buf[1] == "[":
                    m_mouse = SGR_MOUSE_RE.match(self.buf)
                    if m_mouse:
                        self.buf = self.buf[m_mouse.end():]
                        cb, x, y, st = int(m_mouse.group(1)), int(m_mouse.group(2)), int(m_mouse.group(3)), m_mouse.group(4)
                        if cb & 64:
                            btn = "wheel_up" if (cb & 3) == 0 else "wheel_down"
                            self.emit(MouseMsg(x, y, btn, "scroll"))
                        else:
                            btn = {0: "left", 1: "middle", 2: "right", 3: "none"}[cb & 3]
                            act = "release" if st == "m" else ("motion" if (cb & 32) else "press")
                            self.emit(MouseMsg(x, y, btn, act))
                        continue
                    m_csi = CSI_RE.match(self.buf)
                    if m_csi:
                        body = m_csi.group(1)
                        self.buf = self.buf[m_csi.end():]
                        self.emit(KeyMsg(CSI_KEYS.get(body, f"csi:{body}")))
                        continue
                    self.timer = self.loop.call_later(self.ESC_TIMEOUT, self._on_timeout)
                    return
                ch = self.buf[1]
                self.buf = self.buf[2:]
                self.emit(KeyMsg(f"alt+{self._decode_char(ch)}"))
                continue

            ch, self.buf = self.buf[0], self.buf[1:]
            self.emit(KeyMsg(self._decode_char(ch)))

    def _decode_char(self, ch: str) -> str:
        if ch in CONTROL_CHARS:
            return CONTROL_CHARS[ch]
        code = ord(ch)
        if 1 <= code <= 26:
            return f"ctrl+{chr(code + 96)}"
        return ch


async def run_app():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Msg] = asyncio.Queue()
    parser = AnsiInputParser(loop, queue.put_nowait)

    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)

    async def execute_cmd(cmd: Cmd):
        msg = await cmd()
        if isinstance(msg, BatchMsg):
            for sub in msg.cmds:
                asyncio.create_task(execute_cmd(sub))
        elif msg is not None:
            await queue.put(msg)

    def on_stdin():
        try:
            data = os.read(fd, 4096)
            if data:
                parser.feed(data)
        except BlockingIOError:
            pass

    def on_resize():
        try:
            sz = os.get_terminal_size(fd)
            queue.put_nowait(WindowSizeMsg(sz.columns, sz.lines))
        except OSError:
            pass

    try:
        tty.setraw(fd)
        new_term = termios.tcgetattr(fd)
        new_term[1] |= termios.OPOST
        termios.tcsetattr(fd, termios.TCSANOW, new_term)

        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b[?2004h\x1b[2J")
        sys.stdout.flush()

        loop.add_reader(fd, on_stdin)
        loop.add_signal_handler(signal.SIGWINCH, on_resize)
        on_resize()

        model = AppModel()
        while True:
            msg = await queue.get()
            model, cmd, should_quit = model.update(msg)
            if should_quit:
                break
            if cmd:
                asyncio.create_task(execute_cmd(cmd))
            sys.stdout.write(model.view())
            sys.stdout.flush()

    finally:
        loop.remove_reader(fd)
        loop.remove_signal_handler(signal.SIGWINCH)
        sys.stdout.write("\x1b[?2004l\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    asyncio.run(run_app())
