# Input protocols and ownership

The incremental parser accepts UTF-8, CSI/SS3 arrows and function keys, xterm
modifiers/modifyOtherKeys, Kitty key events, focus reports and SGR mouse press,
release, drag, motion and wheel reports. `KeyMsg.action` is press/repeat/release;
existing construction defaults to press. Modifier sets preserve shift/alt/ctrl,
super/hyper/meta and Kitty lock modifiers. Built-in controls ignore key releases.

`TerminalOptions(keyboard_protocol='auto')` queries Kitty support and pushes
configured enhancement flags only after a response. Explicit `kitty` mode pushes
immediately; `legacy` remains the default. Modes are popped exactly once on
cleanup. Focus and mouse-motion modes are independent explicit options. This
follows the [Kitty keyboard protocol](https://sw.kovidgoyal.net/kitty/keyboard-protocol/).
Protocol support never assumes a particular terminal merely from its name.

CSI/string recovery is bounded; unknown replies become structural `ProtocolMsg`
values without copying their contents into model text. Paste data is held until
its terminator, bounded by UTF-8 bytes. Overflow or missing termination is exposed
with `KeyMsg.truncated`; it does not turn pasted escapes into keyboard commands.
A single Escape is resolved by a configurable event-loop timeout, or explicitly
with `flush_escape()`/`finish()` in synchronous parsing. Incomplete UTF-8 is retained
between byte chunks, and finish decodes its final replacement if needed.

Native descriptor input remains POSIX-qualified. Windows runs parsing/headless
fixtures; native Windows console input is still a separate compatibility task.
