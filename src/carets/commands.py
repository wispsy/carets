"""Invocation-owned message producers; no event loop or task is started on import."""

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class Command:
    """Produce a message (or None), optionally delayed or repeated.

    Synchronous producers run on the application thread. Async producers may await
    I/O. Each scheduled command is independently cancellable by its returned ID.
    """

    produce: Callable
    delay: float = 0
    interval: float | None = None
    streaming: bool = False

    def __post_init__(self):
        if not callable(self.produce):
            raise TypeError("Command producer must be callable")
        if not isinstance(self.delay, (int, float)) or not math.isfinite(self.delay) or self.delay < 0:
            raise ValueError("Command delay must be finite and nonnegative")
        if self.interval is not None and (not isinstance(self.interval, (int, float)) or not math.isfinite(self.interval) or self.interval <= 0):
            raise ValueError("Tick interval must be finite and positive")
        if type(self.streaming) is not bool:
            raise TypeError("Streaming must be a Boolean")
        if self.streaming and self.interval is not None:
            raise ValueError("Stream commands cannot repeat")

    @classmethod
    def stream(cls, factory):
        """Lazily consume an async message iterable, closing it when finished.

        The factory runs on the Program's event-loop thread. It must return an
        async iterable (or await one); blocking inference belongs in an adapter.
        Program's stream_buffer bounds messages waiting for model dispatch.
        """
        return cls(factory, streaming=True)

    @classmethod
    def after(cls, seconds, message):
        return cls(lambda: message, delay=seconds)

    @classmethod
    def every(cls, seconds, produce):
        return cls(produce, delay=seconds, interval=seconds)
