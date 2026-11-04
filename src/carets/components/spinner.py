# Immutable spinner component implementing update(msg) and view().

from __future__ import annotations

from dataclasses import dataclass, replace

from ..runtime import KeyMsg, Msg


@dataclass(frozen=True)
class Spinner:
    frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    frame: int = 0
    active: bool = True

    def update(self, msg: Msg) -> "Spinner":
        if isinstance(msg, KeyMsg) and msg.key in ("tick", "space"):
            return replace(self, frame=(self.frame + 1) % len(self.frames))
        return self

    def view(self) -> str:
        return self.frames[self.frame % len(self.frames)] if self.active and self.frames else ""

