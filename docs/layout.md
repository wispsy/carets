# Layout composition

`Layout` nodes and all geometry are immutable. A leaf declares intrinsic content
size independently of its parent. Rows, columns, stacks, overlays and splits
measure children, then arrange them into a caller-owned viewport.

```python
from carets.layout import Column, Leaf, Row, Size, content, fixed

shell = Row('shell',
    Leaf('navigation', width=fixed(20)),
    Column('main', Leaf('title', height=content(), intrinsic=Size(8, 1)),
           Leaf('body'), gap=1), gap=2)
frame = shell.arrange(80, 24)
body = frame.get('body').content
zones = frame.zones()
```

Lengths use integer fixed cells, relative weights, percentages of available
space after gaps, or intrinsic content. Constraints apply to outer sizes,
including margin/padding. Weighted surplus is distributed deterministically;
maximums redistribute remaining space. Alignment controls cross-axis placement;
justification controls unused main-axis space. The root rectangle is the explicit
viewport supplied by the caller.

When minimum/fixed sizes exceed available space, bounds retain the request and
`clip` describes visible geometry. `overflow` reports clipping. Render through
those clips; do not assume an overflowing requested rectangle is visible. Empty
clipped zones are omitted. Overlay hits resolve topmost first. Node IDs must be
unique within a tree; depth and node-count limits reject accidental unbounded
composition. New component types can supply `Size` without another layout engine.
