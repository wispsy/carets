# Architecture

Carets is a small, dependency-free terminal UI toolkit built around immutable
component state and an asyncio event loop.

* `runtime.py` defines messages and `Program`, which applies updates and asks a
  renderer to draw the model.
* `input.py` turns incremental UTF-8 and ANSI terminal bytes into key and mouse
  messages. It uses `loop.add_reader` rather than a thread.
* `renderer.py` keeps a cell grid and emits only changed cells inside DEC mode
  2026 synchronized output.
* `style.py` provides ANSI-safe width/truncation and composable styling.
* `zone.py` stores named rectangles used to map terminal coordinates to UI
  regions.
* `components/` contains immutable `update`/`view` building blocks.
* `huh.py` contains declarative form fields and validation schemas.

The names intentionally describe the Python API rather than copying the
Bubble Tea or Lip Gloss namespaces. `Program`, `Msg`, `Style`, and `Form` are
familiar concepts, while `ZoneManager`, `CellDiffRenderer`, and `ListModel`
make their responsibilities explicit.

