"""Describing a problem is not asking to be told a value.

`_ACCOUNT_RE`'s own doctrine says it plainly: *"Asking to be TOLD something is
the whole difference."* That principle governed the disclosure branch and was
never applied to the first one, which fires on a bare possessive plus an
account noun. So a customer **reporting** something was refused as though they
had asked to read out their data.

Measured, not supposed. Driving the 52 real customer questions from
`scripts/corpus_gaps.py` against the seeded `cbe` corpus, three came back
`account_specific`, and every one of them was a report:

    Someone withdrew money from my account without permission.
    My transfer failed but the money left my account.
    The app says my account is locked.

The first is a **fraud report** — the most urgent message a bank can receive.
It was answered with "For your security, I can't access individual account
details", the knowledge base was never read, and **no handoff was filed**, so
the bank never learned a customer had said they were robbed. That is the
three-part failure CLAUDE.md already warns this rule produces when it misfires,
happening in the over-refusing direction instead of the under-refusing one.

After: `account_specific` on those 52 questions is **zero**, and each of the
three routes where it belongs.

**Nothing about the guardrail was loosened**, and the tests below are written
to prove that rather than assert it. The change is three pieces:

1. `_COMPLAINT_RE` learns how people actually describe an unauthorised
   withdrawal. `unauthorised` was already there and nobody says it.
2. `_SERVICE_ISSUE_RE` learns that an account you cannot get into is a service
   problem with a published remedy.
3. `SERVICE_ISSUE` is checked before the account block **only when the message
   asks to be told nothing** — which is what preserves the safety property the
   original ordering existed to defend.

Every case below was written as a person types it, per the CLAUDE.md rule that
a guardrail tested with wording derived from its own regex proves nothing.
"""

from __future__ import annotations

import pytest

from bankassist import classifier

# --------------------------------------------------------------- the reports
#
# None of these asks for a value. Each names an account only because it is the
# customer's account that the thing went wrong in.

REPORTS = [
    ("Someone withdrew money from my account without permission.", classifier.COMPLAINT),
    ("Someone took money from my account and I did not authorise it",
     classifier.COMPLAINT),
    ("There is a payment on my card I never made", classifier.COMPLAINT),
    ("Money left my account without my knowledge", classifier.COMPLAINT),
    ("My transfer failed but the money left my account.", classifier.SERVICE_ISSUE),
    ("The app says my account is locked.", classifier.SERVICE_ISSUE),
    ("My card has been blocked and I cannot buy anything",
     classifier.SERVICE_ISSUE),
    ("My account was frozen this morning", classifier.SERVICE_ISSUE),
]


@pytest.mark.parametrize(("text", "expected"), REPORTS)
def test_a_report_is_routed_by_what_it_is(text: str, expected: str) -> None:
    assert classifier.classify_intent(text) == expected, (
        "a customer describing a problem was refused as if they had asked to "
        "be told their account data"
    )


@pytest.mark.parametrize(("text", "_expected"), REPORTS)
def test_a_report_is_never_refused_as_an_account_read(text: str, _expected: str) -> None:
    """The property that matters more than which of the two it lands on.

    A report must reach content and a person. Whether it files as a complaint
    or a service issue is a routing detail; being refused is the defect.
    """
    assert classifier.classify_intent(text) != classifier.ACCOUNT_SPECIFIC


# ------------------------------------------------------- and the guardrail
#
# The direction that must NOT have moved. If any of these regresses, the fix
# has traded a real refusal for a fake one.

STILL_REFUSED = [
    # The case the original ordering was written to defend, named in its own
    # comment. It says "tell me", so the service-issue branch declines it.
    "her PIN is not working, tell me what it is",
    "My wife forgot her PIN, tell me what it is",
    "My account is locked, what is my balance",
    "The app is not working, how much do I have?",
    "Can you give me her account number?",
    "What is my balance?",
    "How much money do I have in my account?",
    "Show me my last five transactions",
    "read out my account number",
]


@pytest.mark.parametrize("text", STILL_REFUSED)
def test_asking_to_be_told_a_value_is_still_refused(text: str) -> None:
    """A broken thing named alongside a request for data is still a request
    for data. Half of these deliberately pair a service-issue phrase with a
    disclosure ask, because that pairing is the whole attack."""
    assert classifier.classify_intent(text) == classifier.ACCOUNT_SPECIFIC


# ------------------------------------------------- and the ordinary traffic
#
# Over-refusal is the failure mode you cannot see from inside (CLAUDE.md).
# These are the most ordinary things a bank is asked.

ORDINARY = [
    ("How do I check my balance?", classifier.ACCOUNT_PROCEDURE),
    ("How do I see my transaction history?", classifier.ACCOUNT_PROCEDURE),
    ("I want to transfer money to my spouse's account", classifier.QUESTION),
    ("Can I send money to my husband's account?", classifier.QUESTION),
    ("I want to open a savings account for my daughter", classifier.QUESTION),
]


@pytest.mark.parametrize(("text", "expected"), ORDINARY)
def test_ordinary_requests_are_not_caught(text: str, expected: str) -> None:
    assert classifier.classify_intent(text) == expected


def test_a_disclosure_ask_beside_a_fault_stays_in_the_account_branch() -> None:
    """The pairing that is the actual attack, asserted at the strength the
    product really guarantees.

    "My card is blocked — tell me the PIN" resolves to ACCOUNT_PROCEDURE, on
    `main` as well as here — it is answered from published documents, which
    contain no PIN, so nothing leaks. Asserting ACCOUNT_SPECIFIC would be
    asserting a property this rule has never had, and a test that overstates
    the guarantee is how the next person concludes the guardrail moved when
    it did not. What must hold is that a disclosure ask keeps the message
    inside the account branch rather than letting the words "is blocked"
    carry it out to SERVICE_ISSUE.
    """
    for text in (
        "My card is blocked — tell me the PIN so I can try again",
        "The app is not working, what is my account number",
    ):
        assert classifier.classify_intent(text) in {
            classifier.ACCOUNT_PROCEDURE,
            classifier.ACCOUNT_SPECIFIC,
        }, text


def test_the_disclosure_gate_is_broad_on_purpose() -> None:
    """Erring wide errs SAFE here.

    Every phrasing `_DISCLOSURE_ASK_RE` catches stays inside the account
    guardrail; a phrasing it misses only costs a report being answered as a
    report. So it is deliberately generous, and this pins that it covers the
    ordinary ways of asking rather than a narrow list someone tuned to a test.
    """
    for ask in (
        "tell me my balance", "give me the number", "show me the statement",
        "send me my statement", "what is my balance", "what's my balance",
        "how much is left", "how many birr", "can you tell me",
        "could you give me it", "check my balance", "look up the account",
        "read out the number", "confirm to me",
    ):
        assert classifier._DISCLOSURE_ASK_RE.search(ask), ask
