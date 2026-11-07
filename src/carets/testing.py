"""Deterministic fixtures for application tests without a physical terminal."""

import asyncio
import heapq
import io
import math

from .input import AnsiInputParser
from .runtime import Program
from .style import visual_width
from .terminal import TerminalCapabilities, TerminalSession


class ManualClock:
    def __init__(self):
        self.now = 0.0
        self._sleepers = []
        self._order = 0

    async def sleep(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Delay must be finite and nonnegative")
        if seconds == 0:
            await asyncio.sleep(0)
            return
        self._order += 1
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (self.now + seconds, self._order, future))
        await future

    def advance(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Clock advances must be finite and nonnegative")
        self.now += seconds
        while self._sleepers and self._sleepers[0][0] <= self.now:
            _, _, future = heapq.heappop(self._sleepers)
            if not future.done():
                future.set_result(None)


class FakeTerminal:
    capabilities = TerminalCapabilities(True, True, True, True, True)

    def __init__(self, width=80, height=24):
        self.input = io.BytesIO()
        self.output = io.StringIO()
        self.dimensions = (width, height)
        self.raw = False
        self.restore_count = 0
        self.handlers = {}

    def size(self): return self.dimensions
    def capture_raw(self): return self.raw
    def enter_raw(self): self.raw = True
    def restore_raw(self, state):
        self.raw = state
        self.restore_count += 1
    def install_signal(self, name, callback):
        previous = self.handlers.get(name)
        self.handlers[name] = callback
        return name, previous
    def restore_signal(self, token):
        name, previous = token
        if previous is None:
            self.handlers.pop(name, None)
        else:
            self.handlers[name] = previous
    def resize(self, width, height):
        self.dimensions = (width, height)
        if "resize" in self.handlers:
            self.handlers["resize"]()


class SnapshotRenderer:
    def __init__(self):
        self.frames = []

    def render(self, view):
        self.frames.append(str(view))
        return ""

    @property
    def latest(self):
        return self.frames[-1] if self.frames else ""


def assert_layout(zones, width, height):
    for zone in zones:
        if min(zone.x, zone.y, zone.width, zone.height) < 0 or zone.x + zone.width > width or zone.y + zone.height > height:
            raise AssertionError(f"Zone {zone.name!r} exceeds {width}x{height}")


class TestProgram:
    """Async context manager; send inputs, advance time and assert plain frames."""

    def __init__(self, model, *, terminal=None, clock=None):
        self.model = model
        self.terminal = terminal if terminal is not None else FakeTerminal()
        self.clock = clock if clock is not None else ManualClock()
        self.renderer = SnapshotRenderer()
        self.parser = AnsiInputParser()
        self.program = Program(model, renderer=self.renderer, output_stream=self.terminal.output,
            sleep=self.clock.sleep, terminal=TerminalSession(self.terminal.input, self.terminal.output, backend=self.terminal))
        self.task = None

    async def __aenter__(self):
        self.task = asyncio.create_task(self.program.run([], stop_on_eof=False))
        await self.settle()
        return self

    async def __aexit__(self, *_errors):
        self.program.stop()
        await self.task

    async def settle(self):
        await self.program.idle()
        if self.task is not None and self.task.done():
            await self.task

    async def send(self, *messages):
        for message in messages:
            self.program.post(message)
        await self.settle()

    async def send_bytes(self, data):
        await self.send(*self.parser.feed(data))

    async def advance(self, seconds):
        self.clock.advance(seconds)
        await self.settle()

    async def resize(self, width, height):
        self.terminal.resize(width, height)
        await self.settle()

    async def wait_for(self, predicate, *, turns=100):
        for _ in range(turns):
            await self.settle()
            if predicate():
                return
        raise AssertionError("Application did not reach the expected state")

    def assert_snapshot(self, expected):
        if self.renderer.latest != expected:
            raise AssertionError(f"Expected {expected!r}, received {self.renderer.latest!r}")

    def assert_fits(self, width, height):
        lines = self.renderer.latest.splitlines()
        if len(lines) > height or any(visual_width(line) > width for line in lines):
            raise AssertionError(f"Snapshot exceeds {width}x{height}")
