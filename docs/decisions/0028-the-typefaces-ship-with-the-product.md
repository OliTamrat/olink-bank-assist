# ADR-0028 — The typefaces ship with the product

**Status:** accepted · **Date:** 2026-08-13

## Context

The founder asked for "a good font", naming the one on the DAPS Analytics
site. That is **Inter**, loaded there from the Google Fonts CDN.

Looking at why the panel read flat turned up something worse than a taste
problem. Both `admin.html` and `widget.html` opened their stack with
`"Noto Sans Ethiopic"`, so on any machine that had it, **every Latin
character in the product** — every label, every metric, every English
answer — was drawn with a Ge'ez face's Latin glyphs. Noto Sans Ethiopic is an
excellent Ge'ez face and an incidental Latin one. The panel was not
under-designed; it was being drawn in the wrong typeface.

## Decision

**Inter leads the stack, Ethiopic stays in it.** CSS font fallback is
per-character, not per-element: a family that declares no range for a
codepoint is skipped for that codepoint alone. So Inter first costs Amharic
nothing — ሰላም still resolves to Noto — while Latin stops being a fallback
glyph. Both pages now read:

```
"Inter Variable", Inter, "Noto Sans Ethiopic Variable", "Noto Sans Ethiopic", …
```

**Self-hosted, not from Google Fonts.** This is the same argument already
recorded for the LiveKit SDK, and it applies harder to a font. The admin panel
shows customer conversations; the widget runs in an iframe on a bank's own
production pages. A `fonts.googleapis.com` tag on either is an origin the
bank's security review has to justify, a `Content-Security-Policy` entry they
have to widen, an outage nobody in this project can fix, and — for a
dispatcher in Addis — a round trip to a European edge before there is text on
the screen. The files are in the repo, pinned, and served from `/fonts/*`.

Both are SIL OFL 1.1, and both licences are committed alongside them.

**Variable fonts, split by script.** One file per script covers weights
100–900, so the five weights this panel uses cost nothing extra, and
`unicode-range` decides what is actually fetched:

| File | Size | Fetched when |
|---|---|---|
| `inter-latin.woff2` | 48 KB | any Latin character |
| `inter-latin-ext.woff2` | 85 KB | a Latin-Extended one — rare here |
| `noto-sans-ethiopic.woff2` | 198 KB | any Ge'ez character |

That split is what makes vendoring Ge'ez affordable. Verified in a real
browser: an English widget session fetches **48 KB and nothing else**. Without
`unicode-range` every session on every Ethiopian mobile connection would pull
all 331 KB.

**An allowlist, not a path join.** `/fonts/{name}` takes a name off the wire.
The obvious implementation is a directory join, which is a path-traversal
route; `_FONTS` in `api.py` is a set, and `tests/test_fonts.py` states the
traversal attempts as tests so the "simplification" back to a join fails.

`font-display: swap` throughout — a blocking font on a slow connection is a
blank panel, and the fallback text is readable.

## Consequences

- **Rendering the sign-in screen found the bug the founder actually
  reported**, which no diff and no API test could have. The screen showed an
  Amharic question answered in English — on the login page of a product whose
  entire premise is answering in the customer's language. The cause was not
  the strings: `paintGateCopy()` was reachable from exactly two places, a
  bank's brand resolving and the language picker changing, so a **fresh
  browser with no remembered slug painted the gate from neither** and kept
  whatever the markup said — and the markup happened to carry an Amharic
  question next to an English answer as separate literals. It now also paints
  when the string tables land, which is both the missing call and the correct
  ordering, since a brand can resolve before the tables do. The four markup
  defaults are one language now, so even a failed `/admin/strings` shows a
  coherent exchange.
- The language picker on the gate was a native `<select>`, which keeps the
  platform widget and silently ignores `background` — a light-grey system
  control on a near-black panel. `appearance: none` plus a hand-drawn chevron.
- English gate copy uses typographic apostrophes. At 46px in Inter the
  difference between `'` and `’` is the difference between typeset and typed,
  and it is the whole reason to change a font.
- **331 KB is now in the repo.** That is the price of no third-party origin,
  and it is paid once per release rather than per request:
  `Cache-Control: immutable`, unlike the pages, which are `no-store`. Nothing
  in `/fonts/*` is tenant data.
- Nothing in Python imports these files, so a rename or a dropped file would
  leave every test passing and a bank's dashboard rendering in Times New
  Roman. `tests/test_fonts.py` asserts the allowlist, the woff2 magic number,
  the stack order, the range gating, and that no page reaches out to a font
  CDN.

## References

- `bankassist/static/fonts/` (files + OFL licences); the `/fonts/{name}` route
  and `_FONTS` in `api.py`; the `@font-face` blocks in `admin.html` and
  `widget.html`
- `tests/test_fonts.py`
- ADR-0003 (the portal is served from this origin) — same vendoring argument
