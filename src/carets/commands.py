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

    def __post_init__(self):
        if not callable(self.produce):
            raise TypeError("Command producer must be callable")
        if not isinstance(self.delay, (int, float)) or not math.isfinite(self.delay) or self.delay < 0:
            raise ValueError("Command delay must be finite and nonnegative")
        if self.interval is not None and (not isinstance(self.interval, (int, float)) or not math.isfinite(self.interval) or self.interval <= 0):
            raise ValueError("Tick interval must be finite and positive")

    @classmethod
    def after(cls, seconds, message):
        return cls(lambda: message, delay=seconds)

    @classmethod
    def every(cls, seconds, produce):
        return cls(produce, delay=seconds, interval=seconds)
