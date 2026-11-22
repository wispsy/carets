# Snapshot table presentation

TableModel requires Python 3.14+ and the newer Headless Spreadsheets snapshot
API. Install the pinned optional integration with
`pip install -r requirements-tables.txt` from this checkout, then install Carets.
Published Headless Spreadsheets 0.1.0 predates the snapshot API; it cannot satisfy
this adapter. The development pin stays separate from PyPI package metadata,
which cannot express a direct Git dependency. Core Carets remains dependency-free
on Python 3.10+. The adapter consumes the public immutable
Headless Spreadsheets TableSnapshot, SourceRow and SourceColumn contracts;
querying, sorting, paging, persistence and revision-checked writes stay upstream.
Use `TableSource.query(...)` or another existing source adapter to obtain pages.

TableModel is immutable and read-only. Its selection retains table/schema IDs,
row key, column ID, revision, generation and source address. `with_snapshot()`
keeps identities across reorder/resize, selects the first available item if an
identity disappears, and rejects older generations or a different table. A
caller handling edits must use the source's revision-checked edit API and then
query a new snapshot. A row position is never an edit identity.

Arrow/Page/Home/End keys navigate. Fixed-width columns and bounded row/column
windows format only visible cells; there is no second spreadsheet engine or
autowidth scan of all rows. Headless Spreadsheets formats typed scalars. Text is
clipped by grapheme cells, control sequences are removed by the common Unicode
renderer, and line breaks/tabs become spaces. Row/column selection remains
visible without color. Each snapshot has the upstream 1000-row/64-column/16000-
cell bound; request further pages from the source explicitly.
