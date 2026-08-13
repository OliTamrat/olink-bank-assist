# Linguist review — the six-language workbook

Every string ships in en/am/om/ti/so/sw, drafted by the agent and reviewed by
a native speaker afterwards — the multilingual rule is "draft, ship, review",
never "wait". (Swahili joined in ADR-0018; this page said "five" for a while
after it did.) The review artefact is
`review/Olink_Bank_Assist_language_review.xlsx`, built by
`scripts/build_review_workbook.py` from the string tables and
`review/strings.tsv`.

## The sheets

1. **What the assistant says** — customer-facing replies. Highest stakes.
2. **What it understands** — the classifier phrasebook. **Load-bearing for
   Tigrinya and Somali**: those phrasings were agent-drafted (PR #105) and a
   wrong entry either fires a security refusal on an innocent question or
   misses one it should catch. This sheet is why the review is not cosmetic.
3. **Buttons customers see** — widget strings.
4. **The staff panel** — admin + teller console strings.

Colour code: yellow = please edit, pink = nothing supplied, grey = leave
alone.

## What has actually been confirmed

The whole point of "draft, ship, review" is that shipped text is not the same
as reviewed text. This is the ledger of the difference, and it should be
narrowed by adding rows, never by rounding up.

| Date | What | Languages | By |
|---|---|---|---|
| 2026-08-13 | `stage_line` — the sign-in headline (ADR-0029) | **am, om** | founder, native speaker of both |
| 2026-08-13 | Ge'ez rendering on the sign-in screen — face, tracking, leading, weight (ADR-0028) | **am** | founder, on Windows/Nyala, after deploy |

Everything else in am/om/ti/so/sw is agent-drafted and unreviewed, including
`ti` and `so` of the row above. When writing about this anywhere, name the
languages: "the headline was approved" reads as four when it was two.

## Rules

- Rebuild with `python scripts/build_review_workbook.py` after any string
  change and commit the result. The workbook is **byte-reproducible** — a
  rebuild with unchanged strings produces an identical file
  (`tests/test_review_workbook.py` holds this; PR #110 explains why it once
  didn't).
- Returned corrections go into the JSON string tables via
  `review/strings.tsv`; parity tests refuse untranslated keys.
- Proper nouns are transliterated, never translated — Fayda is ፋይዳ.
