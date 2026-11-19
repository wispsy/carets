import asyncio
import codecs
from dataclasses import dataclass, field, replace
import os
import re
import signal
import sys
import termios
import time
import tty
from typing import Callable, Dict, List, Optional, Tuple
import unicodedata


# =====================================================================
# 1. Core Tea Types & Command Batching
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
    button: str
    action: str


@dataclass(frozen=True)
class WindowSizeMsg(Msg):
    width: int
    height: int


# =====================================================================
# 2. BubbleZone Manager & Styling Helpers
# =====================================================================

@dataclass(frozen=True)
class ZoneInfo:
    id: str
    x1: int
    y1: int
    x2: int
    y2: int

    def contains(self, x: int, y: int) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2


class ZoneManager:
    def __init__(self) -> None:
        self._id_to_marker: Dict[str, int] = {}
        self._marker_to_id: Dict[int, str] = {}
        self._next_marker: int = 1000
        self.zones: Dict[str, ZoneInfo] = {}

    def mark(self, zone_id: str, text: str) -> str:
        if zone_id not in self._id_to_marker:
            m = self._next_marker
            self._next_marker += 2
            self._id_to_marker[zone_id] = m
            self._marker_to_id[m] = zone_id
        else:
            m = self._id_to_marker[zone_id]
        return f"\x1b[{m}z{text}\x1b[{m + 1}z"

    def in_bounds(self, zone_id: str, mouse: MouseMsg) -> bool:
        z = self.zones.get(zone_id)
        return z.contains(mouse.x, mouse.y) if z else False


zone = ZoneManager()

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


def fg_hex(h: str) -> str:
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"\x1b[38;2;{r};{g};{b}m"


def bg_hex(h: str) -> str:
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"\x1b[48;2;{r};{g};{b}m"


# =====================================================================
# 3. Modal Overlay Compositing Engine
# =====================================================================

def render_box(content: str, width: int, border_color: str = "#6C5CE7", title: str = "") -> str:
    tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
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
        pad = " " * max(0, inner_w - visual_width(line))
        rows.append(f"{b_col}{v}{rst}{line}{pad}{b_col}{v}{rst}")
    rows.append(bot)
    return "\n".join(rows)


