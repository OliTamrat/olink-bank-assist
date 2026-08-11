# Linguist review — the five-language workbook

Every string ships in en/am/om/ti/so, drafted by the agent and reviewed by a
native speaker afterwards — the multilingual rule is "draft, ship, review",
never "wait". The review artefact is
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

## Rules

- Rebuild with `python scripts/build_review_workbook.py` after any string
  change and commit the result. The workbook is **byte-reproducible** — a
  rebuild with unchanged strings produces an identical file
  (`tests/test_review_workbook.py` holds this; PR #110 explains why it once
  didn't).
- Returned corrections go into the JSON string tables via
  `review/strings.tsv`; parity tests refuse untranslated keys.
- Proper nouns are transliterated, never translated — Fayda is ፋይዳ.
