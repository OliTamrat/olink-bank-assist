# ADR-0033 — The corpus is not the only ceiling

**Status:** accepted · **Date:** 2026-08-14

## Context

CLAUDE.md has said, since early on and in bold, that **the corpus is the
ceiling**: every tenant runs on fifteen to twenty-three documents where a real
bank's public site is several hundred pages, and nothing about the model, the
prompt or retrieval moves the answer rate as much as content does. The standing
advice to any session asked to "make the assistant better" was to check the
corpus size first.

Asked to act on that, this session built the measurement instead of writing a
hundred documents on faith. The result contradicted the advice, and the
contradiction is worth more than the documents would have been.

## What was measured

`scripts/corpus_gaps.py` asks each tenant 52 questions real retail customers
ask — fees, a lost card, an ATM that took the money — in extractive mode with
no LLM configured, and scores a reply as a gap when it contains none of the
terms a genuine answer would have to contain.

**Baseline: 66 gaps across four tenants — demo 67%, CBE 69%, Dashen 69%,
Awash 67% covered.**

The distribution was the finding. **"Disputes and problems" was 5 of 6
unanswered on all four tenants, identically.** Not a coincidence: every corpus
was built the same way, from the bank's own public pages, and those pages
describe products the bank wants to sell rather than problems its customers
have. "The ATM took my money and did not give me cash" is among the highest-
volume contact reasons at any retail bank, and not one tenant could answer it.

## What happened when the obvious fix was applied

A "When Something Goes Wrong" document was written for all four tenants —
grounded in EthSwitch's reversal rules and NBE's ten-business-day escalation
window, with no invented per-bank figures — and the measurement re-run.

**Gaps went from 66 to 70. Dashen fell from 69% to 63%.**

The document was not wrong; it was retrieved and it did answer the ATM
question. It also displaced correct answers elsewhere. With `top_k=4`, asking
"How do I receive money from abroad?" now pulls the disputes document into the
second slot, diluting the international-transfers text that used to answer it.

A second pass rewriting the document in customer vocabulary rather than bank
vocabulary — "someone withdrew money without your permission" instead of
"anything you did not authorise" — fixed the three questions that had returned
*zero* sources, because they had been failing the informativeness gate in
`retrieve()`. It also made the displacement worse.

## Decision

**Do not bulk-write documents into these corpora until retrieval capacity
grows with them, and measure every batch.**

The change was reverted rather than shipped. Content that the measurement says
makes the assistant worse overall does not ship on the strength of the topic
being important — and this topic *is* important, which is exactly the pressure
the measurement exists to resist.

Two things follow.

**`top_k=4` is a corpus-size assumption, not a constant.** It was reasonable
for fifteen documents. A corpus of a hundred cannot grow one document at a time
under a fixed four-slot budget without documents fighting each other for the
same answer. Raising it, or making it a function of corpus size, is a design
decision with real cost — more retrieved text is more tokens and more chance of
diluting a good match — and it belongs to the founder, not to a session tidying
up. **It is the prerequisite for the corpus work, not a side quest.**

**The informativeness gate stays as it is.** Three questions returned nothing
because the gate refused a weak match, and the gate's own docstring says it must
not be loosened because a plausible-looking wrong answer costs a bank deal. That
is correct. The fix for a missed match is the document's wording, not a lower
bar.

## Consequences

- **CLAUDE.md's "corpus is the ceiling" paragraph is now qualified** rather
  than removed. It is still true that content matters more than prompt tuning;
  it is no longer true that adding content is monotonically good.
- **`scripts/corpus_gaps.py` is the gate for corpus work.** Any batch of
  documents is measured before and after, and a batch that raises the gap count
  does not ship. The script is deliberately English-only: the corpus is
  English-dominant, so English questions isolate content coverage from language
  handling, which the phrasebook and cross-language tests already cover.
- **The disputes content is still owed.** It is the clearest gap in the
  product and it is written; it is parked until the retrieval budget can carry
  it, not abandoned.
- **A measurement that only counts `unanswered` is worthless here**, and the
  first version of this script proved it by reporting CBE at 100% covered.
  `unanswered` fires only when retrieval returns zero documents, and BM25
  always returns something — it scored a pass on "can I set up a standing
  order" while returning the 50/30/20 budgeting document. Retrieval returning
  *a* document is not the corpus containing *the* answer.
