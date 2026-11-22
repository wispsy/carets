"""Component gallery using the same shell as the independent queue example."""
import asyncio
from dataclasses import replace

from carets import AppShell, FocusManager, KeyMsg, Program, ShellCommand, WindowSizeMsg
from carets.components import Button, Checkbox, ComponentState, Progress


class Gallery:
    def __init__(self):
        self.width, self.height = 80, 24
        self.shell = AppShell("Component gallery")
        self.focus = FocusManager()
        self.controls = (Button("Save", ComponentState("save")),
                         Checkbox("Enable", state=ComponentState("enable")), Progress(.6))
        for control in self.controls[:2]:
            self.focus.register(control.state.id)

    def update(self, message):
        if isinstance(message, WindowSizeMsg):
            self.width, self.height = message.width, message.height
        elif isinstance(message, KeyMsg):
            self.focus.route(message)
            self.controls = tuple(replace(c, state=replace(c.state, focused=c.state.id == self.focus.focused)).update(message) for c in self.controls)

    def view(self):
        controls = [replace(c, state=replace(c.state, focused=c.state.id == self.focus.focused)) for c in self.controls]
        return self.shell.frame(self.width, self.height, body="\n".join(c.view() for c in controls),
            navigation=("Controls",), commands=(ShellCommand("next", "Tab", "focus"),)).buffer


if __name__ == "__main__":
    asyncio.run(Program(Gallery()).run())
