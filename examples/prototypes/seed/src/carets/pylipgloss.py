from dataclasses import dataclass, replace
import re
from typing import Optional, Tuple, Union
import unicodedata

# Optional: Use wcwidth if installed, otherwise fallback to built-in unicodedata
try:
    from wcwidth import wcswidth as _wcswidth, wcwidth as _wcwidth
except ImportError:
    _wcwidth = None
    _wcswidth = None

# =====================================================================
# 1. ANSI & Unicode Visual Width Engine
# =====================================================================

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Removes all ANSI CSI escape sequences from a string."""
    return ANSI_RE.sub("", text)


def char_width(ch: str) -> int:
    """Returns the visual terminal column width (0, 1, or 2) of a single character."""
    if _wcwidth is not None:
        w = _wcwidth(ch)
        return max(0, w)
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Cc", "Cf", "Mn", "Me"):
        return 0
    # East Asian Wide (W) and Fullwidth (F) characters + Emojis take 2 cells
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1


def visual_width(text: str) -> int:
    """Returns the exact terminal cell width of a single line (ignoring ANSI codes)."""
    clean = strip_ansi(text)
    if _wcswidth is not None:
        w = _wcswidth(clean)
        if w >= 0:
            return w
    return sum(char_width(ch) for ch in clean)


def block_size(text: str) -> Tuple[int, int]:
    """Returns (width, height) in terminal cells of a multi-line string."""
    lines = text.split("\n")
    return max((visual_width(line) for line in lines), default=0), len(lines)


def truncate_ansi(line: str, max_width: int, tail: str = "…") -> str:
    """Truncates a string containing ANSI codes to max_width visual cells safely."""
    if visual_width(line) <= max_width:
        return line
    tail_w = visual_width(tail)
    target_w = max(0, max_width - tail_w)

    out = []
    cur_w = 0
    i = 0
    while i < len(line):
        # Preserve ANSI escape sequences without counting toward width
        m = ANSI_RE.match(line, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = line[i]
        w = char_width(ch)
        if cur_w + w > target_w:
            break
        out.append(ch)
        cur_w += w
        i += 1

    return "".join(out) + "\x1b[0m" + tail


# =====================================================================
# 2. Borders & Alignment Constants
# =====================================================================

LEFT = 0.0
CENTER = 0.5
RIGHT = 1.0

TOP = 0.0
MIDDLE = 0.5
BOTTOM = 1.0


@dataclass(frozen=True)
class Border:
    top: str = "─"
    bottom: str = "─"
    left: str = "│"
    right: str = "│"
    top_left: str = "╭"
    top_right: str = "╮"
    bottom_left: str = "╰"
    bottom_right: str = "╯"


ROUNDED_BORDER = Border("─", "─", "│", "│", "╭", "╮", "╰", "╯")
NORMAL_BORDER = Border("─", "─", "│", "│", "┌", "┐", "└", "┘")
THICK_BORDER = Border("━", "━", "┃", "┃", "┏", "┓", "┗", "┛")
DOUBLE_BORDER = Border("═", "═", "║", "║", "╔", "╗", "╚", "╝")


# =====================================================================
# 3. Color Helper (Supports ANSI 16, 256, and #RRGGBB TrueColor)
# =====================================================================

def color_code(color: Optional[str], is_bg: bool = False) -> str:
    """Converts '#RRGGBB' hex or 256-color number string into ANSI SGR parameters."""
    if not color:
        return ""
    prefix = "48" if is_bg else "38"
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return f"{prefix};2;{r};{g};{b}"
    if color.isdigit():
        return f"{prefix};5;{color}"
    return color


# =====================================================================
# 4. Layout Combinators: join_horizontal, join_vertical, place
# =====================================================================

def align_line(line: str, target_width: int, pos: float = LEFT, fill: str = " ") -> str:
    """Pads a single line with spaces to reach target_width at pos (0.0=L, 0.5=C, 1.0=R)."""
    shortfall = max(0, target_width - visual_width(line))
    if shortfall == 0:
        return line
    left_pad = int(round(shortfall * pos))
    right_pad = shortfall - left_pad
    return (fill * left_pad) + line + (fill * right_pad)


def join_horizontal(pos: float, *blocks: str, gap: int = 0) -> str:
    """
    Joins multiple multi-line string blocks side-by-side.
    pos: TOP (0.0), MIDDLE (0.5), or BOTTOM (1.0) vertical alignment.
    """
    if not blocks:
        return ""
    split_blocks = [b.split("\n") for b in blocks]
    widths = [max((visual_width(line) for line in lines), default=0) for lines in split_blocks]
    max_height = max(len(lines) for lines in split_blocks)
    spacer = " " * gap

    # Vertically pad each block to max_height and normalize line widths
    normalized_columns = []
    for lines, w in zip(split_blocks, widths):
        extra_rows = max_height - len(lines)
        top_pad = int(round(extra_rows * pos))
        bottom_pad = extra_rows - top_pad
        blank = " " * w
        padded_lines = (
                [blank] * top_pad
                + [align_line(line, w, LEFT) for line in lines]
                + [blank] * bottom_pad
        )
        normalized_columns.append(padded_lines)

    # Zip rows across all blocks horizontally
    out_rows = [spacer.join(row_parts) for row_parts in zip(*normalized_columns)]
    return "\n".join(out_rows)


def join_vertical(pos: float, *blocks: str) -> str:
    """
    Stacks multiple multi-line string blocks vertically.
    pos: LEFT (0.0), CENTER (0.5), or RIGHT (1.0) horizontal alignment.
    """
    if not blocks:
        return ""
    all_lines = []
    for b in blocks:
        all_lines.extend(b.split("\n"))
    max_w = max((visual_width(line) for line in all_lines), default=0)
    return "\n".join(align_line(line, max_w, pos) for line in all_lines)


def place(width: int, height: int, h_pos: float, v_pos: float, content: str) -> str:
    """Places a rendered block inside an empty (width x height) whitespace canvas."""
    lines = content.split("\n")
    extra_v = max(0, height - len(lines))
    top_pad = int(round(extra_v * v_pos))
    bottom_pad = extra_v - top_pad
    blank_row = " " * width

    placed_rows = (
            [blank_row] * top_pad
            + [align_line(line, width, h_pos) for line in lines[:height]]
            + [blank_row] * bottom_pad
    )
    return "\n".join(placed_rows)


# =====================================================================
# 5. Immutable Fluent Style Class (lipgloss.NewStyle())
# =====================================================================

def _unpack_sides(args: Tuple[int, ...]) -> Tuple[int, int, int, int]:
    """CSS-style shorthand unpacking: (all), (v, h), (t, h, b), or (t, r, b, l)."""
    if len(args) == 1:
        return (args[0], args[0], args[0], args[0])
    if len(args) == 2:
        return (args[0], args[1], args[0], args[1])
    if len(args) == 3:
        return (args[0], args[1], args[2], args[1])
    if len(args) == 4:
        return args
    raise ValueError("Expected 1 to 4 integer arguments for box spacing.")


@dataclass(frozen=True)
class Style:
    fg: Optional[str] = None
    bg: Optional[str] = None
    bold_flag: bool = False
    italic_flag: bool = False
    underline_flag: bool = False
    dim_flag: bool = False

    target_width: Optional[int] = None
    target_height: Optional[int] = None
    h_align: float = LEFT
    v_align: float = TOP

    pad_top: int = 0
    pad_right: int = 0
    pad_bottom: int = 0
    pad_left: int = 0

    margin_top: int = 0
    margin_right: int = 0
    margin_bottom: int = 0
    margin_left: int = 0

    border_style: Optional[Border] = None
    border_fg: Optional[str] = None
    border_bg: Optional[str] = None

    # --- Fluent Immutable Builders ---
    def foreground(self, color: str) -> "Style":
        return replace(self, fg=color)

    def background(self, color: str) -> "Style":
        return replace(self, bg=color)

    def bold(self, val: bool = True) -> "Style":
        return replace(self, bold_flag=val)

    def italic(self, val: bool = True) -> "Style":
        return replace(self, italic_flag=val)

    def underline(self, val: bool = True) -> "Style":
        return replace(self, underline_flag=val)

    def dim(self, val: bool = True) -> "Style":
        return replace(self, dim_flag=val)

    def width(self, w: int) -> "Style":
        return replace(self, target_width=w)

    def height(self, h: int) -> "Style":
        return replace(self, target_height=h)

    def align(self, h: float, v: float = TOP) -> "Style":
        return replace(self, h_align=h, v_align=v)

    def padding(self, *sides: int) -> "Style":
        t, r, b, l = _unpack_sides(sides)
        return replace(self, pad_top=t, pad_right=r, pad_bottom=b, pad_left=l)

    def margin(self, *sides: int) -> "Style":
        t, r, b, l = _unpack_sides(sides)
        return replace(self, margin_top=t, margin_right=r, margin_bottom=b, margin_left=l)

    def border(
            self,
            style: Border = ROUNDED_BORDER,
            fg: Optional[str] = None,
            bg: Optional[str] = None,
    ) -> "Style":
        return replace(self, border_style=style, border_fg=fg or self.border_fg, border_bg=bg or self.border_bg)

    # --- Internal SGR Helpers ---
    def _text_sgr(self) -> str:
        codes = []
        if self.bold_flag: codes.append("1")
        if self.dim_flag: codes.append("2")
        if self.italic_flag: codes.append("3")
        if self.underline_flag: codes.append("4")
        if self.fg: codes.append(color_code(self.fg, is_bg=False))
        if self.bg: codes.append(color_code(self.bg, is_bg=True))
        return f"\x1b[{';'.join(c for c in codes if c)}m" if codes else ""

    def _bg_sgr(self) -> str:
        if not self.bg:
            return ""
        return f"\x1b[{color_code(self.bg, is_bg=True)}m"

    def _border_sgr(self) -> str:
        codes = []
        if self.border_fg: codes.append(color_code(self.border_fg, is_bg=False))
        if self.border_bg: codes.append(color_code(self.border_bg, is_bg=True))
        return f"\x1b[{';'.join(c for c in codes if c)}m" if codes else ""

    # --- Core Render Pipeline ---
    def render(self, text: str) -> str:
        lines = text.split("\n")

        # 1. Determine inner content width
        natural_w = max((visual_width(line) for line in lines), default=0)
        if self.target_width is not None:
            inner_w = max(1, self.target_width - self.pad_left - self.pad_right)
        else:
            inner_w = natural_w

        # 2. Truncate or align each content line to inner_w
        processed_lines = []
        for line in lines:
            if visual_width(line) > inner_w:
                line = truncate_ansi(line, inner_w)
            processed_lines.append(align_line(line, inner_w, self.h_align))

        # 3. Apply vertical height and alignment
        if self.target_height is not None:
            inner_h = max(1, self.target_height - self.pad_top - self.pad_bottom)
            extra_v = max(0, inner_h - len(processed_lines))
            top_v = int(round(extra_v * self.v_align))
            bot_v = extra_v - top_v
            blank_inner = " " * inner_w
            processed_lines = (
                    [blank_inner] * top_v
                    + processed_lines[:inner_h]
                    + [blank_inner] * bot_v
            )

        # 4. Apply Padding + Text/Background SGR per line
        text_sgr = self._text_sgr()
        bg_sgr = self._bg_sgr()
        reset = "\x1b[0m" if (text_sgr or bg_sgr) else ""

        pad_l_str = " " * self.pad_left
        pad_r_str = " " * self.pad_right
        total_inner_w = self.pad_left + inner_w + self.pad_right
        empty_pad_row = f"{bg_sgr}{' ' * total_inner_w}{reset}"

        padded_rows = []
        for _ in range(self.pad_top):
            padded_rows.append(empty_pad_row)
        for line in processed_lines:
            # Re-inject text_sgr after any nested \x1b[0m inside the line
            if text_sgr:
                line = line.replace("\x1b[0m", f"\x1b[0m{text_sgr}")
            padded_rows.append(f"{bg_sgr}{pad_l_str}{text_sgr}{line}{bg_sgr}{pad_r_str}{reset}")
        for _ in range(self.pad_bottom):
            padded_rows.append(empty_pad_row)

        # 5. Wrap with Border
        if self.border_style is not None:
            b = self.border_style
            b_sgr = self._border_sgr()
            b_reset = "\x1b[0m" if b_sgr else ""

            top_edge = f"{b_sgr}{b.top_left}{b.top * total_inner_w}{b.top_right}{b_reset}"
            bot_edge = f"{b_sgr}{b.bottom_left}{b.bottom * total_inner_w}{b.bottom_right}{b_reset}"
            l_edge = f"{b_sgr}{b.left}{b_reset}"
            r_edge = f"{b_sgr}{b.right}{b_reset}"

            bordered_rows = [top_edge]
            for row in padded_rows:
                bordered_rows.append(f"{l_edge}{row}{r_edge}")
            bordered_rows.append(bot_edge)
            padded_rows = bordered_rows

        # 6. Wrap with Outer Margin (transparent spaces)
        if any((self.margin_top, self.margin_right, self.margin_bottom, self.margin_left)):
            box_w = visual_width(padded_rows[0]) if padded_rows else 0
            m_left = " " * self.margin_left
            m_right = " " * self.margin_right
            blank_margin_row = " " * (self.margin_left + box_w + self.margin_right)

            final_rows = (
                    [blank_margin_row] * self.margin_top
                    + [f"{m_left}{row}{m_right}" for row in padded_rows]
                    + [blank_margin_row] * self.margin_bottom
            )
            padded_rows = final_rows

        return "\n".join(padded_rows)


# =====================================================================
# 6. Demo: Multi-Column Dashboard with Emojis, CJK, and TrueColor
# =====================================================================

if __name__ == "__main__":
    # Header style
    title_style = (
        Style()
        .bold()
        .foreground("#FAFAFA")
        .background("#7D56F4")
        .padding(0, 2)
        .margin(0, 0, 1, 0)
    )

    # Card styles
    card_base = (
        Style()
        .width(28)
        .height(6)
        .padding(1, 2)
        .border(ROUNDED_BORDER, fg="#6C5CE7")
    )

    active_card = (
        card_base
        .border(DOUBLE_BORDER, fg="#00CEC9")
        .background("#1E272E")
        .foreground("#FFFFFF")
    )

    # Notice: Double-width emojis (🚀, 🍜) and CJK characters (東京) align perfectly!
    card1 = card_base.render(
        "\x1b[1;35mCluster A\x1b[0m\n"
        "Status: 🚀 Online\n"
        "Region: 東京 (Tokyo)\n"
        "Latency: \x1b[32m12ms\x1b[0m"
    )

    card2 = active_card.align(CENTER, MIDDLE).render(
        "\x1b[1;36m★ ACTIVE NODE ★\x1b[0m\n"
        "Throughput: 14.2 GB/s\n"
        "Queue: 🍜 0 pending"
    )

    card3 = (
        card_base
        .border(THICK_BORDER, fg="#FD79A8")
        .align(RIGHT)
        .render(
            "\x1b[1;33mBackup Replica\x1b[0m\n"
            "Sync: 99.98%\n"
            "Disk: 1.8 TB free\n"
            "Uptime: 412 days"
        )
    )

    # Join the 3 cards horizontally with a 2-space gap
    row_of_cards = join_horizontal(TOP, card1, card2, card3, gap=2)

    # Footer bar matching the total width of the 3 cards
    total_w, _ = block_size(row_of_cards)
    footer = (
        Style()
        .width(total_w - 2)
        .padding(0, 2)
        .border(NORMAL_BORDER, fg="#636E72")
        .foreground("#B2BEC3")
        .align(CENTER)
        .render("PyLipGloss Layout Engine • ANSI + Emoji + CJK Cell-Accurate Alignment")
    )

    dashboard = join_vertical(
        LEFT,
        title_style.render("⚡ CHARM-STYLE PYTHON LAYOUT ENGINE ⚡"),
        row_of_cards,
        footer,
    )

    print(dashboard)
