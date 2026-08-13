# ADR-0026 — Generated prose is not reviewable text

**Status:** accepted · **Date:** 2026-08-12

## Context

The founder tested the AI Insights page across all six languages and found an
Afaan Oromoo grammar and word-choice error — correctly judged not a blocker,
and correctly followed by *"we need a professional linguist review."*

The trap is what a linguist would be handed. `review/Olink_Bank_Assist_language_review.xlsx`
carries 437 rows across four sheets and is, reasonably, treated as *the*
review artefact. **The sentence the founder found is in none of them.**

The Insights headline is composed by Gemini per request from the metrics
digest, in whichever language the reader has selected. There is no row to
correct. The same question asked twice produces two different sentences. The
same is true of every answer generated from retrieved documents and every
general-guidance reply — which is most of what a customer actually reads.

Briefing a reviewer as though the workbook covers the product is how a review
gets blamed for a defect it never had access to, and how the same class of
error survives a round of paid review.

## Decision

**Name the two kinds of text, and route their fixes differently.**

- **Table text** — buttons, labels, fixed templates, empty states, errors.
  Lives in the three JSON tables, appears in the workbook, fixed by editing a
  row. Permanent, diffable, testable.
- **Generated prose** — the Insights brief, document-grounded answers,
  general guidance. Lives nowhere. Fixed **only** through the prompt.

A reviewer's corrections on table text land in the tables. Anything they flag
on a generated sentence is feedback on a *prompt*, and the fix is an
instruction rather than a translation. The review brief must say so.

**Both generating prompts now carry the same instruction:** compose in
`{language_name}` rather than translating an English sentence into it —
everyday spoken register, short sentences, common vocabulary over literary,
proper nouns (the bank's name, Telegram, WhatsApp, Fayda) left alone. "A
sentence that is grammatical but reads as translated has failed this rule."

That phrasing is deliberate. "Write in Afaan Oromoo" alone reliably produces
correct-but-calqued output: English clause order with Oromo words in it,
which is exactly the shape of the defect reported. Naming the register and
forbidding the translation *process* is the standard mitigation.

## Consequences

- **It reduces the defect rate; it does not make a native reviewer
  optional.** A fluent-looking wrong sentence in a management brief serves a
  bank manager worse than an obviously broken one, because nothing prompts
  them to doubt it.
- **The tests here are deliberately weak and that is the point.** They assert
  the instruction is present, not that the model obeys it — no sandbox test
  can do the second, since no sandbox can reach the model. What they prevent
  is a future session tidying a prompt and silently undoing a fix made in
  response to a defect a native speaker found by reading the live product.
  `GENERATING_PROMPTS` is a list a new prompt must be added to.
- The `test_the_fayda_name_is_never_translated` rule now has a counterpart
  for text no table holds.
- Unmeasured, and honest about it: whether this actually improves the Oromo
  output. The only way to know is to look at the page again in each
  language, which is the founder's check, not a test's.

## References

- `_SYSTEM_PROMPT` rule 3 and `_INSIGHTS_PROMPT` in `llm.py`
- `tests/test_generated_prose_language.py`
- The "Two kinds of non-English text" table in `CLAUDE.md`
- ADR-0008 (five languages as complete string tables — this is what that ADR
  does *not* cover), ADR-0021 (the model as analyst on the Insights page)
