# ADR-0030 — The public page runs the product, and is English

**Status:** accepted · **Date:** 2026-08-13

## Context

The binding constraint on this product is not a missing feature. It is that
**no bank has signed anything.** Every other item on the roadmap — in-country
hosting, embedding retrieval, retiring the admin-token bypass, the linguist
review — makes the product better for a customer we do not have. There was no
public surface at all: `static/` held an admin panel and a widget.

The founder asked for a marketing site and a pricing system, having looked at
how **Glia** — the direct competitor already named in `market-position.md`,
selling AI-to-human handoff to 700+ US institutions — markets theirs. His
instruction: take the strategy, not the design, and *"I do not want you just
build a static page."*

## Decision

**The page is served from this app, at `/`.** Not a separate marketing host.
The thing that sells this product is the product, and the demo on the page is
a real `/widget?bank=demo` against a real knowledge base. Split across two
origins that becomes a third-party iframe on a marketing site — blocked by
exactly the corporate proxies a bank's staff sit behind — and the demo could
silently drift from the product it demonstrates. One origin, one deploy.

**The hero is the running widget, not a picture of one.** No video, no
screenshot carousel. A prospect types a question and watches it answer from
documents with the source attached, then switches language inside the chat.
Nobody can be argued out of a thing they just did themselves. This is what
"not a static page" means here, and it cost nothing to build because the
product already existed.

**We do not lead with handoff.** `market-position.md` is explicit: *"any pitch
that leads with 'nobody else does live handoff' is wrong and will be caught by
anyone who has shopped this category."* Glia owns that ground. Building their
page with better typography would be fighting them on it. The spine is instead
the real whitespace — *your customers already message you, in their own
language, on Telegram* — and handoff appears fourth.

**Pricing publishes the model, not a number.** Per institution, never per
seat; setup fee plus monthly tiered by conversation volume. That shape is what
Phase 4 already decided and it is what a bank's procurement can approve.
A figure, with zero deployments and no delivery-cost data, is one we get
negotiated down from and cannot revise upward. Three deployment shapes are
named (Pilot / Institution / Group) with what each includes.

**No billing system.** An Ethiopian bank does not put a corporate card into a
checkout page; it signs a contract and pays an invoice. Subscription billing
before a signed pilot is a mechanism for a transaction that will not happen
that way.

**The page is English.** This deviates from the multilingual golden rule and
the deviation is deliberate, so it is recorded rather than quietly taken. The
rule exists so that *product* surfaces are never English-plus-a-promise. This
surface is different in two ways: its reader is a bank's innovation or
procurement lead, who works in English; and its content is **persuasive
prose**, which is far harder to translate well than an interface label. Three
of the six languages are still first-pass and unreviewed — putting thousands
of words of unreviewed persuasive writing in front of prospects in those
languages would be worse than not doing it. The six-language claim is proved
on this page by the *embedded product*, which speaks all six, rather than by
the chrome around it.

**Two values are empty on purpose.** `SITE.contactEmail` and `SITE.domain`.
An invented address silently drops enquiries; a canonical URL invented before
the domain is chosen is a wrong URL somebody has to hunt down later. The
calls to action carry `data-pending` and say so rather than opening a blank
mail window addressed to nobody. There is no canonical tag and no Open Graph
URL yet for the same reason.

## Revised 2026-08-13 — the type pairing is the design

The first build of this page set everything in Inter. The founder's verdict:
*"the same old boring (static) design"*, with a reference site attached — a
dark, editorial fintech page — and the instruction to be inspired by it.

He was right, and the cause was not the colours or the spacing. **A page with
one neutral sans has no voice.** What the reference does before anything else
is set an editorial serif at display size against a workhorse sans at text
size, and the contrast between the two *is* the character. No amount of
gradient work substitutes for it.

