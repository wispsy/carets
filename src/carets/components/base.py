"""Structural component contracts; inheritance and terminal ownership are optional."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from ..layout import Size
from ..runtime import KeyMsg, Msg
from ..unicode import visual_width


@dataclass(frozen=True)
class ComponentState:
    id: str
    label: str = ""
    focused: bool = False
    disabled: bool = False
    read_only: bool = False

    def __post_init__(self):
        if type(self.id) is not str or not self.id or len(self.id) > 128:
            raise ValueError("Components require a stable bounded identity")
        if type(self.label) is not str or any(type(getattr(self, key)) is not bool for key in ("focused", "disabled", "read_only")):
            raise TypeError("Invalid component state")

    @property
    def editable(self):
        return self.focused and not self.disabled and not self.read_only

    def describe(self):
        flags = [name.replace("_", " ") for name in ("focused", "disabled", "read_only") if getattr(self, name)]
        return (self.label or self.id) + (" (" + ", ".join(flags) + ")" if flags else "")


@runtime_checkable
class Component(Protocol):
    state: ComponentState

    def update(self, message: Msg) -> Component: ...
    def measure(self) -> Size: ...
    def view(self) -> str: ...
    def accessibility(self) -> str: ...


def text_size(text):
    lines = text.splitlines() or [""]
    return Size(max(map(visual_width, lines)), len(lines))


def activated(message):
    return isinstance(message, KeyMsg) and message.action == "press" and message.key in ("enter", "space", " ")


@dataclass(frozen=True)
class ComponentAdapter:
    """Give an existing immutable update/view model the shared state contract.

    Navigation in read-only lists/viewports is allowed; text edits are blocked.
    Animation messages reach an unfocused spinner. Callers still own scheduling.
    """
    model: object
    state: ComponentState

    def _bound(self):
        from .textinput import TextInput
        return replace(self.model, focused=self.state.focused and not self.state.disabled) if isinstance(self.model, TextInput) else self.model

    def update(self, message):
        from .spinner import Spinner
        from .textinput import TextInput
        if self.state.disabled or (not self.state.focused and not isinstance(self.model, Spinner)):
            return self
        if self.state.read_only and isinstance(self.model, TextInput):
            return self
        return replace(self, model=self._bound().update(message))

    def view(self):
        marker = "> " if self.state.focused and not self.state.disabled else "  "
        flags = " [disabled]" if self.state.disabled else " [read only]" if self.state.read_only else ""
        return marker + self._bound().view() + flags

    def measure(self):
        return text_size(self.view())

    def accessibility(self):
        return self.state.describe() + ": " + self._bound().view()
