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
from typing import Any, Callable, Dict, List, Optional, Tuple
import unicodedata


# =====================================================================
# 1. Core Tea Messages & Zone Manager
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
# 2. Declarative Huh-Style Field Classes
# =====================================================================

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    error: Optional[str] = None
    validate: Optional[Callable[[Any], Optional[str]]] = None

    def validate_value(self, val: Any) -> Optional[str]:
        if self.validate:
            return self.validate(val)
        return None


@dataclass(frozen=True)
class InputField(Field):
    value: str = ""
    placeholder: str = "Type here..."
    cursor: int = 0

    def update_key(self, k: str) -> "InputField":
        val = self.value
        cur = self.cursor
        if k == "backspace" and cur > 0:
            new_val = val[:cur - 1] + val[cur:]
            return replace(self, value=new_val, cursor=cur - 1, error=None)
        if k == "left" and cur > 0:
            return replace(self, cursor=cur - 1)
        if k == "right" and cur < len(val):
            return replace(self, cursor=cur + 1)
        if len(k) == 1 and ord(k) >= 32:
            new_val = val[:cur] + k + val[cur:]
            return replace(self, value=new_val, cursor=cur + 1, error=None)
        return self

    def view(self, focused: bool, fid: str) -> str:
        box_col = "#00CEC9" if focused else "#636E72"
        val_str = self.value if self.value else f"\x1b[2m{self.placeholder}\x1b[0m"
        box = f" {val_str} "
        marked = zone.mark(fid, box)
        err_str = f"  {fg_hex('#D63031')}✖ {self.error}\x1b[0m" if self.error else ""
        return f"  \x1b[1m{self.label}:\x1b[0m\n  {fg_hex(box_col)}{marked}\x1b[0m{err_str}"


@dataclass(frozen=True)
class SelectField(Field):
    options: Tuple[str, ...] = ()
    selected_idx: int = 0

    def update_key(self, k: str) -> "SelectField":
        if k in ("up", "k") and self.selected_idx > 0:
            return replace(self, selected_idx=self.selected_idx - 1)
        if k in ("down", "j") and self.selected_idx < len(self.options) - 1:
            return replace(self, selected_idx=self.selected_idx + 1)
        return self

    def view(self, focused: bool, fid: str) -> str:
        lines = [f"  \x1b[1m{self.label}:\x1b[0m"]
        for idx, opt in enumerate(self.options):
            is_sel = idx == self.selected_idx
            icon = "◉" if is_sel else "◯"
            col = "#00CEC9" if is_sel else "#B2BEC3"
            opt_box = f" {icon} {opt} "
            marked = zone.mark(f"{fid}_opt_{idx}", opt_box)
            lines.append(f"    {fg_hex(col)}{marked}\x1b[0m")
        if self.error:
            lines.append(f"  {fg_hex('#D63031')}✖ {self.error}\x1b[0m")
        return "\n".join(lines)

    @property
    def value(self) -> str:
        if 0 <= self.selected_idx < len(self.options):
            return self.options[self.selected_idx]
        return ""


@dataclass(frozen=True)
class ConfirmField(Field):
    value: bool = True

    def update_key(self, k: str) -> "ConfirmField":
        if k in ("left", "right", "h", "l", " "):
            return replace(self, value=not self.value)
        return self

    def view(self, focused: bool, fid: str) -> str:
        yes_col = "#00B894" if self.value else "#636E72"
        no_col = "#D63031" if not self.value else "#636E72"
        yes_box = zone.mark(f"{fid}_yes", f" {('◉' if self.value else '◯')} Yes ")
        no_box = zone.mark(f"{fid}_no", f" {('◉' if not self.value else '◯')} No ")
        return (
            f"  \x1b[1m{self.label}:\x1b[0m\n"
            f"    {fg_hex(yes_col)}{yes_box}\x1b[0m    {fg_hex(no_col)}{no_box}\x1b[0m"
        )


@dataclass(frozen=True)
class Group:
    title: str
    fields: Tuple[Union[InputField, SelectField, ConfirmField], ...]


