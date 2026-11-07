"""Scoped focus and phased event routing over caller-owned component zones."""

from dataclasses import dataclass, replace

from .runtime import KeyMsg, MouseMsg
from .zone import ZoneManager


@dataclass(frozen=True)
class FocusComponent:
    id: str
    scope: str = "root"
    parent: str | None = None
    disabled: bool = False
    read_only: bool = False


@dataclass
class FocusEvent:
    message: object
    target: str
    current: str = ""
    phase: str = ""
    stopped: bool = False

    def stop(self):
        self.stopped = True


class FocusManager:
    def __init__(self, zones=None):
        self.zones = zones if zones is not None else ZoneManager()
        self.components = {}
        self._scopes = {"root"}
        self._stack = [("root", None, False)]
        self._handlers = {}
        self.focused = None

    @property
    def active_scope(self):
        return self._stack[-1][0]

    def add_scope(self, name):
        if type(name) is not str or not name or name in self._scopes:
            raise ValueError("Scope names must be nonempty and unique")
        self._scopes.add(name)

    def register(self, id, *, scope="root", parent=None, disabled=False, read_only=False):
        if type(id) is not str or not id or id in self.components or scope not in self._scopes:
            raise ValueError("Component identity/scope must be valid and unique")
        if type(disabled) is not bool or type(read_only) is not bool:
            raise TypeError("Component states must be booleans")
        if parent is not None and (parent not in self.components or self.components[parent].scope != scope):
            raise ValueError("Parent must be an existing component in the same scope")
        component = FocusComponent(id, scope, parent, disabled, read_only)
        self.components[id] = component
        if self.focused is None and scope == self.active_scope and not disabled:
            self.focused = id
        return component

    def set_state(self, id, *, disabled=None, read_only=None):
        updates = {key: value for key, value in (("disabled", disabled), ("read_only", read_only)) if value is not None}
        if any(type(value) is not bool for value in updates.values()):
            raise TypeError("Component states must be booleans")
        self.components[id] = replace(self.components[id], **updates)
        if self.focused == id and self.components[id].disabled:
            eligible = self._eligible()
            self.focused = eligible[0] if eligible else None

    def _eligible(self):
        return [id for id, component in self.components.items() if component.scope == self.active_scope and not component.disabled]

    def focus(self, id):
        if id not in self._eligible():
            raise ValueError("Focus must remain in the active enabled scope")
        self.focused = id

    def activate(self, scope, *, modal=False):
        if scope not in self._scopes or type(modal) is not bool:
            raise ValueError("Unknown scope or invalid modal flag")
        if self._stack[-1][2]:
            raise ValueError("Dismiss the active modal scope before leaving it")
        self._stack.append((scope, self.focused, modal))
        eligible = self._eligible()
        self.focused = eligible[0] if eligible else None

    def dismiss(self):
        if len(self._stack) == 1:
            raise ValueError("Root scope cannot be dismissed")
        _, previous, _ = self._stack.pop()
        eligible = self._eligible()
        self.focused = previous if previous in eligible else (eligible[0] if eligible else None)

    def indicator(self, id):
        return ">" if id == self.focused else " "

    def navigate(self, direction):
        eligible = self._eligible()
        if not eligible:
            self.focused = None
        elif direction in ("next", "previous"):
            index = eligible.index(self.focused) if self.focused in eligible else -1
            self.focused = eligible[(index + (1 if direction == "next" else -1)) % len(eligible)]
        elif direction in ("left", "right", "up", "down"):
            origin = self.zones.get(self.focused)
            if origin is None:
                return self.focused
            x, y = origin.x + origin.width / 2, origin.y + origin.height / 2
            candidates = []
            for id in eligible:
                zone = self.zones.get(id)
                if zone is None or id == self.focused:
                    continue
                dx, dy = zone.x + zone.width / 2 - x, zone.y + zone.height / 2 - y
                primary = {"right": dx, "left": -dx, "down": dy, "up": -dy}[direction]
                if primary > 0:
                    candidates.append((dx * dx + dy * dy, id))
            if candidates:
                self.focused = min(candidates)[1]
        else:
            raise ValueError("Unsupported focus direction")
        return self.focused

    def on(self, id, phase, handler):
        if id not in self.components or phase not in ("capture", "target", "bubble") or not callable(handler):
            raise ValueError("Register a callable for a known component and event phase")
        self._handlers.setdefault((id, phase), []).append(handler)

    def route(self, message):
        if isinstance(message, KeyMsg) and message.key in ("tab", "shift-tab", "backtab"):
            self.navigate("previous" if message.key != "tab" or "shift" in message.modifiers else "next")
            return None
        target = self.focused
        if isinstance(message, MouseMsg):
            target = next((zone.name for zone in reversed(tuple(self.zones)) if zone.contains(message.x, message.y)
                           and zone.name in self.components and self.components[zone.name].scope == self.active_scope), None)
            if target is not None and not self.components[target].disabled:
                self.focus(target)
        elif not isinstance(message, KeyMsg):
            return None
        if target is None:
            return None
        component = self.components[target]
        if component.disabled or component.read_only:
            return None
        ancestors = []
        parent = component.parent
        while parent is not None:
            ancestors.append(parent)
            parent = self.components[parent].parent
        event = FocusEvent(message, target)
        phases = [(id, "capture") for id in reversed(ancestors)] + [(target, "target")] + [(id, "bubble") for id in ancestors]
        for id, phase in phases:
            event.current, event.phase = id, phase
            for handler in self._handlers.get((id, phase), ()):
                if handler(event):
                    event.stop()
                if event.stopped:
                    return event
        return event
