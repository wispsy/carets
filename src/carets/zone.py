# Named terminal regions for coordinate-aware components and mouse handling.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneInfo:
    name: str
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


class ZoneManager:
    def __init__(self) -> None:
        self._zones: dict[str, ZoneInfo] = {}

    def define(self, name: str, x: int, y: int, width: int, height: int) -> ZoneInfo:
        zone = ZoneInfo(name, x, y, width, height)
        self._zones[name] = zone
        return zone

    def get(self, name: str) -> ZoneInfo | None:
        return self._zones.get(name)

    def hit(self, x: int, y: int) -> ZoneInfo | None:
        return next((zone for zone in self._zones.values() if zone.contains(x, y)), None)

    def clear(self) -> None:
        self._zones.clear()

    def __iter__(self):
        return iter(self._zones.values())


zones = ZoneManager()

