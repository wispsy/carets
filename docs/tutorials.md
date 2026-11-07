# Application tutorials

The executable [models](../examples/tutorials.py) are tested in CI with TestProgram.

1. **Counter:** update a count for a KeyMsg and return the current value from view.
   `await test.send_bytes(b"++")` produces `Count: 2`.
2. **Form:** declare TypedField("count", "Count", int) in a Group/Form. An input
   message calls form.update; Enter calls submit. Render display/status and use
   result.values only after valid. See [forms/services](forms-services.md).
3. **Dashboard:** schedule Dashboard.start(), a periodic Command. It emits tick
   messages while input remains live. Advance ManualClock in tests, and cancel the
   returned command ID before shutdown. See [lifecycle](lifecycle.md).
4. **Multiple panes:** register left/right component IDs with FocusManager and
   zones. Recompute rectangles on WindowSizeMsg, route keyboard/mouse input, and
   include focus.indicator in the view. Tab changes panes. assert_layout checks
   resize geometry; [focus](focus.md) explains modal scopes and event phases.

For rendering, Style composes borders/padding/colors and CellDiffRenderer emits
screen differences. Keep layout rectangles and view output consistent; the simple
manual two-pane example does not claim a constraint solver. Pass an explicit
TerminalSession to Program for real POSIX terminal ownership. A reusable library
model should not read stdin, install signals or start Program during import.
