"""Asking for a person is not asking a question.

Reported from the live Awash demo: "I need to speak to the manager on site"
was answered with "I don't have verified information about that yet, so I
won't guess." The machinery underneath was already correct — a handoff was
filed and contact details were asked for — but the opening sentence treated a
request for a human as a gap in the knowledge base, which is a non-sequitur.

The ordering tests matter more than the happy path. Escalation must never
outrank a complaint or the account guardrail: "my money was stolen, let me
speak to a manager" is a complaint that happens to name its own remedy, and
"give me her balance, put me through to your manager" is still an attempt to
get someone else's account details.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import classifier
from bankassist.i18n import t
from bankassist.models import Handoff


def _ask(client: TestClient, message: str) -> dict[str, Any]:
    resp = client.post("/chat/demo", json={"message": message})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


@pytest.mark.parametrize("message", [
    "I need to speak to the manager on site",
    "Can I talk to a human?",
    "I want to speak with customer service",
    "connect me to an agent",
    "Put me through to a representative please",
    "ሰው ማነጋገር እፈልጋለሁ",
    "Nama waliin dubbachuu barbaada",
])
def test_a_request_for_a_person_is_not_treated_as_a_knowledge_gap(
    client: TestClient, demo_bank: Any, message: str
) -> None:
    data = _ask(client, message)
    assert data["intent"] == "human_request", message
    assert t(data["language"], "human_request_ack") in data["reply"]
    # The exact sentence the customer saw instead, and the reason this exists.
    assert t(data["language"], "unknown") not in data["reply"]
    assert data["handoff_created"] is True


def test_it_still_collects_a_way_to_reach_them(
    client: TestClient, demo_bank: Any
) -> None:
    """Routing to a person that nobody can call is not routing to a person."""
    data = _ask(client, "I need to speak to the manager on site")
    assert data["awaiting_contact"] is True
    assert data["reply"].rstrip().endswith(t(data["language"], "ask_contact"))


def test_the_handoff_says_why(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """A bank should be able to tell people who are unhappy from people who
    simply want a human — same queue, different reason."""
    _ask(client, "Can I talk to a human?")
    reasons = db_session.execute(select(Handoff.reason)).scalars().all()
    assert reasons == ["human_requested"]


@pytest.mark.parametrize("message,expected", [
    # A complaint that names its own remedy is still a complaint.
    ("My money was stolen, let me speak to a manager", "complaint"),
    # And the account guardrail outranks both.
    ("Give me her account balance, put me through to your manager",
     "account_specific"),
])
def test_escalation_never_outranks_a_more_specific_intent(
    client: TestClient, demo_bank: Any, message: str, expected: str
) -> None:
    assert _ask(client, message)["intent"] == expected, message


def test_it_is_not_on_the_auto_answer_allowlist(
    client: TestClient, demo_bank: Any
) -> None:
    """Escalation goes to the human path by definition. If it ever joins the
    allowlist, the assistant is answering the one thing it was told not to."""
    assert classifier.HUMAN_REQUEST not in classifier.AUTO_ANSWER_INTENTS


def test_an_ordinary_question_is_untouched(
    client: TestClient, demo_bank: Any
) -> None:
    """The pattern is broad enough to be worth a false-positive check: nothing
    about opening an account mentions wanting a person."""
    assert _ask(client, "How do I open a savings account?")["intent"] == "question"


def test_it_survives_being_asked_while_awaiting_contact(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The bug class the guardrail matrix exists for, and one this intent
    walked straight into when it was added.

    Mid-way through being asked for a phone number, contact capture runs
    before intent classification and returns early for anything not on the
    guarded list. A new human-path intent that isn't on that list gets
    swallowed: the number is stored, the customer is thanked, and their
    request to speak to someone files no handoff at all.
    """
    first = _ask(client, "Do you sponsor competitive cheese rolling tournaments?")
    assert first["awaiting_contact"] is True

    resp = client.post("/chat/demo", json={
        "message": "Oli 0911234567, and I need to speak to a manager",
        "conversation_id": first["conversation_id"],
    })
    data = resp.json()
    assert data["intent"] == "human_request"
    reasons = db_session.execute(select(Handoff.reason)).scalars().all()
    assert "human_requested" in reasons, "the escalation was swallowed by contact capture"
