# Olink Bank Assist — design system

The design language of the public page (`bankassist/static/site.html`), written
so it can be handed to a design tool and handed back. Everything here is
implemented and rendered; nothing is aspirational.

**If you are generating screens from this:** the two rules that carry the whole
look are (1) an editorial serif at display size against a sans at text size,
and (2) colour arrives only as *light*, never as a fill. Get those two and the
rest is detail. Miss either and it reverts to a generic dark SaaS template —
which is exactly what the first version of this page was.

---

## 1. Type — the pairing is the design

| Role | Family | Weight | Notes |
|---|---|---|---|
| Display, numerals | **Playfair Display** | 500 | High contrast, fine hairlines, ball terminals |
| Everything else | **Inter** | 400–650 | With its optical-size axis |
| Ge'ez (አማርኛ, ትግርኛ) | the reader's system face | 600 | Never the serif — see §7 |

**Never bold the serif.** Its whole character is in the thin strokes; weight
700 thickens exactly what makes it worth having. 500 is the display weight.

**Never set the serif below ~28px.** At text sizes the hairlines disappear and
it becomes a worse Inter. Display headings and numerals only.

```
h1        clamp(38px, 5vw, 68px)   serif 500   line-height 1.08   tracking -.015em
h2        clamp(30px, 4.1vw, 54px) serif 500   line-height 1.08   tracking -.015em
numeral   60px                     serif 500   line-height 1
lede      17–18px                  sans 400    line-height 1.62
body      14–15px                  sans 400    line-height 1.62
micro     10.5px                   sans 700    tracking .18em     UPPERCASE
button    13px                     sans 650    tracking .06em     UPPERCASE
```

**One italic phrase per hero.** The headline sets a single word or short phrase
in the serif's italic, in the brand colour — *"In **their** language."* It is
what stops a large headline reading flat. One per page; two is a pattern and
patterns are invisible.

**Headline measure.** Centred display lines are held to ~15ch (h1) and ~22ch
(h2). Set across a full 1180px they read as a banner rather than a sentence.

---

## 2. Colour — light, not fill

```
--bg        #060709   near-black canvas
--card      rgba(255,255,255,.026)   ≈ #0b0c0e composited
--card-2    rgba(255,255,255,.045)
--line      rgba(255,255,255,.085)
--line-2    rgba(255,255,255,.15)

--brand       #2dd4bf   teal
--brand-deep  #0f766e
--warm        #f0873f   the off-hue
--violet      #8b7bff
```

**The rule:** no element is ever filled with a brand colour. Colour appears as
a **blurred bloom behind or bleeding into** content — `filter: blur(110px)` at
13–42% opacity. The only saturated fills anywhere are a 25px logo mark and a
6px status dot.

**One bloom is deliberately off-hue.** An all-teal page reads as a product
screenshot. A warm bloom at low opacity is what makes it read as a photograph
of something lit. Use it once or twice per viewport, never centred.

**Every card gets one lit corner** — a single 190px bloom bleeding in from one
edge at ~20% opacity, `z-index` below the content. This is what makes a flat
card read as a surface with light falling across it, and it is the single
highest-leverage detail in the whole system.

---

## 3. Text contrast — measured, not eyeballed

Low-contrast grey on near-black is the default look of this genre, which is
why it slips past review: it looks deliberate. It is still unreadable on a dim
laptop in a bright office, which is where a bank's staff open this.

| Token | Hex | Ratio | Use |
|---|---|---|---|
| `--ink` | `#f6f8fb` | 18.4:1 | Headings |
| `--body` | `#b9c2d0` | 10.9:1 | Card and plan copy |
| `--muted` | `#98a1b0` | **7.5:1** | Lede and most body copy — AAA |
| `--faint` | `#8892a2` | **6.2:1** | Micro-labels, axis, footer |

Ratios are the **worse** of page background and card surface — a card is
lighter than the page, which *lowers* contrast for light text, so measuring
only against `--bg` passes colours that fail where they are actually printed.

