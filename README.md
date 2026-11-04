# carets

Carets is a dependency-free Python 3.10+ asyncio terminal UI toolkit inspired
by Bubble Tea and Lip Gloss. It provides incremental ANSI input parsing,
immutable components, ANSI-aware styling, named zones, forms, and a
cell-diffing renderer with DEC synchronized output.

```python
import asyncio
from carets import KeyMsg, Program
from carets.components import TextInput


async def main():
    model = TextInput(placeholder="Type here")
    await Program(model).run()


asyncio.run(main())
```

The package lives under `src/carets`; runnable Python files belong under
`examples/`. See [the architecture guide](docs/architecture.md) for the
module boundaries and naming rationale.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests examples
```

