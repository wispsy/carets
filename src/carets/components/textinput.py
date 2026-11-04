# Immutable text input component implementing update(msg) and view().

from __future__ import annotations

from dataclasses import dataclass, replace

from ..runtime import KeyMsg, Msg


@dataclass(frozen=True)
class TextInput:
    value: str = ""
    placeholder: str = ""
    cursor: int = 0
    focused: bool = True

    def update(self, msg: Msg) -> "TextInput":
        if not self.focused or not isinstance(msg, KeyMsg):
            return self
        if msg.key == "left":
            return replace(self, cursor=max(0, self.cursor - 1))
        if msg.key == "right":
            return replace(self, cursor=min(len(self.value), self.cursor + 1))
        if msg.key == "backspace" and self.cursor:
            return replace(self, value=self.value[: self.cursor - 1] + self.value[self.cursor :], cursor=self.cursor - 1)
        if msg.key == "delete" and self.cursor < len(self.value):
            return replace(self, value=self.value[: self.cursor] + self.value[self.cursor + 1 :])
        if msg.text:
            return replace(self, value=self.value[: self.cursor] + msg.text + self.value[self.cursor :], cursor=self.cursor + len(msg.text))
        return self

    def view(self) -> str:
        text = self.value or self.placeholder
        if self.focused:
            return text[: self.cursor] + "|" + text[self.cursor :]
        return text

