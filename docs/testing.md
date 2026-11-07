# Reproducible terminal fixtures

```python
from carets import KeyMsg
from carets.testing import TestProgram

async with TestProgram(model) as test:
    await test.send(KeyMsg("+", "+"))
    test.assert_snapshot("Count: 1")
    await test.resize(60, 20)
    test.assert_fits(60, 20)
```

TestProgram runs the real Program with a fake terminal and a SnapshotRenderer.
send_bytes exercises the real ANSI parser. resize drives the registered resize
handler. assert_layout(zones, width, height) checks zone bounds. Snapshots capture
plain model views independently of screen-diff escape sequences.

ManualClock.sleep replaces physical time. Schedule a Command, await test.settle(),
then advance(seconds) to wake elapsed delays/ticks. Time jumps wake currently due
sleepers; periodic producers schedule their next delay when they run, so advance
one desired tick boundary at a time. settle drains currently queued deliveries;
wait_for(predicate) permits a bounded number of event-loop turns for async work.
No fixture claims to accelerate arbitrary external I/O.

A reproducer consists of the model, initial state, exact send/send_bytes sequence,
clock advances, resizes and expected frame. Parser property tests record their
random seed and compare whole-input/chunked decoding. The tutorials are exercised
through this same harness; no physical terminal is required.
