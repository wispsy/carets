# Runtime messages, batching, and the asyncio program loop.

from __future__ import annotations

import asyncio
import inspect
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterable, Callable, Iterable, Protocol, TextIO

from .commands import Command


class Msg:
    """Base type for events delivered to a model."""


@dataclass(frozen=True)
class KeyMsg(Msg):
    key: str
    text: str | None = None
    modifiers: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class MouseMsg(Msg):
    x: int
    y: int
    button: str = "none"
    action: str = "press"
    modifiers: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class WindowSizeMsg(Msg):
    width: int
    height: int


@dataclass(frozen=True)
class BatchMsg(Msg):
    messages: tuple[Msg, ...]


@dataclass(frozen=True)
class CommandErrorMsg(Msg):
    command_id: str
    error: Exception


def batch(*messages: Msg | Iterable[Msg]) -> BatchMsg:
    """Create one message containing a flattened sequence of messages."""
    flattened: list[Msg] = []
    for item in messages:
        if isinstance(item, Msg):
            flattened.append(item)
        else:
            flattened.extend(item)
    return BatchMsg(tuple(flattened))


class Model(Protocol):
    def update(self, msg: Msg) -> Any: ...

    def view(self) -> str: ...


class Program:
    """Connect a model, input parser, and renderer in an asyncio loop."""

    def __init__(
        self,
        model: Model,
        *,
        parser: AsyncIterable[Msg] | None = None,
        renderer: Any | None = None,
        input_stream: Any = sys.stdin.buffer,
        output_stream: TextIO = sys.stdout,
        sleep: Callable = asyncio.sleep,
        terminal: Any = None,
    ) -> None:
        self.model = model
        self.parser = parser
        self.renderer = renderer
        self.input_stream = input_stream
        self.output_stream = output_stream
        self._stop = asyncio.Event()
        self._queue = asyncio.Queue()
        self._tasks = {}
        self._cleanups = []
        self._sleep = sleep
        self.terminal = terminal
        self._running = False
        self._used = False
        self._next_command = 0

    def stop(self) -> None:
        self._stop.set()
        self._queue.put_nowait(("stop", None))

    def post(self, message: Msg) -> None:
        """Post from the owning event-loop thread; dispatch remains serialized."""
        if not isinstance(message, Msg):
            raise TypeError("Expected a Msg")
        self._queue.put_nowait(("message", message))

    def add_cleanup(self, cleanup: Callable) -> None:
        if self._used and not self._running:
            raise RuntimeError("Program is already closed")
        if not callable(cleanup):
            raise TypeError("Cleanup must be callable")
        self._cleanups.append(cleanup)

    def schedule(self, command: Command) -> str:
        if not self._running:
            raise RuntimeError("Commands require a running Program")
        if not isinstance(command, Command):
            raise TypeError("Expected a Command")
        self._next_command += 1
        identity = f"command-{self._next_command}"

        async def produce():
            try:
                if command.delay:
                    await self._sleep(command.delay)
                while True:
                    message = command.produce()
                    if inspect.isawaitable(message):
                        message = await message
                    if message is not None:
                        self.post(message)
                    if command.interval is None:
                        break
                    await self._sleep(command.interval)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.post(CommandErrorMsg(identity, error))

        task = asyncio.create_task(produce())
        self._tasks[identity] = task
        def finished(_task):
            self._tasks.pop(identity, None)
        task.add_done_callback(finished)
        return identity

    def cancel(self, command_id: str) -> bool:
        task = self._tasks.get(command_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def render(self):
        if self.renderer is not None:
            rendered = self.renderer.render(self.model.view())
            if inspect.isawaitable(rendered):
                rendered = await rendered
            if rendered is not None:
                self.output_stream.write(str(rendered))
                self.output_stream.flush()

    async def dispatch(self, msg: Msg) -> None:
        messages = msg.messages if isinstance(msg, BatchMsg) else (msg,)
        for item in messages:
            result = self.model.update(item)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, Command):
                self.schedule(result)
            elif isinstance(result, (tuple, list)) and all(isinstance(command, Command) for command in result):
                for command in result:
                    self.schedule(command)
            await self.render()

    async def run(
        self,
        messages: AsyncIterable[Msg] | Iterable[Msg] | None = None,
        *,
        stop_on_eof: bool = True,
        commands: Iterable[Command] = (),
    ) -> Model:
        """Run until ``stop`` is called or the input stream ends."""
        if self._used:
            raise RuntimeError("Program instances run once; construct a new Program")
        self._used = self._running = True
        source = messages if messages is not None else self.parser
        if source is None:
            from .input import AnsiInputParser

            source = AnsiInputParser(self.input_stream)
        async def read():
            try:
                if hasattr(source, "__aiter__"):
                    async for message in source:
                        self.post(message)
                else:
                    for message in source:
                        self.post(message)
                self._queue.put_nowait(("eof", None))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._queue.put_nowait(("error", error))

        reader = None
        failure = None
        try:
            if self.terminal is not None:
                self.terminal.start(self)
            reader = asyncio.create_task(read())
            for command in commands:
                self.schedule(command)
            await self.render()
            while not self._stop.is_set():
                kind, value = await self._queue.get()
                try:
                    if kind == "message":
                        await self.dispatch(value)
                    elif kind == "error":
                        raise value
                    elif kind == "eof" and stop_on_eof:
                        self.stop()
                finally:
                    self._queue.task_done()
            return self.model
        except BaseException as error:
            failure = error
            raise
        finally:
            tasks = [*self._tasks.values(), *([reader] if reader is not None else [])]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            cleanups, self._cleanups = self._cleanups, []
            errors = []
            for cleanup in reversed(cleanups):
                try:
                    result = cleanup()
                    if inspect.isawaitable(result):
                        await result
                except BaseException as error:
                    errors.append(error)
            self._running = False
            if errors and failure is None:
                raise errors[0]

