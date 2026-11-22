"""Immutable terminal geometry and deterministic, clipped layout composition."""
from __future__ import annotations

from dataclasses import dataclass, field
import math


def _integer(value, name, *, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError(name + " must be a nonnegative integer")


@dataclass(frozen=True)
class Size:
    width: int = 0
    height: int = 0

    def __post_init__(self):
        _integer(self.width, "width"); _integer(self.height, "height")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        if type(self.x) is not int or type(self.y) is not int:
            raise TypeError("Rectangle positions must be integers")
        Size(self.width, self.height)

    def intersect(self, other):
        x, y = max(self.x, other.x), max(self.y, other.y)
        return Rect(x, y, max(0, min(self.x+self.width, other.x+other.width)-x),
                    max(0, min(self.y+self.height, other.y+other.height)-y))

    def contains(self, x, y):
        return self.x <= x < self.x+self.width and self.y <= y < self.y+self.height


@dataclass(frozen=True)
class Insets:
    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0

    def __post_init__(self):
        for name in ("top", "right", "bottom", "left"):
            _integer(getattr(self, name), name)

    def inside(self, rect):
        left, top = min(self.left, rect.width), min(self.top, rect.height)
        return Rect(rect.x+left, rect.y+top, max(0, rect.width-self.left-self.right),
                    max(0, rect.height-self.top-self.bottom))


@dataclass(frozen=True)
class Length:
    kind: str = "weight"
    value: float = 1

    def __post_init__(self):
        if self.kind not in ("fixed", "weight", "percent", "content"):
            raise ValueError("Unknown length policy")
        if type(self.value) not in (int, float) or not math.isfinite(self.value) or not 0 <= self.value <= 1000000:
            raise ValueError("Length values must be finite and nonnegative")
        if self.kind == "weight" and self.value == 0:
            raise ValueError("Weights must be positive")
        if self.kind == "percent" and self.value > 100:
            raise ValueError("Percentages must be between zero and one hundred")
        if self.kind == "fixed" and self.value != int(self.value):
            raise ValueError("Fixed lengths use integer cells")


def fixed(cells): return Length("fixed", cells)
def weighted(weight=1): return Length("weight", weight)
def percent(value): return Length("percent", value)
def content(): return Length("content", 0)


@dataclass(frozen=True)
class Constraints:
    minimum: Size = field(default_factory=Size)
    maximum_width: int | None = None
    maximum_height: int | None = None

    def __post_init__(self):
        if type(self.minimum) is not Size: raise TypeError("minimum requires Size")
        for name, minimum in (("maximum_width", self.minimum.width), ("maximum_height", self.minimum.height)):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name)
                if value < minimum: raise ValueError("Maximum must include minimum")

    def clamp(self, value, axis):
        minimum = getattr(self.minimum, axis)
        maximum = getattr(self, "maximum_"+axis)
        return max(minimum, value) if maximum is None else min(maximum, max(minimum, value))


@dataclass(frozen=True)
class Placement:
    id: str
    bounds: Rect
    content: Rect
    clip: Rect


@dataclass(frozen=True)
class LayoutResult:
    placements: tuple[Placement, ...]

    def get(self, id):
        return next(p for p in self.placements if p.id == id)

    @property
    def overflow(self):
        return any(p.bounds != p.clip for p in self.placements)

    def hit(self, x, y):
        return next((p.id for p in reversed(self.placements) if p.clip.contains(x, y)), None)

    def zones(self):
        from .zone import ZoneManager
        result = ZoneManager()
        # ZoneManager's established first-match policy receives topmost first.
        for p in reversed(self.placements):
            if not p.clip.width or not p.clip.height: continue
            result.define(p.id, p.clip.x, p.clip.y, p.clip.width, p.clip.height)
        return result


