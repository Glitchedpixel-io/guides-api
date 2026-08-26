# Vendored typefaces

The sheet's two faces, committed rather than fetched.

| File | Family | Weight |
|---|---|---|
| `ArchivoNarrow-400/500/600/700.ttf` | Archivo Narrow | 400, 500, 600, 700 |
| `IBMPlexMono-400/500/600.ttf` | IBM Plex Mono | 400, 500, 600 |

## Why they are here

The Claude Design canvas loads both from the Google Fonts CDN. A PDF whose typography
depends on network reachability is not reproducible, and production has no egress — so
`blueprint.css` references these files by relative path instead.

**Static weights, not the variable font.** Google's woff2 endpoint serves one variable file
covering all four Archivo Narrow weights; WeasyPrint's variable-font support is partial, and
a weight axis it fails to apply collapses every heading silently to regular. Seven separate
static files cannot do that.

## Licence

Both families are licensed under the [SIL Open Font License 1.1](https://openfontlicense.org/),
which permits redistribution of the font files, including bundled in a project like this one.

- **Archivo Narrow** — Copyright The Archivo Project Authors
  (<https://github.com/Omnibus-Type/Archivo>)
- **IBM Plex Mono** — Copyright IBM Corp. (<https://github.com/IBM/plex>)

## Replacing them

Every character the sheet prints must exist in whatever ships here.
`tests/unit/test_font_coverage.py` enforces that and will fail if it does not — WeasyPrint
substitutes missing glyphs silently, so nothing else would catch it. That test exists
because the canvas used `⌀` (U+2300), which is in neither family: a browser fell back to a
system font and it looked fine, while the PDF would have printed a replacement box.
