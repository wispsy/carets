# Screen buffers, cell diffs, and DEC synchronized terminal output.

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TextIO

from .style import visual_width


@dataclass(frozen=True)
class Cell:
    char: str = " "
    style: str = ""


class ScreenBuffer:
    def __init__(self, width: int, height: int, fill: Cell | None = None) -> None:
        self.width = max(0, width)
        self.height = max(0, height)
        self._fill = fill or Cell()
        self.cells = [[self._fill for _ in range(self.width)] for _ in range(self.height)]

    def clear(self) -> None:
        for row in self.cells:
            row[:] = [self._fill for _ in range(self.width)]

    def write(self, x: int, y: int, text: str, style: str = "") -> None:
        if not (0 <= y < self.height):
            return
        column = x
        for char in text:
            if column >= self.width:
                break
            if column >= 0 and char != "\n":
                self.cells[y][column] = Cell(char, style)
            column += 1

    def from_lines(self, lines: Iterable[str]) -> None:
        self.clear()
        for y, line in enumerate(lines):
            if y >= self.height:
                break
            self.write(0, y, line[: self.width])


class CellDiffRenderer:
    """Render only changed cells, wrapped in DEC mode 2026 synchronization."""

    SYNC_START = "\x1b[?2026h"
    SYNC_END = "\x1b[?2026l"

    def __init__(self, width: int = 80, height: int = 24) -> None:
        self.width = width
        self.height = height
        self.previous = ScreenBuffer(width, height)

    def render(self, content: str | ScreenBuffer) -> str:
        current = content if isinstance(content, ScreenBuffer) else self._buffer_for_text(content)
        output: list[str] = [self.SYNC_START]
        for y, row in enumerate(current.cells):
            previous_row = self.previous.cells[y]
            x = 0
            while x < current.width:
                if row[x] == previous_row[x]:
                    x += 1
                    continue
                start = x
                style = row[x].style
                chars: list[str] = []
                while x < current.width and row[x] != previous_row[x] and row[x].style == style:
                    chars.append(row[x].char)
                    x += 1
                output.append(f"\x1b[{y + 1};{start + 1}H{style}{''.join(chars)}\x1b[0m")
        output.append(self.SYNC_END)
        self.previous = current
        return "".join(output)

    def _buffer_for_text(self, content: str) -> ScreenBuffer:
        buffer = ScreenBuffer(self.width, self.height)
        buffer.from_lines(content.splitlines() or [""])
        return buffer

