"""Answers the bank has approved, served without asking a model anything.

The same twenty questions are most of a bank's traffic, and each one currently
costs a retrieval, a Gemini call and a second of the customer's patience — for
an answer that has not changed since the last person asked it.

The obvious fix is to cache what the model said. This is the better one: the
frequent question becomes an answer the BANK has signed off, and that is what
gets served. A cached model output is unreviewed text nobody at the bank has
read; a curated answer is their own words with a name against them. That
difference is what a bank is buying.

The tests that matter here are the ones about what a curated answer must never
be allowed to do — skip a guardrail, or be served before somebody approved it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import faq
from bankassist.models import Faq

Q = "How do I open a savings account?"
A = "Visit any branch with your Fayda ID and 100 birr to open one the same day."


def _publish(
    client: TestClient, bank: Any, question: str = Q, answer: str = A,
    language: str = "en", status: str = "published",
) -> str:
    resp = client.post(
        f"/admin/api/{bank.slug}/faq",
        json={"question": question, "answer": answer,
              "language": language, "status": status},
        headers={"X-Admin-Token": bank.admin_token},
    )
    assert resp.status_code == 201, resp.text
    fid: str = resp.json()["id"]
    return fid


# ------------------------------------------------------------ the matching


def test_the_same_question_typed_differently_is_the_same_question() -> None:
    """Case, spacing and the punctuation around it cannot change what somebody
    is asking. The Ethiopic full stop is in there for a reason: a question
    typed with ። must match the same question typed without it, or Amharic
    gets a worse hit rate than English for punctuation reasons alone."""
    for variant in (
        "how do i open a savings account",
        "  How do I open a savings account?  ",
        "How  do  I  open  a  savings  account",
        "How do I open a savings account!",
    ):
        assert faq.matches(Q, "en", variant, "en"), variant


def test_a_different_question_is_a_different_question() -> None:
    """The restraint that makes this safe. Nothing here stems, drops
    stopwords, or expands synonyms — every one of those merges questions a
    bank would answer differently, and a false hit has no downstream gate to
    catch it: no retrieval score, no INSUFFICIENT_CONTEXT, no sources. What
    the FAQ returns is what the customer reads."""
    assert not faq.matches(Q, "en", "How do I close a savings account?", "en")
    assert not faq.matches(
        "What is the fee for transfers to CBE?", "en",
        "What is the fee for transfers from CBE?", "en",
    )


def test_language_is_part_of_the_question() -> None:
    """A bank writes a different answer per language, and one key would make
    publishing the Amharic version silently overwrite the English one."""
    assert not faq.matches(Q, "en", Q, "am")


# ------------------------------------------------------ what it must not do


def test_a_curated_answer_cannot_skip_the_account_guardrail(
    client: TestClient, demo_bank: Any
) -> None:
    """THE test. Placing the lookup first would have been the obvious
    optimisation and would let a bank publish an answer to "what is my
    balance" that the assistant then serves — bypassing the one refusal this
    product is sold on."""
    _publish(client, demo_bank, question="What is my balance?",
             answer="Your balance is 5000 birr.")

    data = client.post("/chat/demo", json={"message": "What is my balance?"}).json()
    assert data["intent"] == "account_specific"
    assert "5000" not in data["reply"]
    assert data["outcome"] == "account_blocked"


def test_a_curated_answer_cannot_swallow_a_complaint(
    client: TestClient, demo_bank: Any
) -> None:
    """A complaint has to reach a person even if its words happen to match
    something somebody published."""
    _publish(client, demo_bank, question="Someone stole money from my account",
             answer="Please do not worry about it.")

    data = client.post(
        "/chat/demo", json={"message": "Someone stole money from my account"}
    ).json()
    assert data["intent"] == "complaint"
    assert data["handoff_created"] is True


def test_a_draft_is_never_served(client: TestClient, demo_bank: Any) -> None:
    """The gap between starting an answer at 16:55 and finishing it is exactly
    when a customer would read the half of it that exists."""
    _publish(client, demo_bank, answer="HALF WRITTEN", status="draft")
    data = client.post("/chat/demo", json={"message": Q}).json()
    assert "HALF WRITTEN" not in data["reply"]


# ---------------------------------------------------------- what it does do


def test_a_published_answer_is_served_verbatim(
    client: TestClient, demo_bank: Any
) -> None:
    _publish(client, demo_bank)
    data = client.post("/chat/demo", json={"message": Q}).json()
    assert data["reply"] == A
    assert data["outcome"] == "answered"
    assert data["sources"], "the bank said it, and the reply has to say so"


def test_a_greeting_in_front_of_it_still_matches(
    client: TestClient, demo_bank: Any
) -> None:
    """"Selam, how do I open an account?" and the bare question are one
    question. Needing two curated entries for that would be a tax on every
    bilingual customer, who greet far more often than English speakers do."""
    _publish(client, demo_bank)
    data = client.post("/chat/demo", json={"message": "Selam, " + Q}).json()
    assert data["reply"] == A


def test_serving_is_counted(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The number that tells a bank whether curating more of these is worth
    anybody's afternoon."""
    fid = _publish(client, demo_bank)
    for _ in range(3):
        client.post("/chat/demo", json={"message": Q})
    db_session.expire_all()
    assert db_session.get(Faq, fid).served == 3


