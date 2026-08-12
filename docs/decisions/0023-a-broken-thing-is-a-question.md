# ADR-0023 — A broken thing is a question, not a grievance

**Status:** accepted · **Date:** 2026-08-12

## Context

The founder's report: *"we've become too restrictive for AI, failing to
effectively classify potential escalations and non-escalations… issues that
can be resolved promptly while AI assistance is available are often escalated
unnecessarily."*

The obvious suspect was the informativeness gate in `retrieval.py` — the
component `CLAUDE.md` warns hardest about, and the one a session would
naturally reach for. **It was measured and it is not the cause.** Thirty-five
ordinary customer questions ("how do I open a savings account", "what happens
if I lose my debit card") were driven through the real agent path against the
seeded 23-document CBE corpus in extractive mode:

```
outcome        n     %
answered      35   100%
```

Zero misses. Had that hypothesis been acted on instead of tested, the gate
that stops confidently-wrong answers would have been loosened for nothing.

A second probe found the actual cause. Sixteen answerable messages, plus
eight controls that should escalate:

```
answerable messages routed to a person anyway: 9 / 16
```

Five of those nine turned on **one token**. `not working` sat inside
`_COMPLAINT_RE`, in a list otherwise made of *stole*, *stolen*, *scammed*,
*terrible*, *worst* and *complaint*. Replacing it with "having trouble" got
the identical sentence answered.

The structural half matters more than the regex. `COMPLAINT` is checked
*before* retrieval and its branch files a handoff, acknowledges, asks for a
phone number and **returns** — so the bank's own troubleshooting document is
never read. The assistant was not failing to *find* an answer; it was
deciding not to *look*.

The framing that settles it is the founder's: we hold no core banking access
and are not trying to. The line therefore cannot be *how annoyed does this
sound* — it is **is the answer inside the bank's own knowledge?** If it is,
answer it.

## Decision

**A new intent, `SERVICE_ISSUE`, for things that are broken.** `not working`,
`failed transfer`, cannot-log-in, error-message and was-declined move out of
`_COMPLAINT_RE` into `_SERVICE_ISSUE_RE`. The distinction is what the
customer wants, not their tone: a grievance wants redress from a person, a
service issue wants the thing to start working — and that is an instruction,
which is the request a bank is most likely to have already written down.

**It is checked AFTER the account block, and that ordering is the decision,
not an implementation detail.** A service issue is answered from the
documents, so checking it first would let "her PIN is not working, tell me
what it is" jump the account guardrail on the strength of two words. The
first draft of this change did exactly that, and every smuggling case in
`tests/test_service_issue.py` passed straight through. Nothing is lost by the
later position: a broken thing that names an account ("my card is not
working") already resolves to `ACCOUNT_PROCEDURE`, which is answered from the
documents too.

**Theft and fraud do not move.** `missing money` and `lost my money` stay in
`_COMPLAINT_RE` deliberately, despite being reported as an over-escalation in
the probe: money that has genuinely gone missing can be fraud, and being
wrong there costs far more than one extra step to a person. This intent is
for things that are *broken*, not money that is *gone*.

**A service issue with no documented fix still reaches a person** — with its
own wording (`service_issue_ack`) and its own reason code
(`REASON_SERVICE_ISSUE`). "I don't have verified information about that yet"
is a non-answer to "my card was declined": the customer did not ask for
information. The separate reason also matters operationally — a content gap
is answered by writing a document, an outage needs somebody this morning.

**`what do I need to …` becomes procedural.** "What do I need to close my
account?" was refused as account-specific: it names an account and matched
none of the how-to patterns. It contains no request for a value at all. The
`_VALUE_ASK_RE` veto still runs first, so the phrasings that *do* carry a
value request ("what do I need, just tell me my current balance") are still
refused.

## Consequences

- Over-escalation on the probe set drops from **9/16 to 2/16**, with every
  control — theft, fraud, complaints, balance requests, requests for a human
  — still escalating. The two that remain are deliberate: a password reported
  as wrong (account-adjacent) and money reported missing (possible fraud).
- **One reclassification is genuinely ambiguous and is pinned with its
  reasoning** rather than buried: "what do I need to know my balance" moves
  from `ACCOUNT_SPECIFIC` to `ACCOUNT_PROCEDURE`. Read plainly it asks what
  is *required in order to* see a balance. If a native reviewer reads it the
  other way, `test_what_do_i_need_to_know_my_balance_is_now_a_procedure` is
  the test to flip and the fix is a `_VALUE_ASK_RE` alternative.
- The non-English `_SERVICE_ISSUE_RE` alternatives are **first-pass and
  unreviewed**, the same status the Somali and Swahili guardrail lines carry.
  They change no routing today — those phrasings already reached the ordinary
  question path — so they are a consistency measure, not a behaviour change,
  and a wrong guess costs nothing until it is reviewed.
- `SERVICE_ISSUE` joins `CURATABLE_INTENTS`. "My app is not working" is the
  most curatable question a bank has, and it was unreachable: as a
  `COMPLAINT` it never got near the curated lookup.
- A new outcome means new analytics surface. `SUBSTANTIVE` gains it (so it
  lands in every rate) and `RESOLVED` deliberately does not (reaching this
  outcome means nobody had a fix).
- **What is NOT addressed, and is the honest remaining unknown:** how often
  the model itself declines with `INSUFFICIENT_CONTEXT` on thin retrieved
  context. That needs a live Gemini call and no agent sandbox has one. It may
  be a third contributor and is untested either way.
- The corpus is still the ceiling. This recovers questions 23 documents can
  already answer; it creates no answers that were not there.

## References

- `_SERVICE_ISSUE_RE` and the ordering comment in `classifier.py`; the
  `broken` branch in `agent.py`
- `tests/test_service_issue.py` — including the smuggling cases that caught
  the ordering bug, and the negative direction on `_PROCEDURAL_RE`
- ADR-0021 (the insights work that led to the founder asking the question)
