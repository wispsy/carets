# Managed message streams

`Command.stream(factory)` lazily obtains an async iterable and forwards each
`Msg` through `Program`'s serialized model dispatch. The factory may also be an
async function returning the iterable. `stream_buffer=64` bounds the total
stream messages queued or currently dispatched by one Program. Producers await
capacity before requesting the next item; the source may have its own buffering.

```python
from carets import Command, KeyMsg, Program

async def changes():
    yield KeyMsg('first')
    yield KeyMsg('done')

# Model.update handles these messages; the application owns completion.
program = Program(model, renderer=renderer, stream_buffer=32)
await program.run([], stop_on_eof=False, commands=[Command.stream(changes)])
```

This fragment assumes application-provided `model` and `renderer`; the complete
runnable example is `examples/streaming.py`. A stream ending does not stop the
application or synthesize completion. Deliver an application-specific outcome
message when needed. `stop_on_eof=False` lets background work continue after an
empty/synthetic input source ends. A native parser remains active when input is
omitted. Configure a renderer for visible output.

`Program.schedule` returns the command ID used by `Program.cancel`. Cancellation
and shutdown await producer cleanup. Iterators exposing `aclose()` are closed
on exhaustion, error and cancellation. Invalid items and factory/source/close
errors become `CommandErrorMsg` with that command's ID; cancellation is not an
error message. Handle errors in the model so a failed producer does not leave a
waiting view indefinitely. Cancellation is cooperative; blocking synchronous
code inside a factory/iterator still blocks the event loop.

Synchronous `post()` keeps its existing unbounded, event-loop-thread behavior.
The stream bound does not limit input messages, timers, application state or
source-internal buffers. No thread-safe posting, frame throttling or subprocess
JSONL transport is implied. Every stream item updates the model and currently
renders a frame. For high-volume sources, choose a finite buffer and retain a
bounded display tail in the application. Future frame scheduling can coalesce
redraws while preserving all model updates.
