# Carets implementation plan

## Status and scope

Carets is an experimental, dependency-free Python 3.10+ asyncio TUI toolkit.
Version `0.1.0` establishes the current prototype API and the engineering
baseline for building complete terminal applications. It is not yet a
stability promise: public APIs may change while the layout, focus, command,
and renderer subsystems mature.

The project is intentionally split into layers:

1. **Runtime** — messages, commands, lifecycle, timers, shutdown, and signals.
2. **Terminal I/O** — raw mode, capabilities, input protocols, resize, and
   terminal restoration.
3. **Rendering and styling** — cells, Unicode width, colors, cursor control,
   clipping, layers, and synchronized output.
4. **Composition** — layout constraints, zones, focus, event routing, and
   themes.
5. **Components** — reusable immutable widgets that implement `update(msg)`
   and `view()`.
6. **Application services** — forms, configuration, logging, testing helpers,
   and packaging.

## Milestones

### M0 — Prototype baseline (`v0.1.0`)

- Publish the existing runtime, parser, renderer, style, zone, form, and
  component modules.
- Keep the package dependency-free at runtime.
- Add basic examples, architecture documentation, CI, and a release workflow.
- Clearly mark the API as experimental.

### M1 — Reliable application lifecycle

- Add a command abstraction that can return messages asynchronously.
- Add timers, ticks, cancellation, and task error propagation.
- Add terminal raw mode with guaranteed restoration on normal exit, exceptions,
  and signals.
- Add `WindowSizeMsg` delivery from `SIGWINCH` and terminal queries.
- Add runtime options for alternate screen, cursor visibility, mouse reporting,
  bracketed paste, and keyboard protocols.
- Add deterministic lifecycle tests with fake streams and clocks.

### M2 — Layout and interaction foundation

- Define immutable layout constraints and measured layout results.
- Implement rows, columns, stacks, overlays, splits, padding, margins, gaps,
  alignment, min/max sizes, and overflow policies.
- Add focus scopes, tab navigation, directional navigation, modal focus, and
  disabled/read-only state.
- Route events through capture, target, and bubble phases.
- Integrate zones with component IDs and hit testing.

### M3 — Production renderer and terminal support

- Replace character-count assumptions with grapheme-aware cell measurement.
- Handle wide characters, combining marks, zero-width joiners, and clipping.
- Implement 16-color, 256-color, truecolor, and terminal capability fallback.
- Add cursor placement, cursor shape, visibility, and restoration.
- Add styled cell composition, layers, overlays, dirty regions, and full redraw
  fallback.
- Expand parser coverage for function keys, modifiers, SS3, Kitty keyboard,
  mouse motion, drag, wheel, focus, and bracketed paste.

### M4 — Core widget library

- Add labels, rich text, buttons, checkboxes, radio groups, select menus,
  command palettes, tables, trees, tabs, progress bars, dialogs, notifications,
  text areas, file pickers, and split panes.
- Standardize component sizing, focus behavior, key bindings, disabled states,
  accessibility labels, and immutable update semantics.
- Provide a theme object and reusable style tokens.

### M5 — Forms and application services

- Add typed field values and conversion.
- Add synchronous and asynchronous validators, cross-field validation,
  conditional fields, defaults, submit/cancel states, and error summaries.
- Add configuration loading, application context, structured logging, and
  safe crash output outside the rendered terminal.
- Add plugin registration without making third-party packages mandatory.

### M6 — Testing, compatibility, and documentation

- Add a `TestProgram`, fake terminal, deterministic clock, snapshot renderer,
  layout assertions, and event-sequence helpers.
- Add parser fuzz/property tests and terminal resize integration tests.
- Document supported terminals and capability fallbacks.
- Add tutorials for a counter, form, dashboard, and multi-pane application.
- Generate an API reference and publish release notes for each version.

## Definition of done for a stable 1.0

- Runtime cleanup is guaranteed even when application code raises.
- Layout and focus behavior are deterministic under resize.
- Renderer output is correct for common Unicode and color combinations.
- Core widgets share consistent interaction and accessibility conventions.
- Applications can be tested without a real terminal.
- Compatibility and breaking-change policy are documented.
- CI covers supported Python versions and representative terminal behavior.

## Naming decisions

The API uses descriptive Python names rather than mirroring another toolkit's
namespace. `Program`, `Msg`, `Style`, and `Form` express concepts directly;
`CellDiffRenderer`, `ZoneManager`, and `ListModel` make implementation roles
explicit. Future additions should preserve the `update(msg)` / `view()`
protocol and immutable state style for components.

## Delivery policy

Each milestone should land as small, reviewable issues with tests and focused
documentation. Breaking changes should be called out in release notes. The
package remains dependency-free unless an optional integration is explicitly
isolated behind an extra.
