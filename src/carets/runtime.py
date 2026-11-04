# Runtime messages, batching, and the asyncio program loop.

from __future__ import annotations

import asyncio
import inspect
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterable, Callable, Iterable, Protocol, TextIO


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
    ) -> None:
        self.model = model
        self.parser = parser
        self.renderer = renderer
        self.input_stream = input_stream
        self.output_stream = output_stream
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def dispatch(self, msg: Msg) -> None:
        messages = msg.messages if isinstance(msg, BatchMsg) else (msg,)
        for item in messages:
            result = self.model.update(item)
            if inspect.isawaitable(result):
                await result
            if self.renderer is not None:
                rendered = self.renderer.render(self.model.view())
                if inspect.isawaitable(rendered):
                    rendered = await rendered
                if rendered is not None:
                    self.output_stream.write(str(rendered))
                    self.output_stream.flush()

    async def run(
        self,
        messages: AsyncIterable[Msg] | Iterable[Msg] | None = None,
        *,
        stop_on_eof: bool = True,
    ) -> Model:
        """Run until ``stop`` is called or the input stream ends."""
        source = messages or self.parser
        if source is None:
            from .input import AnsiInputParser

            source = AnsiInputParser(self.input_stream)
        if hasattr(source, "__aiter__"):
            async for msg in source:  # type: ignore[union-attr]
                await self.dispatch(msg)
                if self._stop.is_set():
                    break
        else:
            for msg in source:  # type: ignore[union-attr]
                await self.dispatch(msg)
                if self._stop.is_set():
                    break
        if stop_on_eof:
            self.stop()
        return self.model

