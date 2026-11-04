# Immutable selectable list component implementing update(msg) and view().

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Generic, Sequence, TypeVar

from ..runtime import KeyMsg, Msg

T = TypeVar("T")


@dataclass(frozen=True)
class ListModel(Generic[T]):
    items: tuple[T, ...] = ()
    selected: int = 0
    title: str = ""

    def __init__(self, items: Sequence[T] = (), selected: int = 0, title: str = "") -> None:
        object.__setattr__(self, "items", tuple(items))
        object.__setattr__(self, "selected", max(0, min(selected, len(items) - 1)) if items else 0)
        object.__setattr__(self, "title", title)

    def update(self, msg: Msg) -> "ListModel[T]":
        if not isinstance(msg, KeyMsg) or not self.items:
            return self
        if msg.key in ("up", "k"):
            return replace(self, selected=max(0, self.selected - 1))
        if msg.key in ("down", "j"):
            return replace(self, selected=min(len(self.items) - 1, self.selected + 1))
        return self

    def view(self) -> str:
        rows = [self.title] if self.title else []
        rows.extend(("> " if index == self.selected else "  ") + str(item) for index, item in enumerate(self.items))
        return "\n".join(rows)

    @property
    def selected_item(self) -> T | None:
        return self.items[self.selected] if self.items else None

