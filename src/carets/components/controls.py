"""Small immutable controls with visible, color-independent state."""
from dataclasses import dataclass, replace
import math

from .base import ComponentState, activated, text_size


class _Control:
    def measure(self):
        return text_size(self.view())

    def accessibility(self):
        return self.state.describe() + ": " + self.view()

    def update(self, message):
        return self

    def _mark(self, text):
        prefix = "> " if self.state.focused and not self.state.disabled else "  "
        suffix = " [disabled]" if self.state.disabled else " [read only]" if self.state.read_only else ""
        return prefix + text + suffix


@dataclass(frozen=True)
class Label(_Control):
    text: str
    state: ComponentState = ComponentState("label")

    def view(self):
        return self._mark(self.text)


@dataclass(frozen=True)
class Button(_Control):
    text: str
    state: ComponentState = ComponentState("button")
    activations: int = 0

    def update(self, message):
        return replace(self, activations=self.activations + 1) if self.state.editable and activated(message) else self

    def view(self):
        return self._mark("[ " + self.text + " ]")


@dataclass(frozen=True)
class Checkbox(_Control):
    text: str
    checked: bool = False
    state: ComponentState = ComponentState("checkbox")

    def update(self, message):
        return replace(self, checked=not self.checked) if self.state.editable and activated(message) else self

    def view(self):
        return self._mark(("[x] " if self.checked else "[ ] ") + self.text)


@dataclass(frozen=True)
class Progress(_Control):
    value: float = 0
    total: float = 1
    width: int = 12
    state: ComponentState = ComponentState("progress")

    def __post_init__(self):
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in (self.value, self.total)) or self.total <= 0 or not 0 <= self.value <= self.total:
            raise ValueError("Progress requires finite 0 <= value <= total and positive total")
        if type(self.width) is not int or not 0 <= self.width <= 1024:
            raise ValueError("Progress width must be between zero and 1024 cells")

    def view(self):
        filled = int(self.width * self.value / self.total)
        return self._mark("[" + "#" * filled + "-" * (self.width - filled) + f"] {100 * self.value / self.total:.0f}%")
