# Immutable text input component implementing update(msg) and view().

from __future__ import annotations

from dataclasses import dataclass, replace

from ..runtime import KeyMsg, Msg
from ..unicode import graphemes


@dataclass(frozen=True)
class TextInput:
    value: str = ""
    placeholder: str = ""
    cursor: int = 0
    focused: bool = True

    def __post_init__(self):
        boundaries = [0]
        for cluster in graphemes(self.value):
            boundaries.append(boundaries[-1] + len(cluster))
        # Keep the public character-offset representation, at a cluster boundary.
        object.__setattr__(self, "cursor", max(n for n in boundaries if n <= max(0, min(self.cursor, len(self.value)))))

    def _boundaries(self):
        result = [0]
        for cluster in graphemes(self.value):
            result.append(result[-1] + len(cluster))
        return result

    def update(self, msg: Msg) -> "TextInput":
        if not self.focused or (not isinstance(msg, KeyMsg) or msg.action == "release"):
            return self
        boundaries = self._boundaries()
        previous = max((n for n in boundaries if n < self.cursor), default=0)
        following = min((n for n in boundaries if n > self.cursor), default=len(self.value))
        if msg.key == "left":
            return replace(self, cursor=previous)
        if msg.key == "right":
            return replace(self, cursor=following)
        if msg.key == "backspace" and self.cursor:
            return replace(self, value=self.value[:previous] + self.value[self.cursor :], cursor=previous)
        if msg.key == "delete" and self.cursor < len(self.value):
            return replace(self, value=self.value[: self.cursor] + self.value[following:])
        if msg.key == "home":
            return replace(self, cursor=0)
        if msg.key == "end":
            return replace(self, cursor=len(self.value))
        if msg.text and not set(msg.modifiers).intersection(("ctrl", "alt", "super", "meta")):
            return replace(self, value=self.value[: self.cursor] + msg.text + self.value[self.cursor :], cursor=self.cursor + len(msg.text))
        return self

    def view(self) -> str:
        text = self.value or self.placeholder
        if self.focused:
            return text[: self.cursor] + "|" + text[self.cursor :]
        return text

