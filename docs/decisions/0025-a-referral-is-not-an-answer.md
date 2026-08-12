# ADR-0025 — A referral is not an answer

**Status:** accepted · **Date:** 2026-08-12 · **Corrects a defect exposed by
ADR-0023**

## Context

Minutes after ADR-0023 shipped, the founder tested the live CBE demo with the
exact question that change was written for:

> my mobile banking app is not working, what should I do?

The routing worked. The message classified as `SERVICE_ISSUE`, skipped the
complaint branch, reached retrieval, found four documents, and answered:

> For help with your mobile banking app, you can reach CBE's e-payments
> support at epaymentsupport@cbe.com.et.

The verdict — *"this is bad, really bad… redirecting users to send an email is
not helpful"* — is correct, and the temptation is to file it as a corpus
problem. It is not, or not only. **The retrieved context contained a usable
answer and the model passed over it.** In the same document, in the same
chunk as that email:

> If you cannot use the app, standard mobile banking services are also
> available by dialing \*889# from your registered phone number.

A customer locked out of the app could have been given a working alternative
channel. They were given an inbox instead.

Two things were wrong at once:

1. **The model preferred the referral to the step.** Nothing in
   `_SYSTEM_PROMPT` said which to reach for, and "keep answers short" pushed
   toward the one-line version. The shortest answer and the useful answer
   were different sentences in the same paragraph.
2. **A referral passed the decline test.** Rule 1 already said context merely
   *on a similar topic* is not an answer — but a support address does not
   feel off-topic, it feels responsive. It reads like helping while helping
   with nothing.

The second is the more damaging, because a decline here is not a failure: it
routes to `answer_from_general_knowledge`, and first-line app troubleshooting
is *exactly* what that bounded exception exists for. Check the connection,
close and reopen, install the pending update, restart the phone — identical on
every banking app ever written, no figure, no bank-specific claim. The
assistant had a genuinely useful reply available and shipped an email address
in front of it.

## Decision

**Two rules added to `_SYSTEM_PROMPT`.**

*Steps beat referrals.* When the customer asks how to do or fix something and
the context holds a workaround, an alternative channel or a self-service
option, that is the answer. A phone number, an email address or "visit a
branch" is a last resort offered *after* the steps, never instead of them.

*A referral alone is a decline.* If the only relevant thing the context offers
is a contact detail, the question has not been answered — return
`INSUFFICIENT_CONTEXT`. The prompt says why in the words of the failure:
telling a customer whose app has stopped working to send an email is the
assistant giving up while appearing to answer.

"Keep answers short" is now qualified: short never means dropping a step the
customer needs.

**`_GENERAL_PROMPT` is told it may troubleshoot an app**, with the steps named
so the model does not have to guess whether they fall inside the boundary. The
figure-free, nothing-bank-specific constraints are untouched, and a test pins
that the clause did not widen them.

## Consequences

- The decline rate will rise, deliberately. Some of those turns become
  general guidance, some become handoffs. Both beat a referral: general
  guidance is useful, and a handoff is a promise somebody is on the hook
  for, which an email address is not.
- **These are prompt changes, and a prompt cannot be unit-tested from a
  sandbox with no model.** What is tested is everything downstream of the
  decline — general guidance is reached, it carries no sources and is
  labelled, the content gap is still filed, and a second decline still gets
  the customer a person. Plus text assertions that the rules are present, so
  a rule written in response to a live defect cannot be silently deleted.
  **The prompt's own behaviour needs a live check**: ask the deployed widget
  the question at the top of this ADR and confirm the reply names \*889#, or
  gives universal steps, rather than an email.
- **The durable fix is still content.** CBE's 23 documents contain no
  troubleshooting material at all — no "not working", no reset, no reinstall.
  Universal steps are a floor under that gap, not a substitute for the bank
  publishing "what to do when the app will not open". The handoff filed on
  the general-knowledge path is what puts it in front of them.
- Rule numbering in `_SYSTEM_PROMPT` shifted; nothing keys off the numbers.

## References

- `_SYSTEM_PROMPT` rules 2–3 and the troubleshooting clause in
  `_GENERAL_PROMPT` (`llm.py`)
- `tests/test_referral_is_not_an_answer.py`
- ADR-0023 (the routing change that exposed this), and the
  general-knowledge boundary in `CLAUDE.md`