**4.5:1 is a hard floor** (WCAG AA, normal text). `tests/test_contrast.py`
enforces it across all three surfaces and fails the build otherwise. Two real
failures were found this way — `--faint` at 3.80:1 and the widget's
`--text-3` at 4.32:1.

When darkening a grey for looks: don't. Solve for the ratio and keep hue and
saturation fixed, moving lightness only.

---

## 4. Layout

```
container   1180px max, 26px gutter
section     128px vertical (82px ≤760px), 1px top hairline between
radius      18px cards · 11px bars · 999px pills
```

**Bento, not a card row.** Mixed tile weights on one grid — a wide explainer
(`span 2`), a full-height feature (`row span 2`), and small tiles carrying a
single serif numeral. A uniform grid of equal cards is precisely what makes a
page read as a template. Base row height 186px; collapse to one column at
640px.

**Micro-label → display heading → lede** is the section opener, every time.
The uppercase letterspaced label is what stops a long dark page reading as a
wall.

---

## 5. Components

**Buttons.** Pills, uppercase, letterspaced. Solid (`#f2f5f8` on near-black
text) for the working primary action; outlined for secondary. A disabled
primary is worse than no primary — if the main CTA is not wired, promote the
one that works and demote the other.

**Chips.** 999px, `--card-2` fill, hairline border. Active state uses
`color-mix(brand 17%)` fill with a 42% border — never a solid brand fill.

**Numeral tiles.** A serif numeral at 60px, a 13.5px sans caption beneath, and
optionally a `bottom`-anchored link. The numeral does the work; do not add an
icon.

**Gantt rows.** Offset bars on a shared track with `--from` / `--w` / `--tint`
set inline as data, a vertical `NOW` marker, tints progressing teal → violet →
warm across time. Always declare defaults in CSS so a bar missing its inline
values degrades to a full-width row rather than collapsing.

**The live product is the hero object.** Not a screenshot, not a video — the
real widget in an iframe, requested with `?theme=dark` so it sits *in* the page
rather than as a white slab on it.

---

## 6. Motion

Three blooms drifting on a 40s ease-in-out alternate loop, ±4% translate and a
1.18 scale. That is the entire motion budget for the page.

**All of it disables under `prefers-reduced-motion: reduce`**, including
`scroll-behavior`.

---

## 7. Non-negotiables

These are enforced by tests and are not style preferences.

1. **Ge'ez is never set in the serif.** Playfair has no Ethiopic, so an Amharic
   headline falls through to a system face *while keeping the serif's tracking
   and leading*. `.display:lang(am|ti)` must switch family, weight, tracking
   and leading together.
2. **Ge'ez takes no negative tracking and needs more leading.** A Ge'ez
   character is a whole syllable whose sidebearings are already minimal;
   `-.025em` at display size crowds it into a grey block.
3. **No external origin.** No CDN font, icon set or analytics tag. Everything
   is served from our own origin — a bank's staff sit behind proxies that
   block them.
4. **No prospect bank's name** anywhere on a public surface.
5. **No invented metric and no price.** No deployments means no "% deflected",
   no "N banks", no "trusted by". Pricing publishes the *model*, never a
   number.
6. **4.5:1 minimum on all text.** See §3.

---

## 8. Files

| | |
|---|---|
| `bankassist/static/site.html` | The page — self-contained, no build step |
| `bankassist/static/fonts/` | Vendored woff2 + OFL licences |
| `tests/test_marketing_site.py` | The claim guards (§7.4, §7.5) |
| `tests/test_contrast.py` | The contrast floor (§3) |
| `tests/test_fonts.py` | Stack order, range gating, serif scoping |
| `docs/decisions/0030-*.md` | Why the page is built this way |

The serif is loaded by this page **only** — the admin panel and the widget
never request it, so nobody doing their job pays 38 KB for marketing type.
