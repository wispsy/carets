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
import unicodedata
from typing import Callable, List, Optional, Tuple


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
    x: int
    y: int
    button: str
    action: str

@dataclass(frozen=True)
class WindowSizeMsg(Msg):
    width: int
    height: int

@dataclass(frozen=True)
class TickMsg(Msg):
    timestamp: float


# =====================================================================
# 2. 2D Cell Buffer & ANSI-to-Cell Parser
# =====================================================================

ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

def char_width(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Cc", "Cf", "Mn", "Me"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1

@dataclass(frozen=True, slots=True)
class Cell:
    char: str = " "
    sgr: str = ""     # Active cumulative ANSI SGR sequence for this cell
    width: int = 1    # 1 = normal, 2 = wide char lead cell, 0 = wide char trailing cell

EMPTY_CELL = Cell(" ", "", 1)
CONTINUATION_CELL = Cell("", "", 0)


class ScreenBuffer:
    """Represents a 2D grid of terminal cells (width x height)."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells: List[List[Cell]] = [
            [EMPTY_CELL for _ in range(width)] for _ in range(height)
        ]

    @classmethod
    def from_ansi_string(cls, view_str: str, width: int, height: int) -> "ScreenBuffer":
        """Parses a multiline ANSI string from model.view() into a 2D grid of Cells."""
        buf = cls(width, height)
        lines = view_str.split("\n")
        active_sgr = ""

        for y in range(min(height, len(lines))):
            line = lines[y]
            row = buf.cells[y]
            x = 0
            i = 0
            n = len(line)

            while i < n and x < width:
                # Check for ANSI SGR escape code (\x1b[...m)
                if line[i] == "\x1b":
                    m = ANSI_SGR_RE.match(line, i)
                    if m:
                        params = m.group(1)
                        if params in ("", "0"):
                            active_sgr = ""
                        else:
                            # Accumulate active SGR state so each Cell is self-contained
                            active_sgr = f"{active_sgr}\x1b[{params}m"
                        i = m.end()
                        continue
                    # Skip non-SGR CSI sequences if any exist
                    i += 1
                    continue

                ch = line[i]
                i += 1
                w = char_width(ch)

                if w == 0:
                    continue
                elif w == 2:
                    # If wide char doesn't fit in the last column, pad with space
                    if x + 1 >= width:
                        row[x] = Cell(" ", active_sgr, 1)
                        x += 1
                        break
                    row[x] = Cell(ch, active_sgr, 2)
                    row[x + 1] = CONTINUATION_CELL
                    x += 2
                else:
                    row[x] = Cell(ch, active_sgr, 1)
                    x += 1

        return buf


# =====================================================================
# 3. 60 FPS Cell-Diffing Renderer with Synchronized Output (?2026h)
# =====================================================================

class CellDiffRenderer:
    """
    Compares the previous ScreenBuffer against the new ScreenBuffer and emits
    the minimal ANSI cursor moves and SGR state changes wrapped in Mode 2026.
    """

    def __init__(self, fps: int = 60):
        self.frame_interval = 1.0 / fps
        self.front_buffer: Optional[ScreenBuffer] = None
        self.last_bytes_written: int = 0
        self.last_cells_changed: int = 0
        self.total_frames: int = 0

    def invalidate(self) -> None:
        """Forces a full screen redraw on the next frame (e.g. after terminal resize)."""
        self.front_buffer = None

    def render_frame(self, view_str: str, width: int, height: int) -> None:
        back_buffer = ScreenBuffer.from_ansi_string(view_str, width, height)
        front = self.front_buffer

        # Resize or first frame -> full clear
        full_redraw = (
            front is None
            or front.width != width
            or front.height != height
        )

        out: List[str] = []
        # Begin Synchronized Update (DEC Mode 2026) - eliminates mid-frame tearing
        out.append("\x1b[?2026h")

        if full_redraw:
            out.append("\x1b[0m\x1b[2J")

        cur_row = -1
        cur_col = -1
        cur_sgr: Optional[str] = None
        cells_changed = 0

        for y in range(height):
            back_row = back_buffer.cells[y]
            front_row = front.cells[y] if not full_redraw else None
            x = 0

            while x < width:
                cell = back_row[x]

                # Trailing half of a 2-cell wide character is already drawn by x-1
                if cell.width == 0:
                    x += 1
                    continue

                # Check if this cell (or an overlapping wide character) changed
                changed = full_redraw or (cell != front_row[x])
                if not changed and cell.width == 2 and x + 1 < width:
                    changed = back_row[x + 1] != front_row[x + 1]

                # Edge case: If we overwrite the right half of an old wide char with a 1-cell char,
                # and the left half was somehow not marked changed, we must still redraw.
                if not changed and front_row is not None and front_row[x].width == 0:
                    changed = True

                if changed:
                    cells_changed += 1
                    # 1. Move hardware cursor only if it isn't already at (y, x)
                    if cur_row != y or cur_col != x:
                        # ANSI cup is 1-indexed: \x1b[{row};{col}H
                        out.append(f"\x1b[{y + 1};{x + 1}H")
                        cur_row = y
                        cur_col = x

                    # 2. Update SGR style only if it differs from currently active SGR
                    if cell.sgr != cur_sgr:
                        out.append(f"\x1b[0m{cell.sgr}")
                        cur_sgr = cell.sgr

                    # 3. Emit the character and advance our tracked cursor position
                    out.append(cell.char)
                    cur_col += cell.width

                    # If we overwrote the first cell of an old 2-width char with a 1-width char,
                    # force the next column (x + 1) to redraw so no ghost half-char remains
                    if (
                        not full_redraw
                        and front_row is not None
                        and front_row[x].width == 2
                        and cell.width == 1
                        and x + 1 < width
                    ):
                        front_row[x + 1] = Cell("__INVALID__", "", 1)

                x += cell.width

        # Reset SGR at end of frame and close Synchronized Update
        if cur_sgr:
            out.append("\x1b[0m")
        out.append("\x1b[?2026l")

        # Only flush to stdout if at least one cell actually changed!
        if cells_changed > 0 or full_redraw:
            payload = "".join(out)
            sys.stdout.write(payload)
            sys.stdout.flush()
            self.last_bytes_written = len(payload.encode("utf-8"))
            self.last_cells_changed = cells_changed
            self.total_frames += 1
        else:
            self.last_bytes_written = 0
            self.last_cells_changed = 0

        self.front_buffer = back_buffer


# =====================================================================
# 4. Interactive Particle Canvas & Telemetry Demo Model
# =====================================================================

@dataclass(frozen=True)
class DemoModel:
    width: int = 80
    height: int = 24
    mouse_x: int = 20
    mouse_y: int = 10
    trail: Tuple[Tuple[int, int], ...] = field(default_factory=tuple)
    msgs_received: int = 0
    tick_count: int = 0
    use_emojis: bool = True

    def update(self, msg: Msg) -> Tuple["DemoModel", bool]:
        if isinstance(msg, WindowSizeMsg):
            return replace(
                self, width=msg.width, height=msg.height, msgs_received=self.msgs_received + 1
            ), False

        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c"):
                return self, True
            if msg.key == "e":
                return replace(
                    self, use_emojis=not self.use_emojis, msgs_received=self.msgs_received + 1
                ), False
            if msg.key == "c":
                return replace(self, trail=(), msgs_received=self.msgs_received + 1), False
            return replace(self, msgs_received=self.msgs_received + 1), False

        if isinstance(msg, MouseMsg):
            new_trail = (self.trail + ((msg.x, msg.y),))[-18:]
            return replace(
                self,
                mouse_x=msg.x,
                mouse_y=msg.y,
                trail=new_trail,
                msgs_received=self.msgs_received + 1,
            ), False

        if isinstance(msg, TickMsg):
            return replace(
                self, tick_count=self.tick_count + 1, msgs_received=self.msgs_received + 1
            ), False

        return self, False

    def view(self, renderer: CellDiffRenderer) -> str:
        w = max(50, min(self.width, 100))
        h = max(16, min(self.height, 30))
        inner_w = w - 2

        # Build an interactive 2D canvas showing mouse trails + animated spinner
        canvas_h = h - 7
        grid = [[" " for _ in range(inner_w)] for _ in range(canvas_h)]

        # Draw fading mouse trail on canvas
        shades = ["\x1b[38;5;238m·\x1b[0m", "\x1b[38;5;244m•\x1b[0m", "\x1b[38;5;45m●\x1b[0m"]
        for idx, (tx, ty) in enumerate(self.trail):
            cx = tx - 2
            cy = ty - 6
            if 0 <= cy < canvas_h and 0 <= cx < inner_w - 1:
                shade = shades[min(len(shades) - 1, idx * len(shades) // max(1, len(self.trail)))]
                grid[cy][cx] = shade

        # Draw current cursor head (either 2-cell wide 🚀 emoji or 1-cell ★)
        cur_cx = self.mouse_x - 2
        cur_cy = self.mouse_y - 6
        if 0 <= cur_cy < canvas_h and 0 <= cur_cx < inner_w - 2:
            if self.use_emojis:
                grid[cur_cy][cur_cx] = "\x1b[1;33m🚀\x1b[0m"
                grid[cur_cy][cur_cx + 1] = ""  # Account for 2-cell width in raw string builder
            else:
                grid[cur_cy][cur_cx] = "\x1b[1;33m★\x1b[0m"

        spinner_frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        spin = spinner_frames[self.tick_count % len(spinner_frames)]

        full_frame_bytes = w * h * 8  # Approximate bytes a naive full-screen redraw would flush
        saved_pct = 100.0 * (1.0 - (renderer.last_bytes_written / max(1, full_frame_bytes)))

        rows = [
            f"\x1b[1;36m╭{'─' * inner_w}╮\x1b[0m",
            (
                f"\x1b[1;36m│\x1b[0m \x1b[1;35m{spin} 60 FPS Cell-Diffing Engine\x1b[0m • "
                f"Msgs: \x1b[1;32m{self.msgs_received:<6}\x1b[0m "
                f"Frames: \x1b[1;33m{renderer.total_frames:<6}\x1b[0m"
            ),
            (
                f"\x1b[1;36m│\x1b[0m Changed Cells: \x1b[1;36m{renderer.last_cells_changed:<4}\x1b[0m • "
                f"Flushed: \x1b[1;32m{renderer.last_bytes_written:<5} B\x1b[0m "
                f"(Saved \x1b[1;35m{saved_pct:4.1f}%\x1b[0m I/O)"
            ),
            f"\x1b[1;36m├{'─' * inner_w}┤\x1b[0m",
        ]

        for r in grid:
            rows.append(f"\x1b[1;36m│\x1b[0m{''.join(r)}\x1b[1;36m│\x1b[0m")

        rows.append(f"\x1b[1;36m╰{'─' * inner_w}╯\x1b[0m")
        mode_label = "Wide Emoji 🚀 (2-cell)" if self.use_emojis else "ASCII ★ (1-cell)"
        rows.append(
            f"\x1b[2mSwirl mouse inside box! • 'e': Toggle Cursor [{mode_label}] • 'c': Clear • 'q': Quit\x1b[0m"
        )
        return "\n".join(rows)


# =====================================================================
# 5. 60 FPS Event-Coalescing Runtime Loop
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
                    cb, x, y, st = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                    act = "release" if st == "m" else ("motion" if (cb & 32) else "press")
                    queue.put_nowait(MouseMsg(x, y, "mouse", act))
                    i = m.end()
                    continue
            ch = text[i]
            if ord(ch) == 3:
                queue.put_nowait(KeyMsg("ctrl+c"))
            else:
                queue.put_nowait(KeyMsg(ch))
            i += 1

    def on_resize():
        try:
            sz = os.get_terminal_size(fd)
            queue.put_nowait(WindowSizeMsg(sz.columns, sz.lines))
        except OSError:
            pass

    async def background_spinner_ticks():
        """Fires a background animation tick 12 times per second."""
        while True:
            await asyncio.sleep(1.0 / 12.0)
            queue.put_nowait(TickMsg(time.monotonic()))

    renderer = CellDiffRenderer(fps=60)
    model = DemoModel()
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

        tick_task = asyncio.create_task(background_spinner_ticks())

        # --- Core 60 FPS Coalescing Render Loop ---
        while not should_quit:
            frame_start = time.monotonic()

            # 1. Wait for at least one event if screen isn't dirty
            if not dirty:
                msg = await queue.get()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, should_quit = model.update(msg)
                dirty = True

            # 2. Drain ALL pending events currently in the queue without rendering!
            #    If 50 mouse-move events arrived in the last 16ms, we process all 50
            #    in microseconds and only call model.view() ONCE below.
            while not queue.empty() and not should_quit:
                msg = queue.get_nowait()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, should_quit = model.update(msg)
                dirty = True

            if should_quit:
                break

            # 3. Render & Diff at most once per 16.6ms (60 FPS cap)
            if dirty:
                view_str = model.view(renderer)
                renderer.render_frame(view_str, model.width, model.height)
                dirty = False

            # 4. Sleep for the remainder of the 16.6ms frame budget
            elapsed = time.monotonic() - frame_start
            remaining = renderer.frame_interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)

        tick_task.cancel()

    finally:
        loop.remove_reader(fd)
        loop.remove_signal_handler(signal.SIGWINCH)
        sys.stdout.write("\x1b[?2026l\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)


if __name__ == "__main__":
    asyncio.run(run_app())
