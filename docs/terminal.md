# Explicit terminal ownership

Pass `TerminalSession(input_stream, output_stream, options=TerminalOptions(...))`
to Program's terminal argument. Construction is passive. Program starts the
session inside its cleanup scope and restores state after EOF, stop, exceptions,
async cancellation and handled interrupt/termination signals.

Raw mode, alternate screen, hidden cursor, SGR mouse reporting and bracketed paste
are independent options. Setup captures state before mutation; cleanup restores
signals, modes and raw attributes exactly once even when another cleanup fails.
Sessions run once and require exclusive process ownership while active.

An initial WindowSizeMsg and SIGWINCH updates reach the model automatically.
Applications decide how size affects their view/renderer. Interrupt/termination
handlers request graceful Program.stop; they do not invoke application behavior
or install global desktop listeners. Previous handlers are restored on shutdown.

Capabilities are conservative: redirected streams emit no terminal controls;
POSIX TTYs support raw/ANSI behavior; unsupported Windows raw/ANSI and unavailable
resize signals fall back without setup. Signal ownership requires the main thread.
SystemTerminal supports the host OS; synthetic adapters test setup, resize and
teardown without touching a real terminal. Hard process termination cannot execute
Python cleanup. Native Windows console raw-input support remains a separate scope.
