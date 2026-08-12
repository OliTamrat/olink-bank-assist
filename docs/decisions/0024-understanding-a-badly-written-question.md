# ADR-0024 — Understanding a question the customer could not write well

**Status:** accepted · **Date:** 2026-08-12

## Context

The founder's framing, and it is a market fact rather than a UX nicety:
Ethiopia is onboarding tens of millions of first-time digital banking users,
and many of them will not construct a well-formed sentence. Misspellings,
two- and three-word fragments, words in the wrong order, no punctuation,
often in a second language. **How does the assistant help them refine the
message and get the information they need?**

Retrieval here is lexical BM25, which is unforgiving of all four. The obvious
expectation is that a badly-typed question finds nothing. Measured against
the seeded 23-document CBE corpus, that expectation is wrong, and the truth
is worse:

```
'how open acount'  ->  Transfers to Telebirr and Other Wallets
(well-formed)      ->  Ordinary Savings Account
```

The typo kills `acount`. What survives is `open`, which matches "open" in an
unrelated document. **Retrieval succeeds — confidently — on the wrong
thing.** The model then reads that document, correctly judges it does not
answer the question, declines, and the customer is escalated to a teller.

Across a set of twenty-one well-formed/as-typed pairs, 100% of the
well-formed questions retrieved content and 76% of the as-typed ones did —
but the 76% is a misleading comfort, because "found content" and "found the
*right* content" are different measurements and only the second one matters.

So the low-literacy failure mode is not silence. It is *wrong document →
model declines → teller*, which from inside the system is indistinguishable
from correct operation. It would never be reported as a bug, and the
population it hits hardest is precisely the one the product exists to serve.

## Decision

**Two layers, on the failure path only.**

**1. Refine, silently.** `llm.refine_for_search(message)` rewrites the
message as a clear search query **in the customer's own language**, and
retrieval runs again. It triggers on both shapes of failure — nothing
retrieved, *and* the model declining what was retrieved — because the second
is the one bad typing actually produces. It returns the sentinel
`ALREADY_CLEAR` when the message needs no help or when the model genuinely
cannot tell what was meant; guessing there would send a confidently
irrelevant answer, which is worse than asking.

This mirrors `translate_for_search` deliberately, and the shared doctrine is
what makes it safe: **only the search text is rewritten.** The answer is
still generated from whatever documents come back, the informativeness gate
still applies, and the model may still decline. A bad rewrite therefore costs
a miss, never a wrong answer.

**2. Ask, if still unsure.** Rather than fetching a person, offer the
near-miss document titles — real titles, `suggest_topics` invents nothing —
and let the customer answer by **tapping**. The widget already renders each
as a button that re-asks it. That is the whole point: the person who most
needs this is the person who cannot easily rephrase, so the offer must not
require them to type again.

**The gate on layer 2 is that layer 1 produced something DIFFERENT**, and
choosing that took one wrong turn first. Clarifying on every miss looked
obviously right and is not: a customer who writes a perfectly clear question
the bank simply has no content for ("what is your SWIFT code for the Djibouti
branch") would get "did you mean one of these?" — the assistant blaming their
typing for its own content gap. It also silently rewrote the contract for
every existing miss; 87 tests said so, which is exactly what that suite is
for. A non-empty rewrite is the model's own verdict that the message was
unclear, and that is positive evidence rather than an assumption about the
customer.

**One clarification per conversation** (`MAX_CLARIFY_ASKS`). A second is an
interrogation and a loop — it is prompted by the same failure as the first,
so nothing about it goes better. Counted, not ordered: two messages written
in one turn have no reliable order between them, and a UUID tiebreak is
arbitrary rather than chronological. Same shape as `MAX_CONTACT_ASKS`.

**The clarify turn files a handoff with `needs_person=False`.** Both halves
are load-bearing and pull in opposite directions. Filed, because "our content
did not match how this customer writes" is real content-gap information and
is invisible anywhere else. Not `needs_person`, because nobody is waiting for
a callback, and a queue that fills with questions nobody has understood yet
is a queue an operator cannot work — the same failure the
general-knowledge path was corrected for. `handoff_created` on the result is
`False`: that flag is how a channel promises a follow-up, and this turn
promises the opposite.

**`CLARIFYING` is not `SUBSTANTIVE`.** It is a step inside answering one
question, like the contact exchange. Counting it would make a customer who is
asked and then answered appear in the denominator twice, quietly deflating
the deflection rate every time the product does the right thing.

## Consequences

- **Extractive mode is unchanged by this feature, and that is a real cost
  stated rather than hidden.** Both halves need the model — the rewrite
  obviously, and the clarifying question because the rewrite's own verdict
  gates it. With no backend configured a miss takes precisely the path it
  took before. The alternative was a rules-only guess at "did this person
  type badly", which is the assumption this feature must not make.
- One extra model call per failed turn. Answered turns pay nothing, and a
  test pins that.
- A new outcome and a new handoff reason mean new analytics surface; both
  have admin labels, and `test_admin_labels.py` enforces it.
- **The rewrite itself is stubbed in tests, not exercised.** Reaching a real
  Gemini is impossible from a sandbox. Everything downstream of the stub is
  real — retrieval, the gate, the answer — but the prompt's actual behaviour
  on real bad input is unverified, and this repo has shipped an inert model
  path before for exactly that reason (`translate_for_search`, the 64-token
  bug). **First live check should be a handful of real fragments through the
  deployed widget.**
- The corpus is still the ceiling. This recovers questions the documents can
  already answer from customers who could not phrase them; it creates no
  answers that were not there.

## References

- `llm.refine_for_search` / `NOTHING_TO_REFINE`; the `refined` block and the
  `CLARIFYING` branch in `agent.handle_message`
- `tests/test_understanding_the_question.py` — including the case that made
  the first gate wrong, and the extractive-mode fallback
- ADR-0023 (the escalation work this continues), and the
  `translate_for_search` precedent for rewriting only the search text