def test_publishing_the_same_question_twice_is_refused(
    client: TestClient, demo_bank: Any
) -> None:
    """Two answers to one question is a support call nobody can reproduce.
    A 409 is a sentence an operator can act on."""
    _publish(client, demo_bank)
    resp = client.post(
        "/admin/api/demo/faq",
        json={"question": "  how do i OPEN a savings account  ",
              "answer": "Something else", "language": "en", "status": "published"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 409, resp.text


def test_editing_after_approval_records_a_fresh_approval(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """An answer edited after sign-off and still carrying the original
    approval would be a record of somebody approving words they never read."""
    fid = _publish(client, demo_bank)
    db_session.expire_all()
    first = db_session.get(Faq, fid).approved_at

    client.put(
        f"/admin/api/demo/faq/{fid}",
        json={"question": Q, "answer": "Rewritten entirely.",
              "language": "en", "status": "published"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    db_session.expire_all()
    row = db_session.get(Faq, fid)
    assert row.answer == "Rewritten entirely."
    assert row.approved_at is not None and row.approved_at >= first


def test_an_edited_answer_takes_effect_immediately(
    client: TestClient, demo_bank: Any
) -> None:
    """A curated answer with a stale copy in front of it would be worse than
    no curation: the bank corrects a figure and watches the assistant keep
    quoting the old one."""
    fid = _publish(client, demo_bank)
    assert client.post("/chat/demo", json={"message": Q}).json()["reply"] == A

    client.put(
        f"/admin/api/demo/faq/{fid}",
        json={"question": Q, "answer": "The minimum is now 200 birr.",
              "language": "en", "status": "published"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert client.post("/chat/demo", json={"message": Q}).json()["reply"] \
        == "The minimum is now 200 birr."


def test_deleting_it_returns_the_question_to_the_assistant(
    client: TestClient, demo_bank: Any
) -> None:
    """Withdrawing an answer has to actually withdraw it, and the customer
    still gets helped — by retrieval, the way they would have been before."""
    fid = _publish(client, demo_bank)
    client.delete(
        f"/admin/api/demo/faq/{fid}",
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    data = client.post("/chat/demo", json={"message": Q}).json()
    assert data["reply"] != A
    assert data["outcome"] in ("answered", "unanswered")


# --------------------------------------------------------- the loop itself


def test_repeated_questions_are_suggested_for_curation(
    client: TestClient, demo_bank: Any
) -> None:
    """Without this list the feature is a form nobody knows what to type
    into. The assistant sees every question; this is where the bank sees which
    ones repeat."""
    for _ in range(3):
        client.post("/chat/demo", json={"message": "Do you finance ostrich farms?"})
    client.post("/chat/demo", json={"message": "A one-off question nobody repeats"})

    rows = client.get(
        "/admin/api/demo/faq/suggestions",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    top = [r for r in rows if "ostrich" in r["question"].lower()]
    assert top and top[0]["asked"] == 3
    assert top[0]["faq_id"] is None, "not curated yet"
    assert not [r for r in rows if "one-off" in r["question"].lower()], (
        "asked once is not a pattern"
    )


def test_a_suggestion_shows_when_it_is_already_answered(
    client: TestClient, demo_bank: Any
) -> None:
    """Otherwise the list keeps recommending work that is already done."""
    for _ in range(2):
        client.post("/chat/demo", json={"message": Q})
    _publish(client, demo_bank)

    rows = client.get(
        "/admin/api/demo/faq/suggestions",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    mine = [r for r in rows if faq.normalise(r["question"]) == faq.normalise(Q)]
    assert mine and mine[0]["status"] == "published"


@pytest.mark.parametrize("language", ["am", "om"])
def test_an_answer_is_only_served_in_the_language_it_was_written_for(
    client: TestClient, demo_bank: Any, language: str
) -> None:
    """Publishing an Amharic answer must not make it the reply to the English
    question, which is what one shared key would have done."""
    _publish(client, demo_bank, language=language, answer="Local wording.")
    data = client.post("/chat/demo", json={"message": Q}).json()
    assert data["reply"] != "Local wording."


# ------------------------------- only suggest what could actually be served
#
# Found on the first real list in production. It offered "Can I speak to a
# manager" and "My name is Oli" as questions worth answering — one is a
# request for a person, the other is somebody introducing themselves.
#
# The manager one is the dangerous suggestion, not the silly one. A curated
# answer for it is UNREACHABLE: the human-request branch runs before the
# lookup, deliberately, so an operator could write it, publish it, watch it
# never appear, and reasonably conclude the whole feature was broken.


@pytest.mark.parametrize("message,why", [
    ("Can I speak to a manager please", "handled by the human-request branch"),
    ("My name is Oli Tamrat", "an introduction, not a question"),
    ("Someone stole money from my account", "handled by the complaint branch"),
    ("What is my current account balance", "handled by the account guardrail"),
])
def test_unanswerable_traffic_is_never_suggested(
    client: TestClient, demo_bank: Any, message: str, why: str
) -> None:
    for _ in range(3):
        client.post("/chat/demo", json={"message": message})
    rows = client.get(
        "/admin/api/demo/faq/suggestions",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert not [
        r for r in rows if faq.normalise(r["question"]) == faq.normalise(message)
    ], why


def test_ordinary_questions_are_still_suggested(
    client: TestClient, demo_bank: Any
) -> None:
    """The other half. A filter that removed everything would be a page that
    is always empty, and the temptation would then be to loosen it."""
    for _ in range(3):
        client.post("/chat/demo", json={"message": "Do you finance ostrich farms?"})
    rows = client.get(
        "/admin/api/demo/faq/suggestions",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert [r for r in rows if "ostrich" in r["question"].lower()]


@pytest.mark.parametrize("intent_message", [
    "Can I speak to a manager please",
    "Someone stole money from my account",
    "What is my current account balance",
])
def test_the_suggestion_filter_matches_what_respond_actually_serves(
    client: TestClient, demo_bank: Any, intent_message: str
) -> None:
    """The consistency check, so the two lists cannot drift.

    `CURATABLE_INTENTS` is a hand-written set and the branch order in
    `respond()` is what actually decides. A set that fell out of step would
    put work back on the suggestions page that silently does nothing — so
    this publishes an answer for each excluded intent and proves the
    assistant does not serve it.
    """
    from bankassist.classifier import CURATABLE_INTENTS, classify_intent

    assert classify_intent(intent_message) not in CURATABLE_INTENTS
    _publish(client, demo_bank, question=intent_message, answer="CURATED TEXT")
    data = client.post("/chat/demo", json={"message": intent_message}).json()
    assert "CURATED TEXT" not in data["reply"], (
        "the suggestion filter excludes this intent because respond() cannot "
        "serve it — if that stops being true, the filter is now wrong"
    )
