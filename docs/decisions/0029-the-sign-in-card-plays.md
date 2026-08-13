# ADR-0029 — The sign-in card plays, and the headline is composed six times

**Status:** accepted · **Date:** 2026-08-13

## Context

Two things came back from the founder in one message.

The first: the Amharic headline **"የባንክዎ መግቢያ በር፣ በደንበኛዎ ቋንቋ።"** does not make
sense. He was right, and it was not one language — **all five** had rendered
the English metaphor "front door" as a physical door: Oromo `Balbala`,
Tigrinya `መእተዊ ማዕጾ`, Somali `Albaabka hore`, Swahili `Mlango wa mbele`. A
promise had been turned into a carpentry noun in every language but the one it
was written in.

The second: make the mock card an animated live Q&A that plays **all six**
languages.

They are the same problem seen from two sides. The card was a still, so it had
to pick one language to illustrate a product whose entire claim is six — and
whichever it picked was the wrong one for five sixths of the room.

## Decision

**The headline is composed in each language, not translated into it.** English
keeps its metaphor because it works in English. The other five say the same
thing the way a native speaker would say it — *let your bank welcome its
customers in their own language*. This is the rule ADR-0026 already set for
generated prose, applied at last to our own copy.

**The card plays.** One customer question, asked and answered in all six
languages in turn: the question types in, the assistant pauses, the answer
types back, the citation chip lands last. The language pill row doubles as the
progress indicator.

**The same question every time.** Six different questions would have read as a
feature tour. The claim is not "we have six phrasebooks", it is *the same
question is answered in whichever language it arrives in* — and only the same
question shows that.

**It is still not a live conversation.** The text is the string table, not a
model call. Faking a real exchange on a signed-out screen would mean inventing
one that never happened, which is the same reason the stage carries no
metrics.

**The pause is honest.** There is a retrieval pass and a model call behind a
real answer and they take about a second. A mock that answered instantly would
be promising something the product does not do.

**Per-message timing, not per-character.** A Ge'ez character carries a whole
syllable, so the Amharic answer is a fraction of the English one's length. A
fixed ms-per-character would make the same sentence race past in one language
and crawl in another — on a screen whose whole job is to show the six as one
product. A target duration divided by the length is what makes them feel like
one speed.

**The height is reserved before the first frame**, measured from the longest
of the six — and measured *after* the fonts land, because measuring Ge'ez in a
fallback face reserves the wrong number and the card grows a line the first
time Amharic plays.

**Four reasons not to run**, each a real cost rather than a nicety: signed in
(the gate is `display:none` behind the dashboard for eight hours), narrow (the
stage does not render below 1024px, so on a phone this is pure battery),
hidden tab (a login page left open in the background is the normal case), and
no string tables yet (it would play six identical English exchanges, which is
the opposite of the point).

**Reduced motion keeps the rotation and drops the typing.** The rotation is
the subject; freezing the card on one language would remove the only thing it
is there to say.

## Consequences

- **Watching it play in a browser found a defect the diff could not, and it
  was the founder's own complaint one level up.** The exchange cycled while
  the card's *chrome* — `Assistant`, `online`, `2 sources` — kept reading from
  `A()`, the panel's language. So a Tigrinya conversation sat under an Amharic
  header. Everything on the card now paints through `inLang()` from one
  language; `A()` no longer appears in any of it, and a test says so.
- **`[hidden] { display: none !important }` earns the `!important`.** The
  browser's own rule is specificity (0,1,0), so `.bubble.dots { display: flex }`
  outranked it and the thinking dots stayed on screen underneath the answer
  they were supposed to precede. `hidden` has one meaning and no stylesheet
  should be able to argue with it.
- The language chip's turnover animation started at `opacity: 0`, which left
  the chip row visibly empty for a beat and shifted `2 sources` across to fill
  the gap. It starts at `.35` now.
- `tests/test_sign_in_mock.py` reads the wiring out of the source, because CI
  has no browser. It was mutation-checked: putting the card back on `A()`,
  dropping `mockStop()` from `enterApp`, and hard-coding a language into the
  script each fail a test.
- The pill row is generated from `LANGS`, so a seventh language cannot ship in
  the product and be missing from the screen that advertises them.
- **Amharic and Afaan Oromoo are confirmed; Tigrinya and Somali are not.**
  The founder — a native speaker of both — read the replacement headlines and
  confirmed them (2026-08-13). That closes the two that matter most for the
  pilot, and it is worth recording *which* two, because "the founder approved
  the headline change" would quietly imply four.

  `ti` (**ባንክኹም ንዓማዊሉ ብቋንቋኦም ይቀበሎም።**) and `so` (**Bangigaagu macaamiishiisa
  ha ku soo dhaweeyo luqaddooda.**) are still my composition. They are
  unambiguously better than a door, and they stay on the pending linguist
  review — the same status the rest of the OM/TI/SO/SW tables carry.

## References

- `mockScript` / `mockPlay` / `mockType` / `paintMockCard` / `mockMayRun` /
  `reserveMockHeight` in `static/admin.html`; `stage_line` in
  `admin_strings.json`
- `tests/test_sign_in_mock.py`
- ADR-0026 (generated prose is not reviewable text) — the composed-not-
  translated rule this applies to fixed copy
- ADR-0028 (the typefaces ship with the product) — why the Ge'ez face is
  warmed before the card is measured
