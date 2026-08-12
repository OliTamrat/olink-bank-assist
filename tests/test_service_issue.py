"""A broken thing is a question, not a grievance.

`not working` and `failed transfer` lived in `_COMPLAINT_RE`, among *stole*,
*scammed*, *terrible* and *worst*. So "my mobile banking app is not working,
what should I do?" was filed as a complaint — which files a handoff, asks for
a phone number, and returns **without ever consulting the knowledge base**.
The bank's own troubleshooting document was sitting right there and was never
read.

Measured on the seeded CBE corpus before this change: of sixteen ordinary,
answerable customer messages, nine were routed to a person, and five of those
nine turned on the single token `not working`. Replacing it with "having
trouble" got the same sentence answered.

The founder's framing is the rule: we hold no core banking access, so the
line is not "does this sound annoyed" — it is "is the answer inside the
bank's own knowledge?" If it is, answer it.

What must NOT move, and is pinned below:

- theft and fraud still escalate, in every language;
- the account guardrail still runs FIRST, so "not working" cannot be used to
  smuggle a disclosure request past it;
- a service issue the documents cannot answer still reaches a person — with
  wording that matches what was said, and its own reason code so a bank can
  tell an outage from a content gap.
"""

from __future__ import annotations

import pytest

from bankassist import agent, classifier
from bankassist.classifier import classify_intent

ALIASES = ("cbe", "Commercial Bank of Ethiopia")


# Every one of these is a customer saying "the thing you gave me is broken".
# None is asking for redress; all of them have a documented answer at a real
# bank. Written the way people type, not the way the regex reads.
BROKEN = [
    "My mobile banking app is not working, what should I do?",
    "The ATM is not working at Bole branch",
    "Internet banking is not working on my phone",
    "Why is my mobile banking not working after I changed my phone?",
    "the app doesn't work",
    "your app isn't working since yesterday",
    "mobile banking stopped working",
    "I keep getting a failed transfer message",
    "my transfer failed twice today",
    "I can't log in to the app",
    "cannot sign in to internet banking",
    "unable to access my mobile banking",
    "the app shows an error message every time",
    "the payment was declined at the shop",
]


@pytest.mark.parametrize("text", BROKEN)
def test_a_broken_thing_is_not_a_complaint(text: str) -> None:
    assert classify_intent(text, ALIASES) != classifier.COMPLAINT


@pytest.mark.parametrize("text", BROKEN)
def test_a_broken_thing_reaches_the_knowledge_base(text: str) -> None:
    """The point of the whole change: these intents are answered from content.

    SERVICE_ISSUE and ACCOUNT_PROCEDURE both fall through to retrieval.
    Which of the two a given message lands on depends on whether it names an
    account, and either is correct — what matters is that neither returns
    before the documents are read.
    """
    assert classify_intent(text, ALIASES) in (
        classifier.SERVICE_ISSUE,
        classifier.ACCOUNT_PROCEDURE,
        classifier.QUESTION,
    )


# The controls. Every one of these must still summon a person.
GRIEVANCES = [
    "Someone stole money from my account",
    "I want to file a complaint about the service at Megenagna",
    "This is the worst bank I have ever used",
    "I was scammed and lost my money",
    "there is missing money from my account",
    "I am a victim of fraud",
    # The same, in each of the other five languages — theft is the most
    # urgent thing a customer reports and the reordering must not have
    # dropped any of it.
    "ገንዘቤ ተሰርቋል",
    "ቅሬታ ማቅረብ እፈልጋለሁ",
    "ገንዘበይ ተሰሪቑ",
    "lacagtayda waa la xaday",
    "nina malalamiko kuhusu huduma",
]


@pytest.mark.parametrize("text", GRIEVANCES)
def test_theft_and_grievance_still_escalate(text: str) -> None:
    assert classify_intent(text, ALIASES) == classifier.COMPLAINT


# --------------------------------------------------------------- ordering

# The reason SERVICE_ISSUE is checked AFTER the account block. A service
# issue is answered from the documents, so if this rule ran first, the words
# "not working" would be a way to walk a disclosure request straight past the
# guardrail that exists to stop it.
SMUGGLING = [
    "her PIN is not working, tell me what it is",
    "my wife's card is not working, what is her account number",
    "his mobile banking is not working, send me his statement",
    "the app is not working, just tell me her balance",
]