@dataclass(frozen=True)
class Layout:
    id: str
    direction: str = "leaf"
    children: tuple[Layout, ...] = ()
    intrinsic: Size = field(default_factory=Size)
    width: Length = field(default_factory=weighted)
    height: Length = field(default_factory=weighted)
    constraints: Constraints = field(default_factory=Constraints)
    padding: Insets = field(default_factory=Insets)
    margin: Insets = field(default_factory=Insets)
    gap: int = 0
    align: str = "stretch"
    justify: str = "start"

    def __post_init__(self):
        if type(self.id) is not str or not self.id or len(self.id) > 128:
            raise ValueError("Layout identities must be nonempty and bounded")
        if self.direction not in ("leaf", "row", "column", "stack"):
            raise ValueError("Unknown layout direction")
        if type(self.children) is not tuple or len(self.children) > 1024 or any(type(c) is not Layout for c in self.children):
            raise TypeError("Children require a bounded tuple of Layout nodes")
        if self.direction == "leaf" and self.children: raise ValueError("Leaves cannot contain children")
        if any(type(getattr(self, name)) is not kind for name, kind in
               (("intrinsic", Size), ("width", Length), ("height", Length), ("constraints", Constraints),
                ("padding", Insets), ("margin", Insets))): raise TypeError("Invalid layout geometry")
        _integer(self.gap, "gap")
        if self.align not in ("start", "center", "end", "stretch") or self.justify not in ("start", "center", "end"):
            raise ValueError("Unknown alignment")

    def measure(self):
        sizes = [c.measure() for c in self.children]
        if self.direction == "row":
            w, h = sum(s.width for s in sizes)+self.gap*max(0, len(sizes)-1), max((s.height for s in sizes), default=0)
        elif self.direction == "column":
            w, h = max((s.width for s in sizes), default=0), sum(s.height for s in sizes)+self.gap*max(0, len(sizes)-1)
        elif self.direction == "stack":
            w, h = max((s.width for s in sizes), default=0), max((s.height for s in sizes), default=0)
        else: w, h = self.intrinsic.width, self.intrinsic.height
        values = []
        for axis, measured, extra in (("width", w, self.padding.left+self.padding.right+self.margin.left+self.margin.right),
                                      ("height", h, self.padding.top+self.padding.bottom+self.margin.top+self.margin.bottom)):
            length = getattr(self, axis)
            value = int(length.value) if length.kind == "fixed" else measured+extra
            values.append(self.constraints.clamp(value, axis))
        return Size(*values)

    def arrange(self, width, height, *, x=0, y=0):
        outer = Rect(x, y, width, height); seen = set(); measured = {}
        def check(node, depth):
            if depth > 64 or len(seen) >= 4096 or node.id in seen:
                raise ValueError("Layout identities must be unique within a bounded tree")
            seen.add(node.id)
            for child in node.children: check(child, depth+1)
            measured[node.id] = node.measure()
        check(self, 0)
        placed = []
        def basis(node, axis, available):
            length = getattr(node, axis)
            value = {"fixed": lambda: int(length.value), "percent": lambda: math.floor(available*length.value/100),
                     "content": lambda: getattr(measured[node.id], axis), "weight": lambda: available}[length.kind]()
            return node.constraints.clamp(value, axis)
        def align_offset(extra, alignment):
            return max(0, extra)//2 if alignment == "center" else max(0, extra) if alignment == "end" else 0
        def visit(node, bounds, clip):
            visible = bounds.intersect(clip)
            inside = node.padding.inside(node.margin.inside(bounds))
            placed.append(Placement(node.id, bounds, inside, visible))
            child_clip = inside.intersect(visible)
            if node.direction == "stack":
                for child in node.children:
                    w, h = basis(child, "width", inside.width), basis(child, "height", inside.height)
                    visit(child, Rect(inside.x+align_offset(inside.width-w, node.align),
                                      inside.y+align_offset(inside.height-h, node.align), w, h), child_clip)
            elif node.children:
                axis, cross = ("width", "height") if node.direction == "row" else ("height", "width")
                available = max(0, getattr(inside, axis)-node.gap*(len(node.children)-1))
                allocations = [c.constraints.clamp(0, axis) if getattr(c, axis).kind == "weight" else basis(c, axis, available) for c in node.children]
                remaining = max(0, available-sum(allocations))
                active = [i for i,c in enumerate(node.children) if getattr(c, axis).kind == "weight"]
                while remaining and active:
                    total = sum(getattr(node.children[i], axis).value for i in active)
                    shares = {i: remaining*getattr(node.children[i], axis).value/total for i in active}
                    extras = {i: math.floor(shares[i]) for i in active}
                    for i in sorted(active, key=lambda i: (-(shares[i]-extras[i]), i))[:remaining-sum(extras.values())]: extras[i] += 1
                    used = 0
                    for i in active:
                        new = node.children[i].constraints.clamp(allocations[i]+extras[i], axis)
                        used += new-allocations[i]; allocations[i] = new
                    remaining -= used
                    active = [i for i in active if getattr(node.children[i].constraints, "maximum_"+axis) is None or allocations[i] < getattr(node.children[i].constraints, "maximum_"+axis)]
                    if not used: break
                cursor = align_offset(available-sum(allocations), node.justify)
                for child, allocation in zip(node.children, allocations):
                    cross_size = basis(child, cross, getattr(inside, cross))
                    cross_offset = align_offset(getattr(inside, cross)-cross_size, node.align)
                    rect = Rect(inside.x+cursor, inside.y+cross_offset, allocation, cross_size) if axis == "width" else Rect(inside.x+cross_offset, inside.y+cursor, cross_size, allocation)
                    visit(child, rect, child_clip); cursor += allocation+node.gap
        visit(self, outer, outer)
        return LayoutResult(tuple(placed))


def Leaf(id, **options): return Layout(id, **options)
def Row(id, *children, **options): return Layout(id, "row", tuple(children), **options)
def Column(id, *children, **options): return Layout(id, "column", tuple(children), **options)
def Stack(id, *children, **options): return Layout(id, "stack", tuple(children), **options)
def Overlay(id, base, overlay, **options): return Stack(id, base, overlay, **options)
def Split(id, first, second, *, vertical=False, **options):
    return (Column if vertical else Row)(id, first, second, **options)
