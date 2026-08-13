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
| `inter-latin.woff2` | 71 KB | any Latin character |
| `inter-latin-ext.woff2` | 130 KB | a Latin-Extended one — rare here |
| `noto-sans-ethiopic.woff2` | 198 KB | Ge'ez **and** the machine has no Ethiopic font of its own — see the second revision |

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

## Revised 2026-08-13 — the first build got the wrong Inter, and set Ge'ez like Latin

The founder's verdict on what shipped: *"the Ge'ez and also the Latin font
looks ugly, not even the same font we used on DAPS Analytics."* Two separate
mistakes, both mine, both in this ADR's own decision.

**Inter must ship with its optical-size axis.** Inter 4 carries `opsz` 14–32,
and `font-optical-sizing: auto` — the CSS default — moves a 46px headline onto
the **display** cut: tighter, more compact, higher contrast. The first build
took fontsource's `wght`-only file, which has no `opsz`, so the hero rendered
in Inter's **text** cut scaled up to 46px: looser, wider, softer. Google Fonts
*does* serve the axis, so a site loading Inter from there gets the display cut
and this did not — which is precisely why it read as a different typeface.
Rendering both at 46px side by side made the difference obvious. Costs 23 KB
on the Latin file and 45 KB on Latin-Extended.

Nothing outside the font can see this. The filename is ours, the CSS is
identical either way, and the byte count is 23 KB that somebody will
eventually try to save. `tests/test_fonts.py` now reads the `fvar` table —
which is why `fonttools` is a declared dev dependency, on the same reasoning
as `openpyxl`.

**Ge'ez is not Latin and must not be set like it.** The hero's `-.025em`
tracking, `1.1` leading and `700` weight are tuned for Inter at display size,
and all three are wrong for Ethiopic:

- a Ge'ez character is a whole **syllable** with dense internal structure, and
  its sidebearings are already the minimum that keeps the strokes apart —
  pulling a pixel out of every gap at 46px is what turned the Amharic hero
  into a grey block;
- `1.1` leading nearly touches across two lines of a script with tall, busy
  forms;
- `700` fills the counters in. At 46px Ge'ez reads better at 600, and the
  weight drop is invisible beside the Latin because the script is denser to
  start with.

Now `letter-spacing: normal; line-height: 1.28; font-weight: 600`, keyed on
**`:lang()`** rather than the panel's language — the mock card cycles
languages independently of the interface, so the rule has to follow the text.
Both the headline and the card set `lang` from JS for that reason, which is
also just correct: a screen reader handed Amharic tagged `en` pronounces it as
English.

**The widget was checked and deliberately left alone** for the tracking fix. Its negative tracking
is `-.01em` on a 15px bank name and a 17px sheet heading — 0.15 of a pixel,
which is not the defect. The defect is display size: `-.025em` at 46px is over
a pixel per character. Message bubbles already sit at `line-height: 1.5`.
Changing the widget would have been motion without a reason.

## Revised again 2026-08-13 — Ge'ez goes back to the reader's own system face

The tracking and leading fix above helped and did not settle it. The founder:
*"restore the original font for Ge'ez, that was the best font."*

**"The original" was never a font this repo shipped.** Checking `59aa9b3`,
the stack before any of this named `"Noto Sans Ethiopic"` with **no
`@font-face`** — so it resolved only on a machine that already had that font,
and otherwise fell through to whatever the operating system supplies for
Ge'ez. On Windows, where most Ethiopian desktop users are, that is **Nyala**:
a traditional face with modulated strokes, and the one an Amharic reader
recognises as properly set. Self-hosting Noto Sans Ethiopic replaced it
*everywhere* with a monolinear sans — consistent, and worse.

So this ADR's own reasoning was right for Latin and wrong for Ge'ez, and the
two are now handled differently on purpose:

- **Latin is ours.** Inter leads, identical on every machine. There is no
  system Latin face a bank's dispatcher has an opinion about, and the whole
  point of vendoring it was that it look the same everywhere.
- **Ge'ez is the reader's.** `Nyala, "Abyssinica SIL", "Noto Sans Ethiopic",
  Ebrima` come first; our copy is **last**, reached only by a machine with no
  Ethiopic font at all, which would otherwise render tofu.

Two consequences, both accepted:

- **Ge'ez looks slightly different across operating systems.** That is the
  cost of the reader getting the face their own system considers right for
  their script. For this product's readers it is the better trade, and it is
  the founder's call to make, not a typographic principle to defend.
- **Most Ethiopian users no longer download the 198 KB at all.** A webfont is
  only fetched when it wins the fallback for a rendered character.

Both branches were **verified in a browser**, by installing an Ethiopic face
into the test container's fontconfig and running the page twice:

| Machine | our 198 KB file | Ge'ez renders | face used |
|---|---|---|---|
| has a system Ethiopic font | **not fetched** | yes | the system's |
| has none | fetched | yes | ours |

`warmMockFonts` had to change with it. It used to call `document.fonts.load`
with the Ge'ez family *by name*, which requests our copy explicitly and
downloads all 198 KB even on a machine that already has a face — exactly the
saving this arranges. It now lays out a probe carrying both scripts, styled by
the real stack, and awaits `document.fonts.ready`: whatever the stack actually
resolves to is what loads, and a system font resolves immediately.

**The Ge'ez headline weight is `600`, and that is settled** — confirmed on a
Windows machine by the founder, 2026-08-13, after the change went live.

Worth knowing before anybody adjusts it: **on Nyala this value is binary.**
Nyala ships only Regular and Bold, so CSS font-matching resolves `600` up to
**Bold** and `500` down to **Regular** — there is no 500 or 600 in the file
and nothing lands in between. The choice was Bold, because the English hero is
Inter at a true 700 and a Regular-weight Amharic beside it would carry
visibly less presence on a screen whose whole job is to make six languages
look like one product.

It is **not** binary everywhere: on macOS and Android, where Ge'ez resolves to
a variable Noto Sans Ethiopic, 500 and 600 are genuinely different weights. So
a "small" tweak here is one thing on Windows and another elsewhere.

## References

- `bankassist/static/fonts/` (files + OFL licences); the `/fonts/{name}` route
  and `_FONTS` in `api.py`; the `@font-face` blocks in `admin.html` and
  `widget.html`
- `tests/test_fonts.py`
- ADR-0003 (the portal is served from this origin) — same vendoring argument
