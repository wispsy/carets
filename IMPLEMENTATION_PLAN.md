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

## Application completion and Carets v0.2.0 — 22 November 2026

Owner-selected scope: complete the Hypnosis application portion of Cohesion Block B
and Carets foundations leading to #7. Ollama remains deferred. Version 0.2.0 is a
component-library foundation; #7 remains the growing widget backlog. Release and
publication are explicitly authorized after verification.

### Delivery order and acceptance

1. Carets #3: immutable size/constraint/rect/layout nodes, rows, columns, stacks,
   overlays/splits, fixed/weighted/percentage/content sizing, limits, padding,
   margins, gaps/alignment and bounded clipping. Content measurement does not
   depend on the parent. Test nested resize, deterministic allocation, shortage,
   zero dimensions and identity-derived zones.
2. Carets #5: one grapheme/width/clipping path shared by style, cells and layout;
   retain dependency-free core with pinned Unicode property data and conformance
   fixtures. Explicit terminal-width policy covers emoji/ZWJ, combining text,
   flags, wide cells and ambiguous width. Add color fallback, cursor ownership,
   layer composition, resize/full redraw and immutable previous-frame snapshots.
3. Carets #6: incremental CSI/SS3/function/modifier keys, explicit Kitty protocol
   negotiation/events, focus reports, complete SGR mouse actions and bounded
   paste/malformed input. Preserve fragmented UTF-8 and subsequent input. Terminal
   modes are opted into, owned and restored by the existing session.
4. CARET-FRAME-01: optional bounded frame scheduling with serialized lossless
   updates, deterministic clock tests, responsive input and final flush; immediate
   rendering remains the default.
5. CARET-DS-01/#7 foundation: shared immutable component sizing/state/accessibility
   contracts, theme roles/spacing, reusable shell regions and initial controls.
   Adapt existing controls rather than creating another rendering/focus lifecycle.
   Demonstrate Hypnosis and an independent dashboard under narrow/Unicode/modal
   conditions. Keep the complete future widget list open in #7.
6. CARET-TABLE-01: bounded read-only table viewport over public Headless Spreadsheets
   snapshots, stable source/row/column/revision identity, keyboard selection and
   virtualization. Storage and revision-checked edits stay in source adapters.
7. HYP-TOOLS-01: selected Hidden Moves catalog, typed requests, application-owned
   authority, finite arguments/results, structural receipts and explicit uncertain
   effects/cancellation. Never reimplement schema dispatch or activate providers
   from retrieved text.
8. HYP-CONTEXT-01: explicit Workspace selections and trusted instruction inputs,
   bounded UTF-8 bytes and caller tokenizer budgets, source/hash/truncation records,
   stale-source handling and held-out retrieval fixtures. Reuse Workspace and Parse
   MD; private context stays out of structural receipts.
9. HYP-VERIFY-01: caller-selected real verifier outcomes, finite repair attempts and
   shared time/output/tool authority. Cover pass, repaired pass, exhausted limits,
   verifier errors and cancellation. Keep workspace diff/provenance references
   inspectable without automatically executing generated code.
10. HYP-OPT-01: deterministic finite configuration trials and immutable task/provider/
    config identities, held-out regression gates and explicit candidate selection.
    Reuse Backpack receipts; no implicit weight training or automatic promotion.
11. HYP-ORCH-01: explicit role/dependency DAGs, admission and shared resource/time/
    output budgets with existing func_seq seams. Sequential scheduling by default;
    cancellation, blocked dependents and model resource serialization are explicit.
12. Integrate the same application services into CLI and Carets, with job/tool/context/
    verification/trial views. Keep terminal output bounded, use shared shell/theme/
    table components, preserve one terminal owner and keep JSON stdout separate.
13. Finish installed app-family qualification and public source pins. Run focused
    tests for each change, source and wheel checks, Linux/macOS/Windows headless
    checks and POSIX native-terminal evidence. Preserve all existing datasets,
    checkpoints and source profiles; no new long training session is selected.
14. Prepare v0.2.0 metadata, release notes, migration/component-author guidance,
    compatibility limits and verified wheel/source hashes. Publish the requested
    release through the verified existing GitHub/PyPI path and check uploaded
    artifacts. No dependent package release is implied.

Use focused branches/PRs in rolling batches. Fold stacked children into parents
before main, retain passing current-head evidence and update the Project/issues
at integration. Keep numerical training in Thoughtformula, recipes/artifacts in
Thoughtform, capability dispatch in Hidden Moves, storage in Backpack, scheduling
in func_seq and document/table semantics in their owning libraries.
