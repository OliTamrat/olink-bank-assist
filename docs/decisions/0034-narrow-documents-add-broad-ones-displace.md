# ADR-0034 — Narrow documents add, broad ones displace

**Status:** accepted · **Date:** 2026-08-14
**Supersedes the remedy in ADR-0033**, whose finding stands and whose
explanation was wrong.

## What ADR-0033 got right and wrong

Right: the corpus has real, measurable holes — 66 gaps across four tenants on
52 real customer questions, with "disputes and problems" 5 of 6 unanswered on
every tenant identically. And right: writing the obvious document to fill the
largest hole made the product **worse**, 66 gaps to 70.

Wrong: the mechanism, and therefore the remedy. ADR-0033 said the new document
"competed for the four slots" of `top_k=4`, concluded that `top_k` is a
corpus-size assumption blocking corpus growth, and put that decision on the
founder as a prerequisite.

**None of that survived measurement.** `scripts/topk_sweep.py` was written to
size the change and returned an identical row seven times — 142 answered at
`top_k=2` and at `top_k=12`. The reason is `MAX_FALLBACK_CHUNKS = 2` in
`agent.py`: the extractive answer is built from the top **two** chunks, so
`top_k` above two changes the sources list and nothing a customer reads.

Sweeping the parameter that does govern the answer gives the real shape
(measured at the 66-gap baseline, before the narrow document below went
in — re-running it now reads two higher throughout and identical in
shape):

| budget | answered / 208 | coverage | chars per answer |
|---|---|---|---|
| 2 | 142 | 68% | 720 |
| 4 | 143 | 69% | 1,023 |
| 6 | 144 | 69% | 1,223 |
| 12 | 144 | 69% | 1,439 |

**Going from two chunks to twelve buys two answers out of 208 and doubles the
reply text.** The retrieval budget is not the constraint, it was never worth a
founder decision, and corpus work was never blocked behind one.

## What actually happened

The document that made things worse was one long page covering ATM faults,
wrong transfers, unauthorised debits, resolution timelines and NBE escalation.
That breadth is what did the damage: a document touching many topics shares
vocabulary with many queries, so it outscores the *right* document for
questions it should have lost. "How do I receive money from abroad?" started
retrieving the disputes page ahead of the international-transfers page.

Rewritten as a single narrow document — **ATM debited, no cash, and nothing
else** — the same facts and the same sources give the opposite result:

| | baseline | broad version | narrow version |
|---|---|---|---|
| gaps | 66 | **70** | **64** |
| CBE | 69% | 67% | **71%** |
| demo | 67% | 69% | **69%** |

No tenant regressed. The content was never the problem; its scope was.

## Decision

**One document, one question.** A corpus document should answer the thing a
customer asked and stop. Breadth is not generosity here — it is a document
volunteering itself for queries it cannot answer well, at the direct expense of
the document that could.

Concretely, for anyone adding to a tenant corpus:

- **Title it as the question**, not as a topic area. "ATM Took My Money But
  Gave No Cash" retrieves; "When Something Goes Wrong" competes with
  everything.
- **Split rather than append.** Five narrow documents beat one page with five
  sections, even though the second is less work to write and reads better on a
  website. This corpus is not a website.
- **Use the customer's words.** Three questions returned *zero* sources against
  the broad draft because it said "anything you did not authorise" where the
  customer says "someone withdrew money without my permission" — they failed
  the informativeness gate in `retrieve()`. The gate is right; the wording was
  wrong.
- **Measure before and after.** `scripts/corpus_gaps.py`. A batch that raises
  the gap count does not ship, whatever its topic.

## Consequences

- **`top_k=4` and `MAX_FALLBACK_CHUNKS=2` stay.** Neither is the ceiling, and
  raising either costs tokens on a per-conversation cost model for ~1% of
  coverage.
- **Corpus growth is unblocked and needs nothing from the founder** — the
  opposite of ADR-0033's conclusion, and the reason this ADR exists rather than
  an edit to that one.
- **The disputes document ships** in its narrow form, on all four tenants,
  taking the corpus from 66 gaps to 64.
- **The remaining measured gaps are the backlog**, in the order the script
  prints them, each written narrow and each measured. Fees and charges, cards,
  account opening and KYC, loans and account maintenance are the categories
  still carrying holes.
- **A sweep that returns the same number seven times is a broken sweep, not a
  flat curve.** That is what identified the wrong mechanism here, and it is
  worth remembering the next time a parameter appears not to matter.
