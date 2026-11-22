# Release notes

## 0.2.0

Application and component-library foundation:

- One owned Program/command/terminal lifecycle, bounded streams, timers,
  cancellation, restoration, optional frame coalescing and immutable root models.
- Constraint layout with clips, padding/margins, weights, percentages, overlays
  and shared hit-test geometry.
- Bundled Unicode 18 graphemes, documented cell-width policy, wide-cell-safe
  layers, color fallbacks, copied frame diffs and explicit cursor restoration.
- Incremental legacy/xterm/Kitty input, focus and mouse reports, finite malformed
  input/paste handling, Escape timeout and paired protocol cleanup.
- Focus routing, typed forms/services, theme roles, shell regions, textual
  command/status states and modal scope conventions.
- Structural component contracts, Label/Button/Checkbox/Progress controls and
  adapters for TextInput/List/Viewport/Spinner. TextInput edits graphemes.
- Optional read-only Headless Spreadsheets snapshot tables with stable identity
  selection and bounded visible-cell rendering.

Migration: existing update/view models, field declarations and legacy input
defaults remain usable. A Program runs once; create a new instance for a second
session. Returning a model from update is now adopted when it has update/view
methods. TextInput retains character offsets, normalized to grapheme boundaries.
Prefer ComponentState for new controls and AppShell for shared regions. See the
focused guides for protocol opt-ins.

Core has no runtime dependencies and supports Python 3.10+. Native terminal
evidence covers POSIX; native Windows console input remains unqualified. The
snapshot adapter requires Python 3.14+ and the Git pin in requirements-tables.txt,
since published Headless Spreadsheets 0.1.0 predates snapshots. Complete widget
coverage stays in #7. Model providers and domain workflows stay upstream.

Code is MIT licensed; bundled Unicode data carries Unicode-3.0. Both licenses
ship in wheel and source archives.

## Publication

Merge selected work after exact-head CI and application qualification. Build
with `uv build`, then run `python scripts/check_distribution.py dist --tag v0.2.0`
and `python scripts/qualify.py dist`. Tag the verified main commit. Publish the
GitHub release to trigger `.github/workflows/release.yaml` and the existing
`pypi` trusted publisher. The workflow checks main ancestry and tag/version,
qualifies the wheel/source pair, uploads those exact artifacts, and publishes
them from a separate job. Download that pair for GitHub release attachments;
compare actual PyPI download hashes and install the public package uncached.

## 0.1.0

Initial dependency-free message loop, ANSI parser, cell rendering/styles, zones,
basic components and declarative forms.
