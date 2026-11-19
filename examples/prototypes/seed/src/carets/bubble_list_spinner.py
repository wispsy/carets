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
from typing import Callable, Coroutine, Dict, List, Optional, Tuple
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

@dataclass(frozen=True)
class BatchMsg(Msg):
    cmds: Tuple[Callable[[], Coroutine[None, None, Optional[Msg]]], ...]

Cmd = Callable[[], Coroutine[None, None, Optional[Msg]]]

def batch(*cmds: Optional[Cmd]) -> Optional[Cmd]:
    valid = tuple(c for c in cmds if c is not None)
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    async def _run() -> Msg:
        return BatchMsg(cmds=valid)
    return _run


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
# 3. Bubble #1: Self-Ticking `Spinner` Component (bubbles/spinner)
# =====================================================================

@dataclass(frozen=True)
class SpinnerStyle:
    frames: Tuple[str, ...]
    fps: float

DOT_SPINNER    = SpinnerStyle(("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"), fps=12.0)
LINE_SPINNER   = SpinnerStyle(("|", "/", "-", "\\"), fps=10.0)
PULSE_SPINNER  = SpinnerStyle(("█", "▓", "▒", "░", "▒", "▓"), fps=10.0)
POINTS_SPINNER = SpinnerStyle(("∙∙∙", "●∙∙", "∙●∙", "∙∙●", "∙∙∙"), fps=7.0)
METER_SPINNER  = SpinnerStyle(("▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▰▰▱", "▰▱▱"), fps=8.0)

SPINNER_PRESETS = (
    ("Braille Dots", DOT_SPINNER),
    ("Meter Bar", METER_SPINNER),
    ("Pulse Block", PULSE_SPINNER),
    ("Three Points", POINTS_SPINNER),
)

@dataclass(frozen=True)
class SpinnerTickMsg(Msg):
    spinner_id: int
    tag: int

@dataclass(frozen=True)
class Spinner:
    spinner_id: int = 1
    style: SpinnerStyle = DOT_SPINNER
    color: str = "#00CEC9"
    frame: int = 0
    tag: int = 0

    def tick(self) -> Cmd:
        """Schedules the next animation frame via an async tea.Cmd."""
        sid = self.spinner_id
        current_tag = self.tag
        delay = 1.0 / self.style.fps

        async def _tick_cmd() -> Msg:
            await asyncio.sleep(delay)
            return SpinnerTickMsg(spinner_id=sid, tag=current_tag)

        return _tick_cmd

    def update(self, msg: Msg) -> Tuple["Spinner", Optional[Cmd]]:
        if isinstance(msg, SpinnerTickMsg):
            # Ignore ticks meant for other spinners or stale duplicate chains
            if msg.spinner_id != self.spinner_id or msg.tag != self.tag:
                return self, None
            next_frame = (self.frame + 1) % len(self.style.frames)
            next_spinner = replace(self, frame=next_frame, tag=self.tag + 1)
            return next_spinner, next_spinner.tick()
        return self, None

    def view(self) -> str:
        glyph = self.style.frames[self.frame % len(self.style.frames)]
        return f"{fg_hex(self.color)}\x1b[1m{glyph}\x1b[0m"


# =====================================================================
# 4. Fuzzy Matcher with Character-Position Highlighting
# =====================================================================

def fuzzy_match(query: str, target: str) -> Optional[Tuple[int, Tuple[int, ...]]]:
    """
    Matches `query` subsequence against `target`.
    Returns (score, matched_indices) or None if no match.
    Rewards consecutive character streaks and word-start boundaries.
    """
    if not query:
        return (0, ())
    q_low = query.lower()
    t_low = target.lower()
    q_len = len(q_low)
    t_len = len(t_low)

    q_idx = 0
    score = 0
    consecutive = 0
    indices: List[int] = []

    for t_idx in range(t_len):
        if q_idx < q_len and t_low[t_idx] == q_low[q_idx]:
            indices.append(t_idx)
            # Base match score
            score += 10
            # Bonus for consecutive characters
            if consecutive > 0:
                score += 15 * consecutive
            # Bonus for matching at start of string or after separator (-, _, /, space)
            if t_idx == 0 or target[t_idx - 1] in (" ", "-", "_", "/", ":"):
                score += 20
            consecutive += 1
            q_idx += 1
        else:
            consecutive = 0

    if q_idx < q_len:
        return None

    # Slight penalty for longer strings so tighter matches rank higher
    score -= (t_len - q_len)
    return (score, tuple(indices))


