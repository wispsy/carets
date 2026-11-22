"""A separate domain model composing the public shell and list adapter."""
import asyncio
from dataclasses import replace

from carets import AppShell, Program, WindowSizeMsg
from carets.components import ComponentAdapter, ComponentState, ListModel


class QueueApplication:
    def __init__(self):
        self.width, self.height = 80, 24
        self.shell = AppShell("Delivery queue")
        self.items = ComponentAdapter(ListModel(("Package ready", "Review pending", "Release queued")),
                                      ComponentState("jobs", "Queued deliveries", focused=True, read_only=True))

    def update(self, message):
        if isinstance(message, WindowSizeMsg):
            self.width, self.height = message.width, message.height
        else:
            self.items = self.items.update(message)

    def view(self):
        return self.shell.frame(self.width, self.height, body=self.items.view(), navigation=("Deliveries",),
                                status="Read only | Up/Down select").buffer


if __name__ == "__main__":
    asyncio.run(Program(QueueApplication()).run())
