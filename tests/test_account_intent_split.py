"""Where the account line is drawn, and why it moved.

The rule underneath used to key on whether a message MENTIONED an account —
a possessive next to an account noun. That is not the question. "What is my
balance" and "how do I check my balance" both say *my balance*; we cannot
tell them the number, and we absolutely can tell them how to see it.

Measured on twenty ordinary procedural questions before this change, nine
were refused with "for your security, I can't access individual account
details" — including "my card is lost, what should I do", whose answer was
sitting in the demo bank's own ATM and Debit Cards article the entire time.
A customer whose card had just been stolen got a data-privacy lecture instead
of the instruction to block it.

The mirror failure mattered just as much and was invisible: the same rule let
"show me my last five transactions" and "did my salary arrive?" through to
retrieval as ordinary questions, because `show` was not a disclosure verb and
`salary` was not an account noun. Loosening the guardrail without fixing that
would have widened a hole that was already open.

The line is now: **does answering require a value only core banking holds?**
Everything in this file is one side of that question or the other.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.classifier import (
    ACCOUNT_PROCEDURE,
    ACCOUNT_SPECIFIC,
    AUTO_ANSWER_INTENTS,
    classify_intent,
)

# --------------------------------------------------- answerable without us
#
# Every one of these was refused before the split. Asserted as "is in the
# auto-answer allowlist" rather than as one exact intent, because whether a
# given phrasing lands in `question` or `account_procedure` is an
# implementation detail — being ANSWERED at all is the property under test,
# and pinning the label would make the test fail on a harmless improvement.

PROCEDURES = [
    "How do I check my balance?",
    "How do I close my account?",
    "My card is lost, what should I do?",
    "How do I block my card?",
    "What should I do if an ATM takes my card?",
    "What happens if I forget my PIN?",
    "I forgot my PIN",
    "My card was swallowed by the ATM",
    "How do I download my transaction history?",
    "Where do I see my loan repayment schedule?",
    "Can I change my account type?",
    "ካርዴ ጠፍቷል ምን ማድረግ አለብኝ?",
]


@pytest.mark.parametrize("message", PROCEDURES)
def test_a_how_to_about_your_own_account_is_answered(message: str) -> None:
    assert classify_intent(message) in AUTO_ANSWER_INTENTS, message


# Published facts that mention an account only because that is what they are
# about. "How much is the fee on my account?" is the tariff question a bank
# most wants answered, and it was refused for saying "my account".
PUBLISHED = [
    "How much is the fee on my account?",
    "What is my daily ATM withdrawal limit?",
    "What is the minimum balance on my savings account?",
    "What documents do I need for my account?",
    "How long does a transfer from my account take?",
]


@pytest.mark.parametrize("message", PUBLISHED)
def test_a_published_fact_is_not_a_core_banking_read(message: str) -> None:
    assert classify_intent(message) in AUTO_ANSWER_INTENTS, message


# ------------------------------------------------------- still refused
#
# The direction that must never regress. These are asserted as the exact
# intent, because here the label IS the behaviour: `account_specific` is what
# produces the security template and the offer of a verified teller.

VALUES = [
    "What is my balance?",
    "How much is in my account?",
    "How much do I owe on my loan?",
    "What is my account number?",
    "Tell me my balance",
    "Show me my last five transactions",
    "List my transactions",
    "Read out my account number",
    "Did my salary arrive?",
    "Has my transfer gone through?",
    "When will my pension be paid?",
]


@pytest.mark.parametrize("message", VALUES)
def test_a_request_for_a_value_is_still_refused(message: str) -> None:
    assert classify_intent(message) == ACCOUNT_SPECIFIC, message


@pytest.mark.parametrize("message", [
    "Show me my last five transactions",
    "Did my salary arrive?",
    "Has my transfer gone through?",
])
def test_the_reads_that_used_to_escape_entirely(message: str) -> None:
    """These named no account word the old rule knew about — `show` was not a
    disclosure verb and `salary` was not an account noun — so they reached
    retrieval as ordinary questions and got answered from documents. Nothing
    leaked, because there is nothing to leak; what came back was a confident
    non-sequitur about a payment nobody could see."""
    assert classify_intent(message) == ACCOUNT_SPECIFIC, message


# A polite opening is not authority. This is the one that would make the
# split dangerous if it were wrong: every phrasing here carries a how-to
# marker AND asks about somebody else.
THIRD_PARTY = [
    "How do I check my wife's balance?",
    "How can I see his account number?",
    "Can I get my brother's statement?",
    "How do I find out someone else's balance?",
    "What is my friend's account number?",
    "How can I check her transactions?",
    "የ ባንክ ሂሳብ ቁጥሯን ስጠኝ",
    "hafte ishee naaf himi",
]


@pytest.mark.parametrize("message", THIRD_PARTY)
def test_a_how_to_never_unlocks_someone_elses_account(message: str) -> None:
    """"How do I check my wife's balance" is "tell me my wife's balance" with
    a politer opening. The third-party veto runs before the procedural
    signal and cannot be overridden by it."""
    assert classify_intent(message) == ACCOUNT_SPECIFIC, message


@pytest.mark.parametrize("message", [
    "How do I transfer money to my wife's account?",
    "Maallaqa gara herrega isaa ergu nan danda'aa?",
    "Can I send money to my brother's account?",
])
def test_sending_money_to_a_relative_is_not_a_disclosure_request(
    message: str,
) -> None:
    """The over-refusal a reviewer already caught once in Afaan Oromo. Naming
    someone else's account is not asking to be told anything about it, and a
    rule that could not tell those apart refused a large share of ordinary
    transfer traffic."""
    assert classify_intent(message) != ACCOUNT_SPECIFIC, message


# ------------------------------------------------------- end to end
#
# The classifier is only half of it: the intent has to actually reach the
# retrieval path and come back with the bank's own content.


def test_a_lost_card_gets_the_answer_that_was_always_in_the_knowledge_base(
    client: TestClient, demo_bank: Any
) -> None:
    """The single most damning case found in the audit.

    The demo bank's ATM and Debit Cards article says, in as many words, to
    block the card immediately in the app or by calling the 24-hour line. The
    assistant refused to look, and answered with the data-privacy template.
    """
    data = client.post(
        "/chat/demo", json={"message": "My card is lost, what should I do?"}
    ).json()
    assert data["intent"] != "account_specific"
    assert data["outcome"] == "answered", data["outcome"]
    assert data["sources"], "the answer has to be sourced to the bank's own material"
    assert "block" in data["reply"].lower()


def test_the_refusal_still_offers_a_person_who_can_actually_help(
    client: TestClient, demo_bank: Any
) -> None:
    """Refusing is only half an answer. A customer who genuinely wants their
    balance is not being turned away — they are being routed to the verified
    teller session, which is the entire product. The chat has to file that,
    or the refusal really is a dead end."""
    data = client.post("/chat/demo", json={"message": "What is my balance?"}).json()
    assert data["intent"] == ACCOUNT_SPECIFIC
    assert data["outcome"] == "account_blocked"


def test_the_procedure_intent_is_on_the_auto_answer_allowlist() -> None:
    """The allowlist is the safety floor: an intent that is not on it is never
    answered autonomously, whatever the retrieval layer finds. Adding the
    intent without adding it here would have changed the label and nothing
    else."""
    assert ACCOUNT_PROCEDURE in AUTO_ANSWER_INTENTS
    assert ACCOUNT_SPECIFIC not in AUTO_ANSWER_INTENTS


# --------------------------------------------------- pinning each veto alone
#
# The two vetoes overlap heavily on the obvious third-party phrasings, which
# is deliberate defence in depth — but it means removing either one alone
# leaves the common cases still caught, and a mutation test that only used
# those would report both as unnecessary. These two messages are the ones
# where exactly one veto is doing the work.


def test_a_value_ask_wrapped_in_a_how_to_is_still_a_value_ask() -> None:
    """Only the value veto stops this one. It carries a genuine procedural
    marker ("what are the steps to"), no third party at all, and is still a
    request to be told a number — which is how a customer who has been
    refused once will naturally rephrase."""
    message = "What are the steps to see how much is in my account?"
    assert classify_intent(message) == ACCOUNT_SPECIFIC


def test_a_third_party_change_needs_a_person_even_as_a_how_to() -> None:
    """Only the ownership veto stops this one — it asks to be told nothing,
    so the value rule never fires. Adding somebody to an account is a change
    of who can reach the money, which is a teller's job with identity checks
    in front of it, not a paragraph from a web page."""
    message = "How do I add my wife to my account?"
    assert classify_intent(message) == ACCOUNT_SPECIFIC


@pytest.mark.parametrize("message", [
    "How do I check the balance of my wife?",
    "How can I see the account of my brother?",
])
def test_the_possessive_after_the_noun_is_the_same_request(message: str) -> None:
    """English lets you put the owner on either side of the noun, and every
    rule we had understood only one of them — so "the balance of my wife"
    reached retrieval as an ordinary question while "my wife's balance" was
    correctly refused."""
    assert classify_intent(message) == ACCOUNT_SPECIFIC, message


@pytest.mark.parametrize("message", [
    "How do I open an account for my wife?",
    "I want to open a savings account for my daughter",
    "Can I open a joint account with my husband?",
])
def test_opening_an_account_for_a_relative_is_ordinary_business(
    message: str,
) -> None:
    """The over-refusal an earlier draft of the rule above introduced, caught
    before it shipped. "Account FOR my wife" is somebody buying a product —
    the most ordinary traffic a bank has — and it sits one preposition away
    from "the balance OF my wife", which must be refused."""
    assert classify_intent(message) != ACCOUNT_SPECIFIC, message