@dataclass(frozen=True)
class Form:
    groups: Tuple[Group, ...]
    active_group: int = 0
    active_field: int = 0
    submitted: bool = False

    @property
    def current_field(self) -> Union[InputField, SelectField, ConfirmField]:
        return self.groups[self.active_group].fields[self.active_field]

    def set_field(self, new_f: Union[InputField, SelectField, ConfirmField]) -> "Form":
        g_idx = self.active_group
        f_idx = self.active_field
        g = self.groups[g_idx]
        new_fields = list(g.fields)
        new_fields[f_idx] = new_f
        new_groups = list(self.groups)
        new_groups[g_idx] = replace(g, fields=tuple(new_fields))
        return replace(self, groups=tuple(new_groups))

    def advance(self) -> "Form":
        cur = self.current_field
        err = cur.validate_value(cur.value)
        if err:
            return self.set_field(replace(cur, error=err))

        g = self.groups[self.active_group]
        if self.active_field < len(g.fields) - 1:
            return replace(self, active_field=self.active_field + 1)
        elif self.active_group < len(self.groups) - 1:
            return replace(self, active_group=self.active_group + 1, active_field=0)
        else:
            return replace(self, submitted=True)

    def extract_values(self) -> Dict[str, Any]:
        data = {}
        for g in self.groups:
            for f in g.fields:
                data[f.key] = f.value
        return data


# =====================================================================
# 3. Interactive Form App Model
# =====================================================================

