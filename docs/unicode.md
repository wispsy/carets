# Unicode cells, styles and layers

Carets bundles Unicode 18.0.0 property ranges. `carets.unicode.graphemes` follows
[UAX #29 revision 49](https://www.unicode.org/reports/tr29/tr29-49.html), including
the Unicode 18 Indic-conjunct rule. Tests run the entire official grapheme-break
fixture. `unicode-sources.json` pins input URLs/hashes, and the data is distributed
under `UNICODE_LICENSE.txt`. Regeneration uses `scripts/generate_unicode.py` with
explicit downloaded source files, never network work at import/runtime.

All style clipping and screen writes use that same grapheme path. Common emoji,
flags, keycaps, wide characters, combining text and ZWJ sequences stay whole.
Ambiguous width is one; orphan marks/controls occupy zero; common emoji/wide
clusters occupy two. This is a deterministic terminal policy. Fonts, complex
shaping and individual emulators can differ; the Unicode East Asian Width
property alone is not a universal terminal layout solution. Whole graphemes
must be passed to a screen write; stream consumers accumulate text before layout.

`ScreenBuffer` stores continuation cells for double-width clusters. Writes and
`blit` layers clip complete clusters and clear overwritten wide cells. Renderers
snapshot previous frames so mutating/reusing a caller's buffer cannot hide changes.
`invalidate()`, resize and `full=True` force a complete redraw. Clipping accepts
layout `Rect` results. Non-SGR terminal sequences in text are never executed.

`Style` accepts named ANSI colors, 0–255 indexes, RGB tuples and `#RRGGBB` values.
Renderers choose 24-bit, 256-color, 16-color or no-color output (`color_depth`
24/8/4/0). `ansi=False` gives plain frames. Explicit style width/height now clip
content; padding works on every edge. Truncated colored output is reset before
leaving a painted run.

An optional `Cursor` places/shapes/shows the editing cursor after frame writes;
out-of-bounds positions hide it. Standalone renderer owners call `close()` in
cleanup to restore cursor defaults. A Program owns registered renderer cleanup
before terminal restoration. A terminal's previous arbitrary cursor shape is not
queried or guessed. DEC synchronized output can be disabled independently.