- **Playfair Display** is vendored for this page and no other — high stroke
  contrast, fine hairlines, ball terminals. It appears only at display sizes
  and on numerals; at 15px its hairlines vanish and it is a worse Inter. Set
  at weight 500 rather than bold, because bolding thickens exactly the thin
  strokes worth having. 38 KB, on the one surface whose job is to look like
  something — the admin panel and the widget never request it, and a test
  asserts they never do.
- **Colour arrives only as light**, never as fill: three blurred blooms, one
  deliberately off-hue (warm) because an all-teal page reads as a product
  screenshot rather than a photograph of something lit. Each bento tile gets
  one bloom bleeding in from an edge, which is what makes a flat card read as
  a surface.
- **A bento grid**, not a card row. Mixed weights — a wide explainer, numerals
  set in the serif, a full-height feature — because a uniform grid of equal
  cards is the specific thing that made the first version read as a template.
- **The roadmap is a real Gantt of the real phases**, with an honest `NOW`
  marker and Phase 1 marked shipped. It says on the page that no bank has
  signed a pilot, because a roadmap that hid that would be the first thing
  worth distrusting.
- **Ge'ez is never set in the serif.** Playfair has no Ethiopic, so an Amharic
  headline would fall through to a system face while keeping the serif's
  tracking and leading. `.display:lang(am|ti)` switches family as well as
  spacing — a new failure mode that only exists once a display serif is in
  play, and a test covers it.

**The widget gained a theme it should always have had.** Its dark palette was
reachable only through `prefers-color-scheme` — the visitor's operating
system, which an embedding page cannot influence. So a bank with a dark
website got a white panel bolted onto it for every visitor running a light
OS, and so did this page: a white slab in the middle of a near-black hero.
The declarations did not change; they moved off the media query onto
`:root[data-theme="dark"]`, and `?theme=dark|light` now chooses, defaulting to
the visitor's preference exactly as before. Decided in the `<head>` rather
than with the rest of the script, because a panel that paints light and then
corrects itself is worse than one that was simply light.

## Consequences

- **The largest risk on this page is naming a prospect.** CBE, Dashen and
  Awash are unauthorized prototypes built from public information (ADR-0009).
  Internally that is a demo with a disclaimer; publicly it implies a
  relationship that does not exist, which is a trademark problem and the
  fastest way to lose those three as customers. The demo runs on the fictional
  tenant, and `tests/test_marketing_site.py` fails if any of the three names
  appears in the file.
- **Two more machine-checked claims.** No invented metric (no deployments
  means no "% deflected", no "N banks", no "trusted by"), and no currency
  figure — the latter is how "publish the model, not a number" gets quietly
  reversed by somebody filling in the pricing table.
- The page **states which languages have been reviewed**. Amharic and Afaan
  Oromoo have; Tigrinya, Somali and Swahili have not. Saying so on the
  marketing page is the difference between a claim and a claim somebody can
  catch us on, and a test asserts the qualification is still there.
- No external origin, by the same doctrine as the vendored fonts and LiveKit
  SDK — a test raises on any `http(s)://` in a `src` or `href`. Marketing
  pages are where a CDN icon set or an analytics tag normally creeps in.
- **Deferred to a second pass, with the founder's agreement:** "see it on your
  own content" — a prospect pastes their published FAQ URL and gets a working
  assistant on their own material. Page import and bulk import already exist,
  so this is mostly sandbox lifecycle and abuse control. It is a narrow form
  of self-serve tenant creation, which ADR-0030's own reasoning otherwise
  refuses; the distinction is that a sandbox is ephemeral, unbranded,
  channel-less and holds no customer data.

## References

- `bankassist/static/site.html`; the `/` route in `api.py`
- `tests/test_marketing_site.py`
- `docs/market-position.md` — the competitive read on Glia and the whitespace
- ADR-0009 (prospect tenants are unauthorized prototypes)
- ADR-0026 (composed, not translated) — why unreviewed persuasive prose in an
  unreviewed language is a liability rather than a feature
