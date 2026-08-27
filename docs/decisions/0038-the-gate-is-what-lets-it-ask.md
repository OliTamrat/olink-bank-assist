# ADR-0038: The informativeness gate is what lets the assistant ask, so it stays

**Date:** 2026-08-27
**Status:** Accepted
**Relates to:** ADR-0024 (refine and clarify), ADR-0033 (the corpus is the ceiling)

## Context

Founder direction, 2026-08-27: *"just because someone asks a question related
to account shouldn't be blocked… make the platform smarter and efficient — the
more calls we transfer to a live agent will cost time and money. Awash serves
over 15 million users and if 50,000 wanted a teller that is going to be
terrible."*

The economics are right and they are the product's whole case. So the guard
was measured rather than defended.

**Two of the three findings acted on.** Three of 52 real customer questions
were refused by the account rule, and every one was a *report* rather than a
request for data — including a fraud report that filed no handoff (fixed,
#185). The refusal itself then dead-ended, sending a customer to a branch
after a question the corpus could answer (fixed, #186: honest wording, plus
the bank's own near-miss questions as tappable chips).

**The third was the informativeness gate, and this ADR is why it did not
move.** It is the largest single cost — 25% of those questions are answered
with no sources at all, against 6% refused — so it looked like the obvious
lever.

## What was measured

`MIN_INFORMATIVE_RATIO` and `SHORT_QUERY_CONTENT_WORDS` swept against the 52
questions from `scripts/corpus_gaps.py` on the seeded `cbe` corpus, in
extractive mode:

| ratio | short | sourced /52 | correct /52 |
|---|---|---|---|
| **0.5** | **3** | **39** | **35** | ← current |
| 0.45 | 3 | 39 | 35 |
| 0.4 | 3 | 43 | 36 |
| 0.34 | 3 | 43 | 36 |
| 0.4 | 4 | 48 | 37 |
| 0.34 | 5 | 49 | 39 |
| 0.25 | 4 | 48 | 37 |

Ten more sourced answers looks like a clear win. Then the safety suites were
run at each setting — `test_{cbe,dashen,awash}_adversarial.py`,
`test_understanding_the_question.py`, and both eval suites. **Every candidate
broke 9–10 tests**, including the mildest, which moves only the ratio:

    test_endorsement_question_gets_honest_unknown_not_irrelevant_answer
    test_cross_tenant_probe_leaks_nothing_and_admits_unknown
    test_hostile_input_does_not_crash_or_return_a_non_sequitur
    …plus six in test_understanding_the_question.py

## Decision

**The gate stays at `MIN_INFORMATIVE_RATIO = 0.5`, `SHORT_QUERY_CONTENT_WORDS
= 3`.** Not from caution — from the second group of failures.

The first three are the gate's stated purpose and were expected: *"are you
officially endorsed by the bank?"* starts returning a confident, irrelevant
answer from a document that merely shares the word *bank*. That is the
plausible-but-wrong answer the safety doctrine exists to prevent.

**The six were not expected, and they invert the argument.** They are the
clarify path from ADR-0024 — *"did you mean this?"* — which is precisely the
behaviour the founder asked for in the same message. That flow fires **only
when the gate rejects**. The gate is how the assistant knows it did not
understand. Loosen it and the assistant does not ask a better question; it
stops asking at all and answers confidently instead.

So on this lever the intuition points backwards: loosening it makes the
product less able to be smart, not more.

`SHORT_QUERY_CONTENT_WORDS` is the sharper of the two and the more tempting,
because it moves coverage most. It is also the more dangerous: raising it lets
*more* queries bypass the ratio entirely, and the adversarial cases are five
to seven content words — exactly the band it would open.

## Consequences

- **Do not re-derive this.** The sweep is cheap to repeat and the conclusion
  has now been reached once with numbers; a future session asked to "loosen
  the guard" should read this before touching `retrieval.py`.
- **The 25% is a corpus problem**, which ADR-0033 already established by a
  different route: content moves the answer rate more than any tuning. The
  failures are questions like *"What happens if I miss a loan repayment?"* and
  *"Do you give loans to people without a salary?"* — no gate setting conjures
  a document that was never written.
- **The deflection levers that do work**, in order: the suggestion chips
  (#186, now on the refusal path as well as the miss path), the clarify flow
  (which needs the gate intact), and writing documents against the measured
  gap list.
- If the gate is ever revisited — for a much larger corpus, where document
  frequencies differ — the sweep must report **both** axes. A coverage number
  on its own is what made this look like a free win.
