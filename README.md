# carets

Read the [API reference](docs/api.md), [application tutorials](docs/tutorials.md),
[testing guide](docs/testing.md) and [compatibility matrix](docs/compatibility.md)
for application composition. See [components](docs/components.md),
[themes and shells](docs/design-system.md), [layout](docs/layout.md),
[optional tables](docs/tables.md) and [release notes](docs/releases.md).

Carets 0.2 is a dependency-free Python 3.10+ asyncio terminal UI toolkit.
The shared component foundation is ready to grow; APIs may change before 1.0.

Carets provides incremental ANSI input parsing, immutable components,
ANSI-aware styling, named zones, forms, and a cell-diffing renderer with DEC
synchronized output.

```bash
pip install carets==0.2.0
```

One Program owns input, commands, frames and terminal cleanup. Application
models can be mutable or return new immutable models from `update`. Theme and
AppShell compose shared regions; component protocols and adapters keep widgets
independent of terminal ownership. The widget inventory in issue #7 remains an
open growth backlog. The optional snapshot table adapter needs the separately
documented development version of Headless Spreadsheets on Python 3.14+.

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
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests examples
```

Managed async message producers use `Command.stream(factory)`. See the
[streaming guide](docs/streaming.md) and `examples/streaming.py` for bounded live
updates, cooperative cancellation and cleanup.
