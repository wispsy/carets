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
# 1. Core Tea Messages
# =====================================================================

class Msg:
    pass

@dataclass(frozen=True)
class KeyMsg(Msg):
    key: str

@dataclass(frozen=True)
class MouseMsg(Msg):
    x: int        # 0-indexed column (converted from 1-indexed SGR mouse)
    y: int        # 0-indexed row
    button: str   # "left", "middle", "right", "wheel_up", "wheel_down", "none"
    action: str   # "press", "release", "motion", "scroll"

@dataclass(frozen=True)
class WindowSizeMsg(Msg):
    width: int
    height: int


# =====================================================================
# 2. BubbleZone Equivalent: Zero-Width Markers & Bounding Boxes
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

    def relative_pos(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        """Returns (rel_x, rel_y) inside the zone, or None if out of bounds."""
        if not self.contains(x, y):
            return None
        return (x - self.x1, y - self.y1)


class ZoneManager:
    """
    Injects zero-width CSI markers (\x1b[<num>z) around any single-line or
    multi-line string block so the renderer can record its exact 2D bounding box.
    """

    def __init__(self) -> None:
        self._id_to_marker: Dict[str, int] = {}
        self._marker_to_id: Dict[int, str] = {}
        self._next_marker: int = 1000
        self.zones: Dict[str, ZoneInfo] = {}

    def mark(self, zone_id: str, text: str) -> str:
        """
        Wraps `text` (single-line or multi-line box) with invisible start/end
        markers. Even numbers = start marker, Odd numbers = end marker.
        """
        if zone_id not in self._id_to_marker:
            m_num = self._next_marker
            self._next_marker += 2
            self._id_to_marker[zone_id] = m_num
            self._marker_to_id[m_num] = zone_id
        else:
            m_num = self._id_to_marker[zone_id]

        start_seq = f"\x1b[{m_num}z"
        end_seq = f"\x1b[{m_num + 1}z"
        return f"{start_seq}{text}{end_seq}"

    def get(self, zone_id: str) -> Optional[ZoneInfo]:
        return self.zones.get(zone_id)

    def in_bounds(self, zone_id: str, mouse: MouseMsg) -> bool:
        z = self.zones.get(zone_id)
        return z.contains(mouse.x, mouse.y) if z else False

    def find_all_at(self, mouse: MouseMsg) -> List[str]:
        """Returns all zone IDs under the mouse cursor."""
        return [z_id for z_id, z in self.zones.items() if z.contains(mouse.x, mouse.y)]


# Global default ZoneManager instance (just like bubblezone.NewGlobal())
zone = ZoneManager()


# =====================================================================
# 3. PyLipGloss Layout Helpers (Ignores \x1b[...z Zone Markers Automatically!)
# =====================================================================

# Matches standard SGR (\x1b[...m) AND our custom zone markers (\x1b[...z)
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

def align_line(line: str, target_w: int, pos: float = 0.0) -> str:
    shortfall = max(0, target_w - visual_width(line))
    if shortfall == 0:
        return line
    left_p = int(round(shortfall * pos))
    return (" " * left_p) + line + (" " * (shortfall - left_p))

def join_horizontal(pos: float, *blocks: str, gap: int = 0) -> str:
    if not blocks:
        return ""
    split_b = [b.split("\n") for b in blocks]
    widths = [max((visual_width(l) for l in lines), default=0) for lines in split_b]
    max_h = max(len(lines) for lines in split_b)
    spacer = " " * gap

    cols = []
    for lines, w in zip(split_b, widths):
        extra = max_h - len(lines)
        top_p = int(round(extra * pos))
        bot_p = extra - top_p
        blank = " " * w
        cols.append(
            [blank] * top_p
            + [align_line(l, w, 0.0) for l in lines]
            + [blank] * bot_p
        )
    return "\n".join(spacer.join(row) for row in zip(*cols))

def fg_hex(h: str) -> str:
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"\x1b[38;2;{r};{g};{b}m"

def bg_hex(h: str) -> str:
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"\x1b[48;2;{r};{g};{b}m"

def make_button(label: str, bg: str, fg: str = "#FFFFFF", hovered: bool = False) -> str:
    """Renders a 3-line pill/bordered button that lights up on hover."""
    border_col = fg_hex("#00CEC9") if hovered else fg_hex(bg)
    fill_bg = bg_hex("#00CEC9") if hovered else bg_hex(bg)
    text_fg = fg_hex("#1E272E") if hovered else fg_hex(fg)
    rst = "\x1b[0m"
    inner = f"  {label}  "
    w = visual_width(inner)
    return "\n".join([
        f"{border_col}╭{'─' * w}╮{rst}",
        f"{border_col}│{fill_bg}{text_fg}\x1b[1m{inner}{rst}{border_col}│{rst}",
        f"{border_col}╰{'─' * w}╯{rst}",
    ])


# =====================================================================
# 4. ScreenBuffer & 60fps Differ with Integrated Zone Scanning
# =====================================================================

ANSI_TOKEN_RE = re.compile(r"\x1b\[([0-9;]*)([a-zA-Z])")

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
    def from_ansi_and_scan_zones(
        cls, view_str: str, width: int, height: int, zm: ZoneManager
    ) -> "ScreenBuffer":
        """
        Parses ANSI SGR into 2D Cells AND extracts \x1b[<num>z zone markers
        into exact (x1, y1, x2, y2) bounding boxes in a single O(N) pass!
        """
        buf = cls(width, height)
        lines = view_str.split("\n")
        active_sgr = ""

        # Track open zone start coordinates: zone_id -> (start_x, start_y)
        open_zones: Dict[str, Tuple[int, int]] = {}
        new_zones: Dict[str, ZoneInfo] = {}

        for y in range(min(height, len(lines))):
            line = lines[y]
            row = buf.cells[y]
            x = 0
            i = 0
            n = len(line)

            while i < n:
                if line[i] == "\x1b":
                    m = ANSI_TOKEN_RE.match(line, i)
                    if m:
                        params, cmd = m.group(1), m.group(2)
                        if cmd == "m":
                            # Standard SGR color/style sequence
                            if params in ("", "0"):
                                active_sgr = ""
                            else:
                                active_sgr = f"{active_sgr}\x1b[{params}m"
                        elif cmd == "z" and params.isdigit():
                            # Zero-width BubbleZone marker!
                            num = int(params)
                            if num % 2 == 0:
                                # Even = Start Marker
                                z_id = zm._marker_to_id.get(num)
                                if z_id is not None:
                                    open_zones[z_id] = (x, y)
                            else:
                                # Odd = End Marker (inclusive of previous cell x - 1)
                                z_id = zm._marker_to_id.get(num - 1)
                                if z_id is not None and z_id in open_zones:
                                    sx, sy = open_zones.pop(z_id)
                                    ex = max(sx, x - 1)
                                    new_zones[z_id] = ZoneInfo(z_id, sx, sy, ex, y)
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
                elif w == 2:
                    if x + 1 >= width:
                        row[x] = Cell(" ", active_sgr, 1)
                        x += 1
                        continue
                    row[x] = Cell(ch, active_sgr, 2)
                    row[x + 1] = CONT_CELL
                    x += 2
                else:
                    row[x] = Cell(ch, active_sgr, 1)
                    x += 1

        zm.zones = new_zones
        return buf


class CellDiffRenderer:
    def __init__(self, fps: int = 60):
        self.frame_interval = 1.0 / fps
        self.front_buffer: Optional[ScreenBuffer] = None

    def invalidate(self) -> None:
        self.front_buffer = None

    def render_frame(self, view_str: str, width: int, height: int, zm: ZoneManager) -> None:
        back = ScreenBuffer.from_ansi_and_scan_zones(view_str, width, height, zm)
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
# 5. Demo Application Using `zone.mark()` and `zone.in_bounds()`
# =====================================================================

TABS = ("Dashboard", "Deployments", "Settings")
TASKS = (
    "Migrate database replicas to multi-AZ",
    "Enable DEC Mode 2026 synchronized rendering",
    "Add BubbleZone zero-width hit-testing",
    "Ship Python TUI framework v1.0",
)


@dataclass(frozen=True)
class AppModel:
    width: int = 80
    height: int = 24
    active_tab: int = 0
    counter: int = 10
    checked: Tuple[bool, ...] = (True, True, True, False)
    hovered_zone: str = "None"
    last_clicked: str = "Click any tab, button, or checklist row!"
    progress_val: float = 0.65

    def update(self, msg: Msg) -> Tuple["AppModel", bool]:
        if isinstance(msg, WindowSizeMsg):
            return replace(self, width=msg.width, height=msg.height), False

        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c"):
                return self, True
            return self, False

        if isinstance(msg, MouseMsg):
            # 1. Detect Hover state across any registered zone automatically!
            hit_zones = zone.find_all_at(msg)
            hovered = hit_zones[-1] if hit_zones else "None"
            model = replace(self, hovered_zone=hovered)

            # 2. Handle Left Clicks using `zone.in_bounds(id, msg)` — ZERO X/Y MATH!
            if msg.button == "left" and msg.action == "press":
                # Check Tabs
                for idx, name in enumerate(TABS):
                    tab_id = f"tab_{idx}"
                    if zone.in_bounds(tab_id, msg):
                        return replace(
                            model,
                            active_tab=idx,
                            last_clicked=f"Switched to tab '{name}' ({tab_id})",
                        ), False

                # Check Counter Buttons
                if zone.in_bounds("btn_inc", msg):
                    return replace(
                        model,
                        counter=self.counter + 1,
                        last_clicked="Clicked [+ Increment] button",
                    ), False

                if zone.in_bounds("btn_dec", msg):
                    return replace(
                        model,
                        counter=self.counter - 1,
                        last_clicked="Clicked [- Decrement] button",
                    ), False

                if zone.in_bounds("btn_reset", msg):
                    return replace(
                        model,
                        counter=0,
                        last_clicked="Clicked [↺ Reset] button",
                    ), False

                # Check Interactive Progress Bar (using relative X inside the zone!)
                if zone.in_bounds("progress_bar", msg):
                    z_info = zone.get("progress_bar")
                    if z_info:
                        rel_x, _ = z_info.relative_pos(msg.x, msg.y)
                        bar_w = max(1, z_info.x2 - z_info.x1 + 1)
                        pct = min(1.0, max(0.0, rel_x / bar_w))
                        return replace(
                            model,
                            progress_val=pct,
                            last_clicked=f"Scrubbed progress bar to {int(pct * 100)}% (rel_x={rel_x})",
                        ), False

                # Check Task Checklist Rows
                for idx in range(len(TASKS)):
                    row_id = f"task_{idx}"
                    if zone.in_bounds(row_id, msg):
                        new_checked = list(self.checked)
                        new_checked[idx] = not new_checked[idx]
                        return replace(
                            model,
                            checked=tuple(new_checked),
                            last_clicked=f"Toggled task #{idx + 1} ({row_id})",
                        ), False

            return model, False

        return self, False

    def view(self) -> str:
        # 1. Build Clickable Navigation Tabs wrapped in `zone.mark()`
        tab_blocks = []
        for idx, name in enumerate(TABS):
            tab_id = f"tab_{idx}"
            is_active = idx == self.active_tab
            is_hover = self.hovered_zone == tab_id
            col = "#00CEC9" if is_active else ("#A29BFE" if is_hover else "#636E72")
            label = f" ● {name} " if is_active else f" ○ {name} "
            box = "\n".join([
                f"{fg_hex(col)}╭{'─' * (visual_width(label))}╮\x1b[0m",
                f"{fg_hex(col)}│\x1b[1m{label}\x1b[0m{fg_hex(col)}│\x1b[0m",
                f"{fg_hex(col)}┴{'─' * (visual_width(label))}┴\x1b[0m",
            ])
            # Wrap the entire 3-line tab in zone.mark()!
            tab_blocks.append(zone.mark(tab_id, box))

        tabs_row = join_horizontal(0.0, *tab_blocks, gap=1)

        # 2. Build Clickable 3-Line Buttons wrapped in `zone.mark()`
        btn_dec = zone.mark(
            "btn_dec",
            make_button("－ Decrement", "#D63031", hovered=(self.hovered_zone == "btn_dec")),
        )
        btn_inc = zone.mark(
            "btn_inc",
            make_button("＋ Increment", "#00B894", hovered=(self.hovered_zone == "btn_inc")),
        )
        btn_rst = zone.mark(
            "btn_reset",
            make_button("↺ Reset", "#6C5CE7", hovered=(self.hovered_zone == "btn_reset")),
        )

        counter_badge = "\n".join([
            f"{fg_hex('#DFE6E9')}╭──────────────╮\x1b[0m",
            f"{fg_hex('#DFE6E9')}│\x1b[0m  Count: \x1b[1;33m{self.counter:<4}\x1b[0m {fg_hex('#DFE6E9')}│\x1b[0m",
            f"{fg_hex('#DFE6E9')}╰──────────────╯\x1b[0m",
        ])

        controls_row = join_horizontal(0.5, counter_badge, btn_dec, btn_inc, btn_rst, gap=2)

        # 3. Build a Click-to-Scrub Progress Bar (demonstrates zone.relative_pos)
        bar_w = 40
        filled = int(round(self.progress_val * bar_w))
        bar_str = (
            f"{fg_hex('#00CEC9')}{'━' * filled}"
            f"{fg_hex('#2D3436')}{'─' * (bar_w - filled)}\x1b[0m"
        )
        marked_bar = zone.mark("progress_bar", bar_str)
        progress_section = (
            f"  \x1b[1mClick Bar to Scrub:\x1b[0m [{marked_bar}] "
            f"\x1b[1;36m{int(self.progress_val * 100):3d}%\x1b[0m"
        )

        # 4. Build Clickable Checklist Rows
        task_rows = []
        for idx, text in enumerate(TASKS):
            row_id = f"task_{idx}"
            done = self.checked[idx]
            hovered = self.hovered_zone == row_id
            check_icon = f"{fg_hex('#00B894')}✔\x1b[0m" if done else f"{fg_hex('#636E72')}☐\x1b[0m"
            style = "\x1b[1;36m" if hovered else ("\x1b[2m" if done else "\x1b[0m")
            row_str = f" {check_icon} {style}{text}\x1b[0m "
            task_rows.append("  " + zone.mark(row_id, row_str))

        # 5. Live Zone Inspector Telemetry Footer
        hovered_box = zone.get(self.hovered_zone)
        coords_str = (
            f"({hovered_box.x1}, {hovered_box.y1}) → ({hovered_box.x2}, {hovered_box.y2})"
            if hovered_box
            else "—"
        )

        return "\n".join([
            f"\x1b[1;35m  ⚡ PyBubbleZone — Zero-Math Declarative Mouse Hit-Testing\x1b[0m",
            "",
            "  " + tabs_row.replace("\n", "\n  "),
            "",
            f"  \x1b[1mActive View:\x1b[0m {fg_hex('#00CEC9')}{TABS[self.active_tab]}\x1b[0m",
            "  " + controls_row.replace("\n", "\n  "),
            "",
            progress_section,
            "",
            "  \x1b[1mInteractive Checklist (Click any item to toggle):\x1b[0m",
            *task_rows,
            "",
            f"  {fg_hex('#636E72')}────────────────────────────────────────────────────────────────────\x1b[0m",
            f"  \x1b[1mHovered Zone:\x1b[0m \x1b[1;33m{self.hovered_zone:<16}\x1b[0m \x1b[1mBounds:\x1b[0m {fg_hex('#A29BFE')}{coords_str}\x1b[0m",
            f"  \x1b[1mLast Action:\x1b[0m  \x1b[1;32m{self.last_clicked}\x1b[0m",
            f"  \x1b[2mHover & click anywhere above! Press 'q' or 'ctrl+c' to quit.\x1b[0m",
        ])


# =====================================================================
# 6. Runtime Loop
# =====================================================================

SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")

async def run_app():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Msg] = asyncio.Queue()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)

    def on_stdin():
        try:
            raw = os.read(fd, 4096)
        except BlockingIOError:
            return
        text = decoder.decode(raw, final=False)
        i = 0
        while i < len(text):
            if text[i] == "\x1b":
                m = SGR_MOUSE_RE.match(text, i)
                if m:
                    cb = int(m.group(1))
                    # Convert 1-indexed SGR coordinates to 0-indexed ScreenBuffer coordinates!
                    x = int(m.group(2)) - 1
                    y = int(m.group(3)) - 1
                    st = m.group(4)
                    if cb & 64:
                        btn = "wheel_up" if (cb & 3) == 0 else "wheel_down"
                        act = "scroll"
                    else:
                        btn = {0: "left", 1: "middle", 2: "right", 3: "none"}[cb & 3]
                        act = "release" if st == "m" else ("motion" if (cb & 32) else "press")
                    queue.put_nowait(MouseMsg(x, y, btn, act))
                    i = m.end()
                    continue
            ch = text[i]
            queue.put_nowait(KeyMsg("ctrl+c" if ord(ch) == 3 else ch))
            i += 1

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
