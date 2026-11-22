# Authoring components

`carets.components.Component` is a structural protocol: immutable `state`,
`update(message)`, intrinsic `measure() -> Size`, `view() -> str`, and a textual
`accessibility()` description. A component never creates a Program, terminal,
renderer, event loop or background task. The application owns those resources.
Return a new value from updates and let the application interpret activation
counters or selected values as domain actions. Measurement includes terminal
cell widths; layout and the shell own available space and clipping.

`ComponentState` carries stable identity, accessible label, focus, disabled and
read-only flags. Register the same identity with `FocusManager`; bind its focus
into state before rendering. Disabled controls cannot act. Read-only controls
remain focusable; list/viewport navigation is allowed while input edits and
button/checkbox actions are blocked. State markers and percentages remain
visible without color. These are terminal text conventions, not a claim of a
platform screen-reader accessibility API.

Initial controls are Label, Button, Checkbox and Progress. `ComponentAdapter`
adds these contracts to TextInput, ListModel, Viewport and Spinner without
replacing their update/view APIs. TextInput retains character-offset cursors
but normalizes movement and deletion to Unicode grapheme boundaries. Animation
still needs an application-owned tick. Key release does not activate controls.

The widget inventory in [issue #7](https://github.com/wispsy/carets/issues/7)
remains the growth backlog. New components should test immutable updates,
disabled/read-only/focus behavior, textual state, Unicode measurement, bounded
layout, and cancellation when the application starts work. Existing APIs remain
usable without adopting the protocol all at once.
