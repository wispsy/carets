# ANSI styling, terminal width helpers, and box alignment combinators.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def visual_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in ANSI_RE.sub("", text))


def truncate_ansi(text: str, width: int, ellipsis: str = "…") -> str:
    if width <= 0:
        return ""
    if visual_width(text) <= width:
        return text
    target = max(0, width - visual_width(ellipsis))
    result: list[str] = []
    visible = 0
    position = 0
    for match in ANSI_RE.finditer(text):
        segment = text[position : match.start()]
        for char in segment:
            amount = visual_width(char)
            if visible + amount > target:
                return "".join(result) + ellipsis
            result.append(char)
            visible += amount
        result.append(match.group())
        position = match.end()
    for char in text[position:]:
        amount = visual_width(char)
        if visible + amount > target:
            break
        result.append(char)
        visible += amount
    return "".join(result) + ellipsis


@dataclass(frozen=True)
class Border:
    top: str = "─"
    bottom: str = "─"
    left: str = "│"
    right: str = "│"
    top_left: str = "┌"
    top_right: str = "┐"
    bottom_left: str = "└"
    bottom_right: str = "┘"

    @classmethod
    def rounded(cls) -> "Border":
        return cls("─", "─", "│", "│", "╭", "╮", "╰", "╯")


@dataclass(frozen=True)
class Style:
    foreground: str | None = None
    background: str | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    border: Border | None = None
    width: int | None = None
    height: int | None = None

    def copy(self, **changes: object) -> "Style":
        return replace(self, **changes)

    def render(self, text: str) -> str:
        lines = text.splitlines() or [""]
        content_width = max((visual_width(line) for line in lines), default=0)
        width = self.width or content_width
        top, right, bottom, left = self.padding
        width = max(width, content_width) + left + right
        padded = [" " * left + line + " " * max(0, width - left - right - visual_width(line)) + " " * right for line in lines]
        while self.height and len(padded) < self.height:
            padded.append(" " * width)
        if self.border:
            b = self.border
            padded = [b.top_left + b.top * width + b.top_right] + [b.left + line + b.right for line in padded] + [b.bottom_left + b.bottom * width + b.bottom_right]
        prefix = "".join(code for enabled, code in ((self.bold, "\x1b[1m"), (self.dim, "\x1b[2m"), (self.italic, "\x1b[3m")) if enabled)
        return "\n".join(prefix + line + ("\x1b[0m" if prefix else "") for line in padded)

    def join_horizontal(self, *parts: str, gap: int = 0) -> str:
        return (" " * gap).join(parts)

    def join_vertical(self, *parts: str, gap: int = 0) -> str:
        return ("\n" * (gap + 1)).join(parts)

    def align(self, text: str, width: int, *, horizontal: str = "left") -> str:
        missing = max(0, width - visual_width(text))
        if horizontal == "right":
            return " " * missing + text
        if horizontal == "center":
            left = missing // 2
            return " " * left + text + " " * (missing - left)
        return text + " " * missing