@dataclass(frozen=True)
class FormAppModel:
    width: int = 80
    height: int = 24
    form: Form = field(
        default_factory=lambda: Form(
            groups=(
                Group(
                    title="1. Cluster Configuration",
                    fields=(
                        InputField(
                            key="cluster_name",
                            label="Cluster Name",
                            placeholder="e.g. production-us-east",
                            validate=lambda s: "Min 3 chars required" if len(s.strip()) < 3 else None,
                        ),
                        SelectField(
                            key="region",
                            label="Cloud Region",
                            options=("us-east-1", "us-west-2", "eu-central-1", "ap-southeast-1"),
                        ),
                    ),
                ),
                Group(
                    title="2. Scaling & Review",
                    fields=(
                        SelectField(
                            key="instance_type",
                            label="Node Instance Tier",
                            options=("t4g.xlarge (4vCPU / 16GB)", "c7g.2xlarge (8vCPU / 16GB)", "m6g.4xlarge (16vCPU / 64GB)"),
                        ),
                        ConfirmField(
                            key="auto_backup",
                            label="Enable Automated Daily Snapshots?",
                            value=True,
                        ),
                    ),
                ),
            )
        )
    )

    def update(self, msg: Msg) -> Tuple["FormAppModel", bool]:
        if isinstance(msg, WindowSizeMsg):
            return replace(self, width=msg.width, height=msg.height), False

        if isinstance(msg, KeyMsg):
            if msg.key in ("q", "ctrl+c"):
                return self, True
            if self.form.submitted:
                if msg.key == "enter":
                    return replace(self, form=Form(groups=self.form.groups)), False
                return self, False

            form = self.form
            cur = form.current_field

            if msg.key == "tab" or msg.key == "enter":
                if isinstance(cur, InputField) and msg.key == "enter":
                    return replace(self, form=form.advance()), False
                elif isinstance(cur, SelectField) and msg.key == "enter":
                    return replace(self, form=form.advance()), False
                elif isinstance(cur, ConfirmField):
                    return replace(self, form=form.advance()), False
                else:
                    # Tab cycles active field
                    g = form.groups[form.active_group]
                    next_f = (form.active_field + 1) % len(g.fields)
                    return replace(self, form=replace(form, active_field=next_f)), False

            if isinstance(cur, InputField):
                return replace(self, form=form.set_field(cur.update_key(msg.key))), False
            elif isinstance(cur, SelectField):
                return replace(self, form=form.set_field(cur.update_key(msg.key))), False
            elif isinstance(cur, ConfirmField):
                return replace(self, form=form.set_field(cur.update_key(msg.key))), False

        if isinstance(msg, MouseMsg) and msg.button == "left" and msg.action == "press":
            if self.form.submitted:
                if zone.in_bounds("btn_restart", msg):
                    return replace(self, form=Form(groups=self.form.groups)), False
                return self, False

            # Check all fields in all groups for direct mouse selection
            for g_idx, g in enumerate(self.form.groups):
                for f_idx, f in enumerate(g.fields):
                    fid = f"field_{g_idx}_{f_idx}"
                    if isinstance(f, SelectField):
                        for o_idx in range(len(f.options)):
                            if zone.in_bounds(f"{fid}_opt_{o_idx}", msg):
                                updated = replace(f, selected_idx=o_idx)
                                return replace(self, form=replace(self.form, active_group=g_idx, active_field=f_idx).set_field(updated)), False
                    elif isinstance(f, ConfirmField):
                        if zone.in_bounds(f"{fid}_yes", msg):
                            return replace(self, form=replace(self.form, active_group=g_idx, active_field=f_idx).set_field(replace(f, value=True))), False
                        if zone.in_bounds(f"{fid}_no", msg):
                            return replace(self, form=replace(self.form, active_group=g_idx, active_field=f_idx).set_field(replace(f, value=False))), False
                    elif isinstance(f, InputField):
                        if zone.in_bounds(fid, msg):
                            return replace(self, form=replace(self.form, active_group=g_idx, active_field=f_idx)), False

            if zone.in_bounds("btn_submit", msg):
                return replace(self, form=self.form.advance()), False

        return self, False

    def view(self) -> str:
        w = max(60, min(self.width, 92))
        inner_w = w - 4
        rows = [f"\x1b[1;35m  🚀 Declarative Form Builder (Huh-Style)\x1b[0m", ""]

        if self.form.submitted:
            data = self.form.extract_values()
            rows.append(f"  {fg_hex('#00B894')}\x1b[1m✔ Form Successfully Submitted!\x1b[0m")
            rows.append("")
            for k, v in data.items():
                rows.append(f"    • \x1b[1m{k}:\x1b[0m {fg_hex('#00CEC9')}{v}\x1b[0m")
            rows.append("")
            restart_btn = zone.mark("btn_restart", fg_hex("#1E272E") + bg_hex("#00CEC9") + "  ↺ Reset Form  " + "\x1b[0m")
            rows.append(f"  {restart_btn}")
            return "\n".join(rows)

        # Render Active Group & Fields
        g_idx = self.form.active_group
        g = self.form.groups[g_idx]
        rows.append(f"  {fg_hex('#A29BFE')}\x1b[1m{g.title}\x1b[0m")
        rows.append(f"  {fg_hex('#636E72')}{'─' * inner_w}\x1b[0m")

        for f_idx, f in enumerate(g.fields):
            is_focused = f_idx == self.form.active_field
            fid = f"field_{g_idx}_{f_idx}"
            rows.append(f.view(is_focused, fid))
            rows.append("")

        submit_btn = zone.mark("btn_submit", fg_hex("#1E272E") + bg_hex("#00B894") + "  ✔ Submit Configuration  " + "\x1b[0m")
        rows.append(f"  {submit_btn}")
        rows.append("")
        rows.append(f"  \x1b[2mTab / Click: Focus Field • Enter: Next/Submit • ↑/↓: Select Options • q: Quit\x1b[0m")

        return "\n".join(rows)


# =====================================================================
# 4. Cell-Diffing Renderer & Runtime Loop (Same as previous engine)
# =====================================================================

ANSI_TOKEN_RE = re.compile(r"\x1b\[([0-9;]*)([a-zA-Z])")
SGR_MOUSE_RE = re.compile(r"^\x1b\[\x3c(\d+);(\d+);(\d+)([Mm])")
CSI_RE = re.compile(r"^\x1b\[([\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e])")
CSI_KEYS = {"A": "up", "B": "down", "C": "right", "D": "left", "5~": "pgup", "6~": "pgdn"}

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
    def from_ansi_and_scan_zones(cls, view_str: str, width: int, height: int, zm: ZoneManager) -> "ScreenBuffer":
        buf = cls(width, height)
        lines = view_str.split("\n")
        active_sgr = ""
        open_zones: Dict[str, Tuple[int, int]] = {}
        new_zones: Dict[str, ZoneInfo] = {}

        for y in range(min(height, len(lines))):
            line = lines[y]
            row = buf.cells[y]
            x, i, n = 0, 0, len(line)
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
                    m_match = SGR_MOUSE_RE.match(buf)
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
                    m_csi = CSI_RE.match(buf)
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
    model = FormAppModel()
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
