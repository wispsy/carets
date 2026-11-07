# Incremental terminal input parsing and asyncio file-descriptor integration.

from __future__ import annotations

import asyncio
import codecs
import re
from collections.abc import AsyncIterator
from typing import Any

from .runtime import KeyMsg, MouseMsg


_SGR_MOUSE = re.compile(r"\x1b\[<(?P<code>\d+);(?P<x>\d+);(?P<y>\d+)(?P<final>[mM])")


class AnsiInputParser(AsyncIterator[KeyMsg | MouseMsg]):
    """Parse UTF-8 bytes and common terminal escape sequences incrementally."""

    def __init__(self, stream: Any | None = None, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.stream = stream
        self.loop = loop
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._buffer = ""
        self._events: asyncio.Queue[KeyMsg | MouseMsg | None] = asyncio.Queue()
        self._reader_registered = False

    def start(self) -> None:
        if self.stream is None or self._reader_registered:
            return
        loop = self.loop or asyncio.get_running_loop()
        fileno = self.stream.fileno()
        loop.add_reader(fileno, self._on_readable)
        self._reader_registered = True

    def close(self) -> None:
        if self.stream is None or not self._reader_registered:
            return
        loop = self.loop or asyncio.get_event_loop()
        loop.remove_reader(self.stream.fileno())
        self._reader_registered = False
        self._events.put_nowait(None)

    async def __anext__(self) -> KeyMsg | MouseMsg:
        if self.stream is not None and not self._reader_registered:
            self.start()
        event = await self._events.get()
        if event is None:
            raise StopAsyncIteration
        return event

    def _on_readable(self) -> None:
        data = self.stream.read(4096)
        if not data:
            self.close()
            return
        self.feed(data)

    def feed(self, data: bytes | str) -> list[KeyMsg | MouseMsg]:
        """Feed a chunk and return all events that can be decoded from it."""
        text = data if isinstance(data, str) else self._decoder.decode(data, final=False)
        self._buffer += text
        events = self._parse()
        for event in events:
            self._events.put_nowait(event)
        return events

    def finish(self) -> list[KeyMsg | MouseMsg]:
        self._buffer += self._decoder.decode(b"", final=True)
        events = self._parse(final=True)
        for event in events:
            self._events.put_nowait(event)
        self._events.put_nowait(None)
        return events

    def _parse(self, *, final: bool = False) -> list[KeyMsg | MouseMsg]:
        events: list[KeyMsg | MouseMsg] = []
        while self._buffer:
            if self._buffer.startswith("\x1b[200~"):
                end = self._buffer.find("\x1b[201~", 6)
                if end < 0:
                    if final:
                        events.append(KeyMsg("paste", self._buffer[6:]))
                        self._buffer = ""
                    break
                events.append(KeyMsg("paste", self._buffer[6:end]))
                self._buffer = self._buffer[end + 6 :]
                continue
            mouse = _SGR_MOUSE.match(self._buffer)
            if mouse:
                code = int(mouse.group("code"))
                modifiers = frozenset(
                    name for bit, name in ((4, "shift"), (8, "alt"), (16, "ctrl")) if code & bit
                )
                button_code = code & 3
                button = ("left", "middle", "right", "none")[button_code]
                action = "release" if mouse.group("final") == "m" else "press"
                if code & 64:
                    action = "scroll"
                    button = "down" if button_code == 1 else "up"
                events.append(MouseMsg(int(mouse.group("x")) - 1, int(mouse.group("y")) - 1, button, action, modifiers))
                self._buffer = self._buffer[mouse.end() :]
                continue
            if self._buffer.startswith("\x1b["):
                match = re.match(r"\x1b\[(?P<code>[0-9;]*)(?P<final>[A-Za-z~])", self._buffer)
                if not match:
                    if not final:
                        break
                    self._buffer = self._buffer[1:]
                    events.append(KeyMsg("escape"))
                    continue
                code, final_char = match.group("code"), match.group("final")
                keys = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end", "Z": "backtab"}
                key = keys.get(final_char)
                if final_char == "~":
                    key = {"1": "home", "3": "delete", "4": "end", "5": "pageup", "6": "pagedown", "7": "home", "8": "end"}.get(code)
                events.append(KeyMsg(key or f"csi:{code}{final_char}"))
                self._buffer = self._buffer[match.end() :]
                continue
            if self._buffer.startswith("\x1b"):
                if len(self._buffer) == 1 and not final:
                    break
                if len(self._buffer) > 1 and self._buffer[1] != "[":
                    events.append(KeyMsg(self._buffer[1], modifiers=frozenset({"alt"})))
                    self._buffer = self._buffer[2:]
                else:
                    events.append(KeyMsg("escape"))
                    self._buffer = self._buffer[1:]
                continue
            char = self._buffer[0]
            self._buffer = self._buffer[1:]
            control = {"\r": "enter", "\n": "enter", "\x7f": "backspace", "\t": "tab", "\x03": "ctrl-c"}
            events.append(KeyMsg(control.get(char, char), None if char in control else char))
        return events