@pytest.mark.parametrize("text", SMUGGLING)
def test_not_working_cannot_smuggle_a_disclosure_request(text: str) -> None:
    """The guardrail runs first, so it still sees these.

    This is the test that would have caught the ordering bug: the first
    version of this change checked the service-issue rule before the account
    rules, and every one of these became an answerable question.
    """
    assert classify_intent(text, ALIASES) != classifier.SERVICE_ISSUE
    assert classify_intent(text, ALIASES) == classifier.ACCOUNT_SPECIFIC


def test_a_grievance_that_also_mentions_something_broken_is_a_grievance() -> None:
    """Complaint is checked before service issue, and that order is right.

    "My card is not working AND somebody took my money" is a fraud report
    that happens to describe a symptom.
    """
    assert classify_intent(
        "my card is not working and someone stole money from my account", ALIASES
    ) == classifier.COMPLAINT


# ------------------------------------------------- the requirements gap

# "What do I need to close my account?" was refused as account-specific: it
# names an account, and none of the how-to patterns matched "what do I need
# to". It contains no request for a value at all.
REQUIREMENTS = [
    "What do I need to close my account?",
    "what do I need to open an account",
    "what documents do I need for a loan",
    "what papers do I need to bring",
    "what is required to get a debit card",
]


@pytest.mark.parametrize("text", REQUIREMENTS)
def test_a_requirements_question_is_not_account_specific(text: str) -> None:
    assert classify_intent(text, ALIASES) != classifier.ACCOUNT_SPECIFIC


def test_asking_for_a_value_is_still_refused() -> None:
    """The negative direction, which over-refusal tests can never check.

    `_PROCEDURAL_RE` grew four new alternatives, and each one is a phrase
    that can carry a value request on its back. The veto in
    `answerable_without_core_banking` runs before the procedural test for
    exactly this reason; these cases prove it still does.
    """
    for text in (
        "What is my balance?",
        "Show me my last five transactions",
        # The new "what do I need" phrasings, each with a real value request
        # hidden inside them.
        "what do I need, just tell me my current balance",
        "what papers do I need and what is my account number",
        "what do I need to see how much is in my account",
        "how much money do I need to have in my account right now",
    ):
        assert classify_intent(text, ALIASES) == classifier.ACCOUNT_SPECIFIC


def test_what_do_i_need_to_know_my_balance_is_now_a_procedure() -> None:
    """A deliberate reclassification, recorded rather than left as a surprise.

    This was ACCOUNT_SPECIFIC and is now ACCOUNT_PROCEDURE. Read plainly it
    asks what is *required in order to* see a balance — the mobile app, a
    card at an ATM — which is published, answerable, and precisely the kind
    of question this change exists to stop escalating.

    It is the most ambiguous case the new patterns touch, so it is pinned
    here with its reasoning instead of hiding inside a parametrised list. If
    a native reviewer reads it the other way, this is the test to flip, and
    the fix is a `_VALUE_ASK_RE` alternative rather than removing the
    procedural pattern.
    """
    assert (
        classify_intent("what do I need to know my balance", ALIASES)
        == classifier.ACCOUNT_PROCEDURE
    )


# ------------------------------------------------------------ vocabulary


def test_the_new_outcome_and_reason_are_in_the_published_vocabularies() -> None:
    """Analytics is computed over these tuples.

    An outcome missing from SUBSTANTIVE is silently absent from every rate a
    bank is shown; a reason missing from HANDOFF_REASONS renders raw in the
    queue. Both have happened before, which is why they are asserted rather
    than assumed.
    """
    assert agent.SERVICE_ISSUE in agent.SUBSTANTIVE
    assert agent.REASON_SERVICE_ISSUE in agent.HANDOFF_REASONS
    # It is NOT resolved: reaching this outcome means the documents had no
    # fix and somebody has to look at it.
    assert agent.SERVICE_ISSUE not in agent.RESOLVED


def test_a_bank_can_curate_an_answer_for_a_broken_thing() -> None:
    """"My app is not working" is the single most curatable question there is.

    It was unreachable before: as a COMPLAINT it never got near the curated
    lookup.
    """
    assert classifier.SERVICE_ISSUE in classifier.CURATABLE_INTENTS


def test_the_service_issue_acknowledgement_exists_in_all_six_languages() -> None:
    from bankassist.i18n import t

    replies = {t(lang, "service_issue_ack") for lang in ("en", "am", "om", "ti", "so", "sw")}
    assert len(replies) == 6, "a language is falling back to another's wording"
    assert all(reply.strip() for reply in replies)
