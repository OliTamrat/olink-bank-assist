# ADR-0008 — Five languages as complete string tables: draft, ship, review

**Status:** accepted · **Date:** 2026-08 (PRs #98–#107)

## Context

en/am/om/ti/so across assistant replies, widget, admin and teller console.
Waiting for native-speaker review before shipping means the languages never
ship; shipping English with TODO keys means customers see mixed-language
screens.

## Decision

Every key ships in all five languages at once — agent-drafted, then reviewed
via the byte-reproducible workbook (`build_review_workbook.py`). Parity tests
refuse empty or English-identical cells. Proper nouns (Fayda → ፋይዳ) are
transliterated, never translated.

## Consequences

- No screen is ever part-English; review improves live text instead of
  gating it.
- The classifier phrasebook for ti/so is agent-drafted and **review is
  load-bearing there** — a wrong phrase mis-fires security refusals
  (runbooks/linguist-review.md).
- Cost: agent drafts are imperfect by design; the loop, not the draft, is
  the quality mechanism.

## References

`i18n.py`, parity tests, PRs #102, #105, #107.
