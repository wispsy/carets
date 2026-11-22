# Application composition

`Theme` supplies text, muted, accent, focus, disabled, success, warning and error
Style roles plus spacing. It introduces no renderer, dependencies or global
state. Replace tokens for a different palette; CellDiffRenderer adapts colors
to the terminal's supported depth. Every state also needs text or a marker.

`AppShell.frame(width, height, ...)` arranges header, optional navigation, body,
footer and an optional opaque modal through Layout and ScreenBuffer. It returns
both the buffer and layout so callers can bind zones. Unicode text clips at
whole grapheme cells. The sidebar hides below the configurable breakpoint;
the current section remains in the header. Zero and tiny viewports are valid.
Frames are bounded to 4096 by 1024 cells; caller-owned content is already finite.
ShellCommand describes visible shortcuts, including disabled states. The
application maps keys to trusted actions and owns command lifetime.

The shell is presentation only. Register controls in one FocusManager. Give a
dialog its own scope and call `activate(scope, modal=True)`, then `dismiss()` to
restore focus. Bind focus to ComponentState. Put status codes and errors in
text; colors supplement them. Domain models, storage, provider selection and
authorization belong to the consuming application.

`examples/gallery.py` and `examples/queue.py` are independent models sharing
these primitives. Both run in one Program and resize without a nested terminal.
Hypnosis composes the same shell for harness jobs and measurements. Native raw
terminal support remains qualified on POSIX; Windows can use application-owned
message sources. See compatibility and Unicode policy docs for terminal limits.
