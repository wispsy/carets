# Immutable scrolling viewport component implementing update(msg) and view().

from __future__ import annotations

from dataclasses import dataclass, replace

from ..runtime import KeyMsg, Msg


@dataclass(frozen=True)
class Viewport:
    content: str = ""
    width: int = 80
    height: int = 24
    offset: int = 0

    def update(self, msg: Msg) -> "Viewport":
        if not isinstance(msg, KeyMsg):
            return self
        lines = self.content.splitlines()
        maximum = max(0, len(lines) - self.height)
        if msg.key in ("up", "k"):
            return replace(self, offset=max(0, self.offset - 1))
        if msg.key in ("down", "j"):
            return replace(self, offset=min(maximum, self.offset + 1))
        if msg.key == "pageup":
            return replace(self, offset=max(0, self.offset - self.height))
        if msg.key == "pagedown":
            return replace(self, offset=min(maximum, self.offset + self.height))
        return self

    def view(self) -> str:
        return "\n".join(self.content.splitlines()[self.offset : self.offset + self.height])