def highlight_matches(
    text: str,
    matched_indices: Tuple[int, ...],
    base_sgr: str,
    match_sgr: str,
) -> str:
    """Renders `text` with characters at `matched_indices` highlighted in `match_sgr`."""
    if not matched_indices:
        return f"{base_sgr}{text}\x1b[0m"
    match_set = set(matched_indices)
    out: List[str] = []
    for idx, ch in enumerate(text):
        if idx in match_set:
            out.append(f"{match_sgr}{ch}\x1b[0m")
        else:
            out.append(f"{base_sgr}{ch}\x1b[0m")
    return "".join(out)


# =====================================================================
# 5. Bubble #2: Filterable `ListModel` Component (bubbles/list)
# =====================================================================

@dataclass(frozen=True)
class ListItem:
    id: str
    title: str
    description: str
    badge: str = ""

@dataclass(frozen=True)
class FilteredItem:
    item: ListItem
    score: int = 0
    matched_indices: Tuple[int, ...] = ()

UNFILTERED = "UNFILTERED"
FILTERING = "FILTERING"
FILTER_APPLIED = "FILTER_APPLIED"


@dataclass(frozen=True)
class ListModel:
    title: str = "Services"
    items: Tuple[ListItem, ...] = ()
    cursor: int = 0
    per_page: int = 5
    filter_state: str = UNFILTERED
    filter_query: str = ""

    @property
    def visible_items(self) -> Tuple[FilteredItem, ...]:
        if not self.filter_query:
            return tuple(FilteredItem(item=it) for it in self.items)
        ranked: List[FilteredItem] = []
        for it in self.items:
            # Match against title first, or fallback to description
            res = fuzzy_match(self.filter_query, it.title)
            if res is not None:
                score, idxs = res
                ranked.append(FilteredItem(item=it, score=score + 50, matched_indices=idxs))
            else:
                desc_res = fuzzy_match(self.filter_query, it.description)
                if desc_res is not None:
                    score, _ = desc_res
                    ranked.append(FilteredItem(item=it, score=score, matched_indices=()))
        ranked.sort(key=lambda x: x.score, reverse=True)
        return tuple(ranked)

    @property
    def selected_item(self) -> Optional[ListItem]:
        vis = self.visible_items
        if 0 <= self.cursor < len(vis):
            return vis[self.cursor].item
        return None

    @property
    def total_pages(self) -> int:
        vis_count = len(self.visible_items)
        return max(1, (vis_count + self.per_page - 1) // self.per_page)

    @property
    def current_page(self) -> int:
        return self.cursor // max(1, self.per_page)

    def _clamp_cursor(self, new_cursor: int) -> "ListModel":
        vis_len = len(self.visible_items)
        if vis_len == 0:
            return replace(self, cursor=0)
        return replace(self, cursor=max(0, min(vis_len - 1, new_cursor)))

    def update(self, msg: Msg) -> Tuple["ListModel", Optional[Cmd]]:
        vis = self.visible_items

        # 1. Mouse Support (Wheel Scroll + Click on Item or Page Dot)
        if isinstance(msg, MouseMsg):
            if msg.action == "scroll":
                delta = -1 if msg.button == "wheel_up" else 1
                return self._clamp_cursor(self.cursor + delta), None

            if msg.button == "left" and msg.action == "press":
                # Check if user clicked a visible list item
                page_start = self.current_page * self.per_page
                page_slice = vis[page_start:page_start + self.per_page]
                for idx in range(len(page_slice)):
                    abs_idx = page_start + idx
                    if zone.in_bounds(f"list_item_{abs_idx}", msg):
                        return replace(self, cursor=abs_idx), None

                # Check if user clicked a pagination dot
                for p in range(self.total_pages):
                    if zone.in_bounds(f"page_dot_{p}", msg):
                        return self._clamp_cursor(p * self.per_page), None

        # 2. Keyboard Handling in FILTERING mode (Typing search query)
        if isinstance(msg, KeyMsg) and self.filter_state == FILTERING:
            k = msg.key
            if k == "esc":
                # Cancel filter completely
                return replace(self, filter_state=UNFILTERED, filter_query="", cursor=0), None
            if k == "enter":
                # Lock in the current filter if non-empty
                new_state = FILTER_APPLIED if self.filter_query else UNFILTERED
                return replace(self, filter_state=new_state), None
            if k == "up" or k == "ctrl+p":
                return self._clamp_cursor(self.cursor - 1), None
            if k == "down" or k == "ctrl+n":
                return self._clamp_cursor(self.cursor + 1), None
            if k == "backspace":
                new_q = self.filter_query[:-1]
                return replace(self, filter_query=new_q, cursor=0), None
            if k == "ctrl+u":
                return replace(self, filter_query="", cursor=0), None
            if len(k) == 1 and ord(k) >= 32:
                new_q = self.filter_query + k
                return replace(self, filter_query=new_q, cursor=0), None
            return self, None

        # 3. Keyboard Handling in Navigation Mode (UNFILTERED or FILTER_APPLIED)
        if isinstance(msg, KeyMsg):
            k = msg.key
            if k == "/":
                return replace(self, filter_state=FILTERING), None
            if k == "esc" and self.filter_state == FILTER_APPLIED:
                return replace(self, filter_state=UNFILTERED, filter_query="", cursor=0), None
            if k in ("up", "k"):
                return self._clamp_cursor(self.cursor - 1), None
            if k in ("down", "j"):
                return self._clamp_cursor(self.cursor + 1), None
            if k in ("left", "h", "pgup"):
                return self._clamp_cursor(self.cursor - self.per_page), None
            if k in ("right", "l", "pgdn"):
                return self._clamp_cursor(self.cursor + self.per_page), None
            if k in ("home", "g"):
                return self._clamp_cursor(0), None
            if k in ("end", "G"):
                return self._clamp_cursor(len(vis) - 1), None

        return self, None

    def view(self, width: int = 72) -> str:
        vis = self.visible_items
        rows: List[str] = []

        # --- Header / Filter Bar ---
        title_pill = f"{bg_hex('#6C5CE7')}{fg_hex('#FFFFFF')}\x1b[1m  {self.title}  \x1b[0m"
        count_str = f"\x1b[2m{len(vis)}/{len(self.items)} items\x1b[0m"

        if self.filter_state == FILTERING:
            cursor_block = f"{bg_hex('#00CEC9')}{fg_hex('#1E272E')} \x1b[0m"
            filter_bar = (
                f"{fg_hex('#00CEC9')}\x1b[1m🔍 Filter:\x1b[0m "
                f"{fg_hex('#FFFFFF')}{self.filter_query}{cursor_block}"
                f"  \x1b[2m(Enter: lock • Esc: clear)\x1b[0m"
            )
            rows.append(f"  {title_pill}  {filter_bar}")
        elif self.filter_state == FILTER_APPLIED:
            filter_badge = (
                f"{bg_hex('#00CEC9')}{fg_hex('#1E272E')}\x1b[1m 🔍 \"{self.filter_query}\" \x1b[0m "
                f"\x1b[2m(Press '/' to edit or 'Esc' to clear)\x1b[0m"
            )
            rows.append(f"  {title_pill}  {count_str}  {filter_badge}")
        else:
            rows.append(f"  {title_pill}  {count_str}  \x1b[2m(Press '/' to fuzzy filter)\x1b[0m")

        rows.append("")

        # --- Visible Page Slice ---
        if not vis:
            rows.append(f"    \x1b[2mNo items match \"{self.filter_query}\". Press Esc to reset.\x1b[0m")
            for _ in range(self.per_page * 3 - 1):
                rows.append("")
        else:
            page_start = self.current_page * self.per_page
            page_items = vis[page_start:page_start + self.per_page]

            for i, f_item in enumerate(page_items):
                abs_idx = page_start + i
                it = f_item.item
                is_sel = abs_idx == self.cursor

                # Style active vs inactive item with left gutter bar (just like bubbles/list!)
                if is_sel:
                    gutter = f"{fg_hex('#00CEC9')}┃\x1b[0m"
                    base_title_sgr = f"{fg_hex('#00CEC9')}\x1b[1m"
                    match_title_sgr = f"{fg_hex('#FFEAA7')}\x1b[1;4m"
                    desc_sgr = fg_hex("#DFE6E9")
                else:
                    gutter = " "
                    base_title_sgr = fg_hex("#DFE6E9")
                    match_title_sgr = f"{fg_hex('#00CEC9')}\x1b[1;4m"
                    desc_sgr = "\x1b[2m"

                rendered_title = highlight_matches(
                    it.title, f_item.matched_indices, base_title_sgr, match_title_sgr
                )
                badge_str = f"  {fg_hex('#A29BFE')}[{it.badge}]\x1b[0m" if it.badge else ""
                item_block = (
                    f"  {gutter} {rendered_title}{badge_str}\n"
                    f"  {gutter} {desc_sgr}{it.description}\x1b[0m"
                )
                # Wrap each list item in BubbleZone for direct click selection!
                rows.append(zone.mark(f"list_item_{abs_idx}", item_block))
                rows.append("")

            # Pad remaining empty slots on last page so layout height never jumps
            missing_slots = self.per_page - len(page_items)
            for _ in range(missing_slots * 3):
                rows.append("")

        # --- Clickable Pagination Dots ---
        dots: List[str] = []
        for p in range(self.total_pages):
            dot_glyph = (
                f"{fg_hex('#00CEC9')}●\x1b[0m"
                if p == self.current_page
                else f"{fg_hex('#636E72')}•\x1b[0m"
            )
            dots.append(zone.mark(f"page_dot_{p}", f" {dot_glyph} "))
        rows.append("   " + "".join(dots))

        return "\n".join(rows)


# =====================================================================
# 6. Root Application Composing `ListModel` + Async `Spinner` Tasks
# =====================================================================

CATALOG_ITEMS = (
    ListItem("api-gw", "api-gateway-envoy", "Edge reverse proxy & TLS termination cluster", "us-east-1"),
    ListItem("auth-svc", "identity-oauth-provider", "Zero-trust JWT & OIDC authentication service", "global"),
    ListItem("pg-primary", "postgres-ha-cluster", "Primary transactional database with read replicas", "us-east-1"),
    ListItem("redis-cache", "valkey-session-store", "In-memory sub-millisecond cache & pub/sub broker", "us-west-2"),
    ListItem("kafka-bus", "redpanda-event-stream", "High-throughput event streaming backbone", "eu-central-1"),
    ListItem("worker-ai", "gpu-inference-workers", "vLLM tensor-parallel model serving fleet", "us-west-2"),
    ListItem("otel-col", "opentelemetry-collector", "Distributed tracing, metrics & log ingestion pipeline", "global"),
    ListItem("cdn-edge", "cloudflare-worker-router", "Anycast edge caching and WAF rules engine", "global"),
    ListItem("search-idx", "meilisearch-indexer", "Typo-tolerant instant search indexing service", "eu-central-1"),
    ListItem("cron-sched", "temporal-workflow-engine", "Durable distributed async task orchestrator", "us-east-1"),
    ListItem("vault-sec", "hashicorp-vault-kms", "Dynamic secrets management & encryption-as-a-service", "global"),
    ListItem("prom-tsdb", "victoria-metrics-tsdb", "Long-term time-series monitoring storage", "us-east-1"),
)

@dataclass(frozen=True)
class DeployFinishedMsg(Msg):
    service_title: str
    elapsed_sec: float


@dataclass(frozen=True)
class AppModel:
    width: int = 84
    height: int = 26
    list_model: ListModel = field(
        default_factory=lambda: ListModel(
            title="☁️  Production Microservices",
            items=CATALOG_ITEMS,
            per_page=4,
        )
    )
    spinner_preset_idx: int = 0
    spinner: Spinner = field(default_factory=lambda: Spinner(spinner_id=1, style=DOT_SPINNER))
    deploying_service: Optional[str] = None
    last_status: str = "Select a service and press Enter to trigger an async rollout."

    def init(self) -> Optional[Cmd]:
        # Start the spinner tick chain on boot
        return self.spinner.tick()

    def _trigger_deploy(self, item: ListItem) -> Tuple["AppModel", Optional[Cmd]]:
        """Starts an async simulated deployment Cmd alongside the animated Spinner."""
        title = item.title

        async def _deploy_task() -> Msg:
            t0 = time.monotonic()
            await asyncio.sleep(2.4)
            return DeployFinishedMsg(service_title=title, elapsed_sec=time.monotonic() - t0)

        return (
            replace(
                self,
                deploying_service=title,
                last_status=f"Rolling out {title} across {item.badge}...",
            ),
            _deploy_task,
        )

    def update(self, msg: Msg) -> Tuple["AppModel", Optional[Cmd], bool]:
        if isinstance(msg, WindowSizeMsg):
            # Dynamically adjust items per page based on terminal height
            per_p = max(2, min(6, (msg.height - 10) // 3))
            new_list = replace(self.list_model, per_page=per_p)._clamp_cursor(self.list_model.cursor)
            return replace(self, width=msg.width, height=msg.height, list_model=new_list), None, False

        if isinstance(msg, DeployFinishedMsg):
            return replace(
                self,
                deploying_service=None,
                last_status=f"✔ Successfully deployed {msg.service_title} in {msg.elapsed_sec:.1f}s!",
            ), None, False

        # Global keys when not actively typing inside the filter input
        if isinstance(msg, KeyMsg):
            if msg.key == "ctrl+c" or (msg.key == "q" and self.list_model.filter_state != FILTERING):
                return self, None, True

            # 's' cycles spinner preset style
            if msg.key == "s" and self.list_model.filter_state != FILTERING:
                next_idx = (self.spinner_preset_idx + 1) % len(SPINNER_PRESETS)
                _, preset_style = SPINNER_PRESETS[next_idx]
                new_sp = replace(
                    self.spinner,
                    style=preset_style,
                    frame=0,
                    tag=self.spinner.tag + 1,
                )
                return replace(self, spinner_preset_idx=next_idx, spinner=new_sp), new_sp.tick(), False

            # 'Enter' triggers async deployment on selected item (when not in FILTERING input mode)
            if msg.key == "enter" and self.list_model.filter_state != FILTERING:
                sel = self.list_model.selected_item
                if sel and self.deploying_service is None:
                    new_self, deploy_cmd = self._trigger_deploy(sel)
                    return new_self, deploy_cmd, False

        # Delegate to Spinner and ListModel
        new_sp, cmd_sp = self.spinner.update(msg)
        new_list, cmd_list = self.list_model.update(msg)

        return (
            replace(self, spinner=new_sp, list_model=new_list),
            batch(cmd_sp, cmd_list),
            False,
        )

    def view(self) -> str:
        preset_name, _ = SPINNER_PRESETS[self.spinner_preset_idx]
        sp_view = self.spinner.view()

        # Status Banner with live Spinner
        if self.deploying_service:
            status_line = (
                f"  {sp_view} \x1b[1;33mDEPLOYING:\x1b[0m {self.last_status} "
                f"\x1b[2m(Spinner: {preset_name})\x1b[0m"
            )
        else:
            status_line = (
                f"  {sp_view} \x1b[1;32mREADY:\x1b[0m {self.last_status} "
                f"\x1b[2m[Press 's' to cycle spinner: {preset_name}]\x1b[0m"
            )

        sep = f"  {fg_hex('#2D3436')}{'─' * max(40, min(self.width - 6, 76))}\x1b[0m"
        help_bar = (
            "  \x1b[2m/: Fuzzy Search • ↑/↓/j/k/Wheel: Navigate • ←/→/h/l: Page • "
            "Enter: Deploy Selected • s: Spinner Style • q: Quit\x1b[0m"
        )

        return "\n".join([
            "",
            self.list_model.view(width=self.width),
            sep,
            status_line,
            help_bar,
        ])


# =====================================================================
# 7. 60 FPS Cell-Diffing ScreenBuffer & Runtime Loop
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
    def from_ansi_and_scan_zones(
        cls, view_str: str, width: int, height: int, zm: ZoneManager
    ) -> "ScreenBuffer":
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

    async def execute_cmd(cmd: Cmd):
        msg = await cmd()
        if isinstance(msg, BatchMsg):
            for sub in msg.cmds:
                asyncio.create_task(execute_cmd(sub))
        elif msg is not None:
            await queue.put(msg)

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
                    m_mouse = SGR_MOUSE_RE.match(buf)
                    if m_mouse:
                        buf = buf[m_mouse.end():]
                        cb = int(m_mouse.group(1))
                        x, y = int(m_mouse.group(2)) - 1, int(m_mouse.group(3)) - 1
                        st = m_mouse.group(4)
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
            elif 1 <= ord(ch) <= 26:
                queue.put_nowait(KeyMsg(f"ctrl+{chr(ord(ch) + 96)}"))
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

        if init_cmd := model.init():
            asyncio.create_task(execute_cmd(init_cmd))

        while not should_quit:
            t0 = time.monotonic()

            if not dirty:
                msg = await queue.get()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, cmd, should_quit = model.update(msg)
                if cmd:
                    asyncio.create_task(execute_cmd(cmd))
                dirty = True

            while not queue.empty() and not should_quit:
                msg = queue.get_nowait()
                if isinstance(msg, WindowSizeMsg):
                    renderer.invalidate()
                model, cmd, should_quit = model.update(msg)
                if cmd:
                    asyncio.create_task(execute_cmd(cmd))
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
