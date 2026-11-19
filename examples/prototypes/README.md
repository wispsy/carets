# Terminal prototypes

The `seed/` directory preserves the original local project and ten standalone
terminal experiments, byte for byte. `source-sha256.json` records the source
inventory. These files predate the maintained package; run individual scripts
explicitly on POSIX rather than installing the nested project or importing its
legacy `__init__.py`. Terminal demos take over the current terminal.

The supported package in `src/carets/` supplies the extracted implementations:

| Prototype | Maintained surface |
| --- | --- |
| `main.py` | `Program`, messages, commands and terminal lifecycle |
| `pylipgloss.py` | `Style`, borders, visual measurement and layout helpers |
| `bubble_input.py`, `bubble_paste_resize.py` | `AnsiInputParser`, paste/resize messages |
| `bubble_cell_renderer.py` | `ScreenBuffer`, `CellDiffRenderer` |
| `bubble_zones.py`, `bubble_modal.py` | Zones, focus scopes and application composition |
| `bubbles_components.py` | Text input and viewport components |
| `bubble_list_spinner.py` | List and spinner components |
| `huh_form.py` | Typed forms and fields |

The prototypes embed independent runtimes and message classes. New applications
use the maintained public API and its lifecycle/terminal tests. First-class
stream commands are developed on that public API, separately from this source
preservation. See the package tutorials and streaming guide for runnable current
examples.
