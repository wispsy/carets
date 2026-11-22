"""Read-only terminal presentation of public Headless Spreadsheets snapshots."""
from dataclasses import dataclass, replace

from ..layout import Size
from ..runtime import KeyMsg
from ..unicode import clip_text, visual_width
from .base import ComponentState


@dataclass(frozen=True)
class TableSelection:
    table_id: str
    schema_version: str
    row_key: str
    column_id: str
    revision: str | None
    generation: int
    source_address: str


@dataclass(frozen=True)
class TableModel:
    snapshot: object
    width: int = 80
    height: int = 12
    column_width: int = 16
    selected_key: str | None = None
    selected_column: str | None = None
    row_offset: int = 0
    column_offset: int = 0
    state: ComponentState = ComponentState("table", "Table", focused=True, read_only=True)

    def __post_init__(self):
        from headless_spreadsheets import TableSnapshot
        if not isinstance(self.snapshot, TableSnapshot):
            raise TypeError("Use a public TableSnapshot from the tables extra")
        Size(self.width, self.height)
        if self.width > 4096 or self.height > 1024 or type(self.column_width) is not int or not 3 <= self.column_width <= 256:
            raise ValueError("Invalid bounded table viewport")
        if any(type(v) is not int or v < 0 for v in (self.row_offset, self.column_offset)):
            raise ValueError("Offsets must be nonnegative integers")
        rows, columns = self.snapshot.rows, self.snapshot.columns
        keys, ids = [row.key for row in rows], [column.id for column in columns]
        key = self.selected_key if self.selected_key in keys else (keys[0] if keys else None)
        column = self.selected_column if self.selected_column in ids else (ids[0] if ids else None)
        object.__setattr__(self, "selected_key", key)
        object.__setattr__(self, "selected_column", column)
        room = max(1, self.height-2)
        index = keys.index(key) if key is not None else 0
        offset = max(min(self.row_offset, index), index-room+1)
        object.__setattr__(self, "row_offset", min(offset, max(0, len(rows)-room)))
        count = max(1, (max(0, self.width-2)+1)//(self.column_width+1))
        ci = ids.index(column) if column is not None else 0
        object.__setattr__(self, "column_offset", max(min(self.column_offset, ci), ci-count+1))

    @property
    def selection(self):
        if self.selected_key is None or self.selected_column is None:
            return None
        row = next(row for row in self.snapshot.rows if row.key == self.selected_key)
        index = next(i for i, column in enumerate(self.snapshot.columns) if column.id == self.selected_column)
        return TableSelection(self.snapshot.table_id, self.snapshot.schema_version, row.key,
                              self.selected_column, row.revision, self.snapshot.generation, row.source_addresses[index])

    def with_snapshot(self, snapshot):
        if snapshot.table_id != self.snapshot.table_id:
            raise ValueError("A different table needs an explicit new TableModel")
        if snapshot.generation < self.snapshot.generation:
            raise ValueError("Cannot apply an older snapshot generation")
        return replace(self, snapshot=snapshot)

    def update(self, message):
        if not self.state.focused or self.state.disabled or not isinstance(message, KeyMsg) or message.action == "release":
            return self
        keys = [row.key for row in self.snapshot.rows]
        ids = [column.id for column in self.snapshot.columns]
        if message.key in ("up", "down", "pageup", "pagedown", "home", "end") and keys:
            index = keys.index(self.selected_key)
            delta = {"up": -1, "down": 1, "pageup": -max(1, self.height-2), "pagedown": max(1, self.height-2), "home": -len(keys), "end": len(keys)}[message.key]
            return replace(self, selected_key=keys[max(0, min(index+delta, len(keys)-1))])
        if message.key in ("left", "right") and ids:
            index = ids.index(self.selected_column)
            return replace(self, selected_column=ids[max(0, min(index+(-1 if message.key == "left" else 1), len(ids)-1))])
        return self

    def measure(self):
        return Size(self.width, self.height)

    def accessibility(self):
        selection = self.selection
        return self.state.describe()+" | read only | "+(f"row {selection.row_key}, column {selection.column_id}" if selection else "empty")

    def view(self):
        from headless_spreadsheets.serialization import scalar_text
        if not self.width or not self.height:
            return ""
        columns, room, used = [], max(0, self.width-2), 0
        for index in range(self.column_offset, len(self.snapshot.columns)):
            width = min(self.column_width, room-used)
            if width <= 0:
                break
            columns.append((index, width))
            used += width+1
        def field(text, width):
            text = clip_text(text.replace("\n", " ").replace("\r", " ").replace("\t", " "), width)
            return text+" "*max(0, width-visual_width(text))
        header = "  "+" ".join(field((">" if c.id == self.selected_column else "")+c.label, width) for i, width in columns for c in (self.snapshot.columns[i],))
        lines = [clip_text(header, self.width)]
        for row in self.snapshot.rows[self.row_offset:self.row_offset+max(0, self.height-2)]:
            text = ("> " if row.key == self.selected_key else "  ")+" ".join(field(scalar_text(row.cells[i].value), width) for i, width in columns)
            lines.append(clip_text(text, self.width))
        if self.height > 1:
            lines.append(clip_text(self.accessibility(), self.width))
        return "\n".join(lines[:self.height])
