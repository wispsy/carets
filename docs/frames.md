# Frame scheduling and immutable models

`Program(..., frame_interval=1/30)` serializes every model update while painting
at most once per interval. It keeps only one frame wakeup, retains the latest
view and flushes a dirty final frame before renderer/terminal cleanup. Input and
cancellation remain messages; stream backpressure still uses `stream_buffer`.
The default zero interval preserves immediate rendering.

Tests inject a monotonic clock and its matching async sleep. Frame coalescing
never coalesces model messages, edits, keys or token events. Applications may
explicitly keep a bounded display tail; that is separate from frame scheduling.

A model may mutate itself, return commands, or return a new object implementing
`update`/`view`. Program adopts immutable replacement models. Existing controls
can therefore serve directly as root models. Program owns an optional renderer's
`close()` cleanup (including awaitables and returned terminal-reset text), before
restoring the terminal resource. Native sources and commands settle first.
