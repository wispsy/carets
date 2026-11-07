# Commands and application lifetime

`Program` keeps the existing `update(message)` / `view()` model protocol. An update
may return a Command or a sequence of Commands. A producer returns one Msg or None,
or awaits either result. Synchronous producers run on the application thread; async
producers should await blocking work. Nothing schedules itself during import.

`Command.after(seconds, message)` delays one delivery. `Command.every(seconds,
producer)` ticks after each positive interval. `program.schedule(command)` returns
a deterministic invocation-local ID; `program.cancel(id)` cancels that task.
Failures arrive as CommandErrorMsg(id, error), allowing the model to present or
stop explicitly. Input and command messages are dispatched serially.

Pass initial commands to `await program.run(messages, commands=[...])`. Default
EOF stops the application and cancels outstanding commands. Set stop_on_eof=False
for applications kept alive by commands/external messages, then call program.stop.
Stop wakes a blocked message loop. Cancellation propagates through the producer.
post(message) is for the owning event-loop thread; no global desktop input exists.

Register sync/async resource callbacks with add_cleanup. Shutdown cancels and
awaits input/commands before invoking every cleanup in reverse order exactly once.
Cleanup failure cannot skip other resources or replace an existing application
failure. Program instances run once; construct a fresh one for another session.
The sleep callable is injectable for deterministic clocks and tests.