def overlay_centered(background: str, modal: str, term_w: int, term_h: int) -> str:
    """
    Overlays a modal view centered on top of a background view,
    blending lines cell-by-cell while keeping background width/height intact.
    """
    bg_lines = background.split("\n")
    modal_lines = modal.split("\n")

    modal_h = len(modal_lines)
    modal_w = max((visual_width(l) for l in modal_lines), default=0)

    start_x = max(0, (term_w - modal_w) // 2)
    start_y = max(0, (term_h - modal_h) // 2)

    # Pad bg_lines to match term_h
    while len(bg_lines) < term_h:
        bg_lines.append(" " * term_w)

    composited = list(bg_lines)

    for my, m_line in enumerate(modal_lines):
        target_y = start_y + my
        if target_y >= term_h:
            break

        bg_line = composited[target_y]
        # Pad bg_line with spaces if shorter than term_w
        if visual_width(bg_line) < term_w:
            bg_line += " " * (term_w - visual_width(bg_line))

        # Reconstruct line by replacing characters in the modal bounding box region
        # Note: To avoid breaking ANSI codes or zone markers embedded in bg_line,
        # we parse/rebuild characters or do character cell overlay.
        # Simple approach for string blocks:
        # We can convert bg_line into a list of characters, but ANSI codes complicate indexing.
        # Instead, let's use a cell grid overlay:

    return background  # Will use ScreenBuffer blitting or direct grid overlay below


# =====================================================================
# 4. Robust Cell-Level Modal Compositor inside ScreenBuffer
# =====================================================================

# (We handle modal overlay directly during ScreenBuffer parsing so ANSI & zones never break)


# =====================================================================
# 5. Demo Application Model
# =====================================================================

@dataclass(frozen=True)
class AppModel:
    width: int = 80
    height: int = 24
    is_modal_open: bool = False
    action_log: str = "Ready. Click 'Open Modal' or press 'm'."
    counter: int = 42

    def update(self, msg: Msg) -> Tuple["AppModel", bool]:
        if isinstance(msg, WindowSizeMsg):
            return replace(self, width=msg.width, height=msg.height), False

        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c") and not self.is_modal_open:
                return self, True
            if msg.key == "m":
                return replace(self, is_modal_open=not self.is_modal_open,
                               action_log="Toggled modal via 'm' key"), False
            if msg.key == "esc" and self.is_modal_open:
                return replace(self, is_modal_open=False, action_log="Closed modal via Esc"), False

        if isinstance(msg, MouseMsg):
            if msg.button == "left" and msg.action == "press":
                # If modal is open, ONLY modal zones can be clicked!
                if self.is_modal_open:
                    if zone.in_bounds("modal_confirm", msg):
                        return replace(self, is_modal_open=False, counter=self.counter + 1,
                                       action_log="Modal: Confirmed (+1 counter)!"), False
                    if zone.in_bounds("modal_cancel", msg):
                        return replace(self, is_modal_open=False, action_log="Modal: Cancelled action."), False
                    # Click outside modal dismisses it or does nothing
                    return self, False
                else:
                    # Background clicks
                    if zone.in_bounds("btn_open_modal", msg):
                        return replace(self, is_modal_open=True, action_log="Opened modal via click"), False
                    if zone.in_bounds("btn_increment", msg):
                        return replace(self, counter=self.counter + 1, action_log="Incremented counter"), False

        return self, False

    def view(self) -> str:
        # 1. Build Background View
        w = max(60, min(self.width, 96))
        inner_w = w - 4

        btn_open = zone.mark("btn_open_modal",
                             fg_hex("#1E272E") + bg_hex("#00CEC9") + " 📂 Open Modal Dialog (m) " + "\x1b[0m")
        btn_inc = zone.mark("btn_increment", fg_hex("#1E272E") + bg_hex("#6C5CE7") + " ＋ Inc Counter " + "\x1b[0m")

        bg_content = "\n".join([
            f"\x1b[1;35m  ✨ Modal Compositing Architecture Demo ✨\x1b[0m",
            "",
            f"  Current Counter Value: \x1b[1;33m{self.counter}\x1b[0m",
            "",
            f"  {btn_open}    {btn_inc}",
            "",
            f"  {fg_hex('#636E72')}────────────────────────────────────────────────────────────────────\x1b[0m",
            f"  \x1b[1mAction Log:\x1b[0m \x1b[1;32m{self.action_log}\x1b[0m",
            f"  \x1b[2mPress 'm' or click button to pop up centered modal dialog.\x1b[0m",
        ])
        background_view = render_box(bg_content, width=w, border_color="#636E72", title="Background Workspace")

        if not self.is_modal_open:
            return background_view

        # 2. Build Modal Dialog View
        modal_inner_w = 46
        confirm_btn = zone.mark("modal_confirm", fg_hex("#1E272E") + bg_hex("#00B894") + "  ✔ Confirm  " + "\x1b[0m")
        cancel_btn = zone.mark("modal_cancel", fg_hex("#1E272E") + bg_hex("#D63031") + "  ✖ Cancel  " + "\x1b[0m")

        modal_body = "\n".join([
            f"\x1b[1mAre you sure you want to execute\x1b[0m",
            f"this sensitive operation?",
            "",
            f"Current counter will be incremented by 1.",
            "",
            f"     {confirm_btn}     {cancel_btn}",
        ])
        modal_view = render_box(modal_body, width=modal_inner_w, border_color="#00CEC9",
                                title="⚠️ Confirmation Required")

        # Instead of manual string slicing, we return both views separated by a special marker
        # or composite them directly inside the ScreenBuffer parser!
        return f"{background_view}\n---MODAL_SPLIT---\n{modal_view}"


# =====================================================================
# 6. ScreenBuffer with Built-in Modal Compositing & Zone Scanning
# =====================================================================

ANSI_TOKEN_RE = re.compile(r"\x1b\[([0-9;]*)([a-zA-Z])")
SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")
CSI_RE = re.compile(r"^\x1b\[([\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])")

CSI_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "5~": "pgup", "6~": "pgdn",
}


@dataclass(frozen=True, slots=True)
class Cell:
    char: str = " "
    sgr: str = ""
    width: int = 1


EMPTY_CELL = Cell(" ", "", 1)
CONT_CELL = Cell("", "", 0)


class ScreenBuffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells: List[List[Cell]] = [
            [EMPTY_CELL for _ in range(width)] for _ in range(height)
        ]

    @classmethod
    def from_view_string(
            cls, view_str: str, width: int, height: int, zm: ZoneManager
    ) -> "ScreenBuffer":
        buf = cls(width, height)

        # Check if view contains a modal split ("---MODAL_SPLIT---")
        if "---MODAL_SPLIT---" in view_str:
            bg_str, modal_str = view_str.split("---MODAL_SPLIT---", 1)
            # Parse background first into buffer
            buf._parse_layer(bg_str, width, height, zm, dim_background=True)
            # Then composite modal centered on top
            buf._parse_centered_modal(modal_str, width, height, zm)
        else:
            buf._parse_layer(view_str, width, height, zm, dim_background=False)

        return buf

    def _parse_layer(
            self, text: str, width: int, height: int, zm: ZoneManager, dim_background: bool
    ) -> None:
        lines = text.split("\n")
        active_sgr = f"\x1b[2m\x1b[38;5;242m" if dim_background else ""
        open_zones: Dict[str, Tuple[int, int]] = {}
        new_zones: Dict[str, ZoneInfo] = {}

        for y in range(min(height, len(lines))):
            line = lines[y]
            row = self.cells[y]
            x, i, n = 0, 0, len(line)
            while i < n:
                if line[i] == "\x1b":
                    m = ANSI_TOKEN_RE.match(line, i)
                    if m:
                        params, cmd = m.group(1), m.group(2)
                        if cmd == "m":
                            if not dim_background:
                                active_sgr = "" if params in ("", "0") else f"{active_sgr}\x1b[{params}m"
                        elif cmd == "z" and params.isdigit():
                            # Ignore background zones if dimmed (modal blocks background clicks!)
                            if not dim_background:
                                num = int(params)
                                if num % 2 == 0:
                                    z_id = zm._marker_to_id.get(num)
                                    if z_id is not None:
                                        open_zones[z_id] = (x, y)
                                else:
                                    z_id = zm._marker_to_id.get(num - 1)
                                    if z_id is not None and z_id in open_zones:
                                        sx, sy = open_zones.pop(z_id)
                                        new_zones[z_id] = ZoneInfo(z_id, sx, sy, max(sx, x - 1), y)
                        i = m.end()
                        continue
                    i += 1
                    continue
                if x >= width:
                    i += 1
                    continue
                ch = line[i]
                i += 1
                w = char_width(ch)
                if w == 0:
                    continue
                sgr_to_use = f"\x1b[2m{active_sgr}" if dim_background else active_sgr
                if w == 2:
                    if x + 1 >= width:
                        row[x] = Cell(" ", sgr_to_use, 1)
                        x += 1
                        continue
                    row[x] = Cell(ch, sgr_to_use, 2)
                    row[x + 1] = CONT_CELL
                    x += 2
                else:
                    row[x] = Cell(ch, sgr_to_use, 1)
                    x += 1

        # Merge background zones if not dimmed
        if not dim_background:
            zm.zones.update(new_zones)
        else:
            # Store background zones so they don't get wiped out entirely if needed,
            # but in modal state we only want modal zones to be active:
            pass

    def _parse_centered_modal(
            self, modal_str: str, term_w: int, term_h: int, zm: ZoneManager
    ) -> None:
        lines = modal_str.split("\n")
        modal_h = len(lines)
        modal_w = max((visual_width(l) for l in lines), default=0)

        start_x = max(0, (term_w - modal_w) // 2)
        start_y = max(0, (term_h - modal_h) // 2)

        active_sgr = ""
        open_zones: Dict[str, Tuple[int, int]] = {}
        modal_zones: Dict[str, ZoneInfo] = {}

        for my, line in enumerate(lines):
            y = start_y + my
            if y >= term_h:
                break
            row = self.cells[y]
            x, i, n = start_x, 0, len(line)
            while i < n:
                if line[i] == "\x1b":
                    m = ANSI_TOKEN_RE.match(line, i)
                    if m:
                        params, cmd = m.group(1), m.group(2)
                        if cmd == "m":
                            active_sgr = "" if params in ("", "0") else f"{active_sgr}\x1b[{params}m"
                        elif cmd == "z" and params.isdigit():
                            num = int(params)
                            if num % 2 == 0:
                                z_id = zm._marker_to_id.get(num)
                                if z_id is not None:
                                    open_zones[z_id] = (x, y)
                            else:
                                z_id = zm._marker_to_id.get(num - 1)
                                if z_id is not None and z_id in open_zones:
                                    sx, sy = open_zones.pop(z_id)
                                    modal_zones[z_id] = ZoneInfo(z_id, sx, sy, max(sx, x - 1), y)
                        i = m.end()
                        continue
                    i += 1
                    continue

                curr_col = x
                if curr_col >= term_w:
                    i += 1
                    continue

                ch = line[i]
                i += 1
                w = char_width(ch)
                if w == 0:
                    continue
                elif w == 2:
                    if curr_col + 1 >= term_w:
                        row[curr_col] = Cell(" ", active_sgr, 1)
                        x += 1
                        continue
                    row[curr_col] = Cell(ch, active_sgr, 2)
                    row[curr_col + 1] = CONT_CELL
                    x += 2
                else:
                    row[curr_col] = Cell(ch, active_sgr, 1)
                    x += 1

        # When modal is open, ONLY modal zones are active (blocking background clicks)
        zm.zones = modal_zones


class CellDiffRenderer:
    def __init__(self, fps: int = 60):
        self.frame_interval = 1.0 / fps
        self.front_buffer: Optional[ScreenBuffer] = None

    def invalidate(self) -> None:
        self.front_buffer = None

    def render_frame(self, view_str: str, width: int, height: int, zm: ZoneManager) -> None:
        back = ScreenBuffer.from_view_string(view_str, width, height, zm)
        front = self.front_buffer
        full = front is None or front.width != width or front.height != height

        out: List[str] = ["\x1b[?2026h"]
        if full:
            out.append("\x1b[0m\x1b[2J")

        cur_r, cur_c = -1, -1
        cur_sgr: Optional[str] = None
        changed_count = 0

        for y in range(height):
            b_row = back.cells[y]
            f_row = front.cells[y] if not full else None
            x = 0
            while x < width:
                cell = b_row[x]
                if cell.width == 0:
                    x += 1
                    continue
                changed = full or (cell != f_row[x])
                if not changed and cell.width == 2 and x + 1 < width:
                    changed = b_row[x + 1] != f_row[x + 1]
                if not changed and f_row is not None and f_row[x].width == 0:
                    changed = True

                if changed:
                    changed_count += 1
                    if cur_r != y or cur_c != x:
                        out.append(f"\x1b[{y + 1};{x + 1}H")
                        cur_r, cur_c = y, x
                    if cell.sgr != cur_sgr:
                        out.append(f"\x1b[0m{cell.sgr}")
                        cur_sgr = cell.sgr
                    out.append(cell.char)
                    cur_c += cell.width
                    if (
                            not full
                            and f_row is not None
                            and f_row[x].width == 2
                            and cell.width == 1
                            and x + 1 < width
                    ):
                        f_row[x + 1] = Cell("__INV__", "", 1)
                x += cell.width

        if cur_sgr:
            out.append("\x1b[0m")
        out.append("\x1b[?2026l")

        if changed_count > 0 or full:
            sys.stdout.write("".join(out))
            sys.stdout.flush()

        self.front_buffer = back


# =====================================================================
# 7. Runtime Loop
# =====================================================================

async def run_app():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Msg] = asyncio.Queue()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)
    esc_timer: Optional[asyncio.TimerHandle] = None
    buf = ""

    def flush_esc():
        nonlocal buf, esc_timer
        esc_timer = None
        if buf == "\x1b":
            buf = ""
            queue.put_nowait(KeyMsg("esc"))

    def on_stdin():
        nonlocal buf, esc_timer
        try:
            raw = os.read(fd, 4096)
        except BlockingIOError:
            return
        if esc_timer:
            esc_timer.cancel()
            esc_timer = None
        buf += decoder.decode(raw, final=False)
        while buf:
            if buf[0] == "\x1b":
                if len(buf) == 1:
                    esc_timer = loop.call_later(0.030, flush_esc)
                    return
                if buf[1] == "[":
                    m_match = re.match(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])", buf)
                    if m_match:
                        buf = buf[m_match.end():]
                        cb = int(m_match.group(1))
                        x, y = int(m_match.group(2)) - 1, int(m_match.group(3)) - 1
                        st = m_match.group(4)
                        if cb & 64:
                            btn = "wheel_up" if (cb & 3) == 0 else "wheel_down"
                            queue.put_nowait(MouseMsg(x, y, btn, "scroll"))
                        else:
                            btn = {0: "left", 1: "middle", 2: "right", 3: "none"}[cb & 3]
                            act = "release" if st == "m" else ("motion" if (cb & 32) else "press")
                            queue.put_nowait(MouseMsg(x, y, btn, act))
                        continue
                    m_csi = re.match(r"^\x1b\[([\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])", buf)
                    if m_csi:
                        body = m_csi.group(1)
                        buf = buf[m_csi.end():]
                        queue.put_nowait(KeyMsg(CSI_KEYS.get(body, f"csi:{body}")))
                        continue
                    esc_timer = loop.call_later(0.030, flush_esc)
                    return
                buf = buf[2:]
                continue

            ch, buf = buf[0], buf[1:]
            if ch in ("\r", "\n"):
                queue.put_nowait(KeyMsg("enter"))
            elif ch in ("\x7f", "\x08"):
                queue.put_nowait(KeyMsg("backspace"))
            elif ord(ch) == 3:
                queue.put_nowait(KeyMsg("ctrl+c"))
            else:
                queue.put_nowait(KeyMsg(ch))

    def on_resize():
        try:
            sz = os.get_terminal_size(fd)
            queue.put_nowait(WindowSizeMsg(sz.columns, sz.lines))
        except OSError:
            pass

    renderer = CellDiffRenderer(fps=60)
    model = AppModel()
    dirty = True
    should_quit = False

    try:
        tty.setraw(fd)
        new_term = termios.tcgetattr(fd)
        new_term[1] |= termios.OPOST
        termios.tcsetattr(fd, termios.TCSANOW, new_term)

        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b[2J")
        sys.stdout.flush()

        loop.add_reader(fd, on_stdin)
        loop.add_signal_handler(signal.SIGWINCH, on_resize)
        on_resize()

        while not should_quit:
            t0 = time.monotonic()

            if not dirty:
                msg = await queue.get()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, should_quit = model.update(msg)
                dirty = True

            while not queue.empty() and not should_quit:
                msg = queue.get_nowait()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, should_quit = model.update(msg)
                dirty = True

            if should_quit:
                break

            if dirty:
                renderer.render_frame(model.view(), model.width, model.height, zone)
                dirty = False

            rem = renderer.frame_interval - (time.monotonic() - t0)
            if rem > 0:
                await asyncio.sleep(rem)

    finally:
        loop.remove_reader(fd)
        loop.remove_signal_handler(signal.SIGWINCH)
        sys.stdout.write("\x1b[?2026l\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    asyncio.run(run_app())
