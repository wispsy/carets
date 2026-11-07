# carets

Read the [API reference](docs/api.md), [application tutorials](docs/tutorials.md),
[testing guide](docs/testing.md) and [compatibility matrix](docs/compatibility.md)
for the source-qualified application foundation. [Release notes](docs/releases.md)
distinguish this source work from the published baseline.

> **Prototype / experimental:** Carets is an early dependency-free Python
> 3.10+ asyncio terminal UI toolkit. Public APIs may change before 1.0.

Carets provides incremental ANSI input parsing, immutable components,
ANSI-aware styling, named zones, forms, and a cell-diffing renderer with DEC
synchronized output.

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

The longer-term roadmap is documented in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests examples
```
