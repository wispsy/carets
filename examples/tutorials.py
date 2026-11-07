"""Small models shared by the tutorials and synthetic application tests."""

from carets import Command, FocusManager, Form, Group, KeyMsg, TypedField, WindowSizeMsg


class Counter:
    def __init__(self): self.count = 0
    def update(self, message):
        if isinstance(message, KeyMsg) and message.key in ("+", "tick"):
            self.count += 1
    def view(self): return f"Count: {self.count}"


class Dashboard(Counter):
    def start(self): return Command.every(1, lambda: KeyMsg("tick"))
    def view(self): return f"Completed ticks: {self.count}"


class FormExample:
    def __init__(self):
        self.form = Form([Group([TypedField("count", "Count", int, default="1")])])
    def update(self, message):
        if isinstance(message, KeyMsg) and message.key == "enter":
            self.form.submit()
        elif isinstance(message, KeyMsg) and message.text:
            self.form.update("count", message.text)
    def view(self): return f"Count: {self.form.display('count')} ({self.form.status})"


class MultiPane:
    def __init__(self):
        self.focus = FocusManager()
        self.focus.register("left")
        self.focus.register("right")
        self.width, self.height = 40, 2
        self._layout()
    def _layout(self):
        half = self.width // 2
        self.focus.zones.define("left", 0, 0, half, self.height)
        self.focus.zones.define("right", half, 0, self.width - half, self.height)
    def update(self, message):
        if isinstance(message, WindowSizeMsg):
            self.width, self.height = message.width, message.height
            self._layout()
        else:
            self.focus.route(message)
    def view(self): return f"{self.focus.indicator('left')} Left | {self.focus.indicator('right')} Right"
