"""A handoff has to be reachable, or it is not a handoff.

Every miss replied that "our customer service team can follow up with you"
while the product held no name, no number and no email to follow up on — on
the web widget there is no identity at all. A customer reported it exactly
that way: the assistant said it was passing the question to a person, then
offered unrelated topics, and never asked how to reach them.

These lock in the ask, the capture, and — more importantly — the two ways
capture must fail safely: it must never store something that isn't contact
details, and it must never turn into a loop that nags a customer who has
moved on.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist.classifier import extract_contact
from bankassist.models import Conversation, Handoff

UNANSWERABLE = "What is your policy on interplanetary wire transfers to Mars?"
# A second miss, chosen because it shares no terms with the demo corpus —
# "transfers to the Moon" retrieves three documents on the word "transfers".
SECOND_UNANSWERABLE = "Do you sponsor competitive cheese rolling tournaments?"


def _ask(
    client: TestClient, slug: str, message: str, conversation_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    resp = client.post(f"/chat/{slug}", json=payload)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# ------------------------------------------------------------- the ask


def test_an_unanswered_question_asks_how_to_reach_the_customer(
    client: TestClient, demo_bank: Any
) -> None:
    data = _ask(client, "demo", UNANSWERABLE)
    assert data["handoff_created"] is True
    assert data["awaiting_contact"] is True
    # The promise and the means of keeping it arrive together.
    assert "phone number" in data["reply"].lower()


def test_a_complaint_also_asks_how_to_reach_the_customer(
    client: TestClient, demo_bank: Any
) -> None:
    data = _ask(client, "demo", "I got scammed and nobody at the branch would help me")
    assert data["handoff_created"] is True
    assert data["awaiting_contact"] is True


def test_an_answered_question_never_asks_for_contact_details(
    client: TestClient, demo_bank: Any
) -> None:
    """Only a promise of a callback earns the right to ask.

    Asking a customer who just got their answer for a phone number is
    collecting personal data for nothing.
    """
    data = _ask(client, "demo", "How do I open a savings account?")
    assert data["awaiting_contact"] is False
    assert "phone number" not in data["reply"].lower()


# --------------------------------------------------------- the capture


def test_the_number_is_stored_and_backfilled_onto_the_open_handoff(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    first = _ask(client, "demo", UNANSWERABLE)
    convo_id = first["conversation_id"]

    second = _ask(client, "demo", "Oli 0911234567", conversation_id=convo_id)
    assert second["awaiting_contact"] is False
    assert "0911234567" in second["reply"]
    assert "Oli" in second["reply"]

    handoff = db_session.execute(
        select(Handoff).where(Handoff.conversation_id == convo_id)
    ).scalars().one()
    # The operator working the queue sees who to call on the row itself.
    assert handoff.contact_phone == "0911234567"
    assert handoff.contact_name == "Oli"


def test_contact_is_asked_for_once_per_conversation(
    client: TestClient, demo_bank: Any
) -> None:
    """A second handoff inherits the number instead of asking again.

    Being asked for your phone number twice in one chat reads as nobody being
    on the other end — the opposite of what a handoff is meant to reassure.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    convo_id = first["conversation_id"]
    _ask(client, "demo", "0911234567", conversation_id=convo_id)

    again = _ask(
        client, "demo", SECOND_UNANSWERABLE, conversation_id=convo_id
    )
    assert again["handoff_created"] is True
    assert again["awaiting_contact"] is False
    assert "phone number" not in again["reply"].lower()


def test_a_later_handoff_carries_the_contact_from_the_start(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    first = _ask(client, "demo", UNANSWERABLE)
    convo_id = first["conversation_id"]
    _ask(client, "demo", "Oli 0911234567", conversation_id=convo_id)
    _ask(client, "demo", SECOND_UNANSWERABLE, conversation_id=convo_id)

    handoffs = db_session.execute(
        select(Handoff).where(Handoff.conversation_id == convo_id)
    ).scalars().all()
    assert len(handoffs) == 2
    assert all(h.contact_phone == "0911234567" for h in handoffs)


# ------------------------------------------------------- failing safely


def test_changing_the_subject_answers_the_question_instead_of_nagging(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """One ask, never a loop.

    A customer who ignores the request and asks something else must get an
    answer, not the same question again. This is the difference between a
    form and a conversation.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    convo_id = first["conversation_id"]

    second = _ask(
        client, "demo", "How do I open a savings account?", conversation_id=convo_id
    )
    assert second["awaiting_contact"] is False
    assert second["sources"], "the new question should have been answered normally"

    convo = db_session.execute(
        select(Conversation).where(Conversation.id == convo_id)
    ).scalars().one()
    assert convo.contact_phone is None
    assert convo.awaiting_contact is False


def test_a_filler_reply_is_never_stored_as_a_name(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The expensive false positive.

    "yes" sitting where a name was asked for would be stored and used to
    address the customer for the rest of the conversation.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    convo_id = first["conversation_id"]
    _ask(client, "demo", "yes", conversation_id=convo_id)

    convo = db_session.execute(
        select(Conversation).where(Conversation.id == convo_id)
    ).scalars().one()
    assert convo.customer_name is None


def test_an_account_number_is_never_captured_as_a_phone_number() -> None:
    """The dangerous false positive, and the reason validation is narrow.

    A thirteen-digit CBE account number matches none of the accepted shapes,
    and anything unusual has to carry an explicit country code — which an
    account number never does.
    """
    assert extract_contact("my account is 1000123456789") == (None, None)
    assert extract_contact("account 1000123456789 balance please") == (None, None)


def test_phone_spellings_normalise_to_one_number() -> None:
    for spelling in ("0911234567", "0911 234 567", "0911-234-567"):
        assert extract_contact(spelling)[1] == "0911234567"
    for spelling in ("+251911234567", "+251 91 123 4567"):
        assert extract_contact(spelling)[1] == "+251911234567"


def test_an_invalid_local_prefix_is_rejected() -> None:
    # 08 is not an Ethiopian mobile prefix; accepting it would send an
    # operator to a dead number and look like the capture worked.
    assert extract_contact("0811234567")[1] is None


def test_telephony_phrasing_is_not_read_as_a_name() -> None:
    name, contact = extract_contact("call me on 0911234567")
    assert contact == "0911234567"
    assert name is None


def test_an_email_is_accepted_as_contact(client: TestClient, demo_bank: Any) -> None:
    first = _ask(client, "demo", UNANSWERABLE)
    second = _ask(
        client, "demo", "oli@example.com", conversation_id=first["conversation_id"]
    )
    assert "oli@example.com" in second["reply"]


def test_the_ask_stops_after_two_ignored_requests(
    client: TestClient, demo_bank: Any
) -> None:
    """Each handoff is its own promise, so a second miss earns a second ask.

    A customer who has ignored two of them has answered. Asking a third time
    is pestering, which is how a helpful prompt turns into the thing people
    close the widget over.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    assert first["awaiting_contact"] is True
    convo = first["conversation_id"]

    second = _ask(client, "demo", SECOND_UNANSWERABLE, conversation_id=convo)
    assert second["awaiting_contact"] is True

    third = _ask(
        client,
        "demo",
        "Which chess opening do you recommend for beginners?",
        conversation_id=convo,
    )
    assert third["handoff_created"] is True
    assert third["awaiting_contact"] is False
    assert "phone number" not in third["reply"].lower()


# --------------------------------------------------------------- privacy


def test_the_number_never_reaches_the_audit_log(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Personal data, exactly like the chat text.

    That contact was captured is auditable; the number itself is not.
    """
    from bankassist.models import AuditLog

    first = _ask(client, "demo", UNANSWERABLE)
    _ask(client, "demo", "Oli 0911234567", conversation_id=first["conversation_id"])

    rows = db_session.execute(
        select(AuditLog).where(AuditLog.action == "contact_captured")
    ).scalars().all()
    assert rows, "capturing contact details should be auditable"
    for row in rows:
        assert "0911234567" not in str(row.log_metadata)


def test_the_admin_handoff_queue_shows_who_to_call(
    client: TestClient, demo_bank: Any
) -> None:
    first = _ask(client, "demo", UNANSWERABLE)
    _ask(client, "demo", "Oli 0911234567", conversation_id=first["conversation_id"])

    token = demo_bank.admin_token
    resp = client.get("/admin/api/demo/handoffs", headers={"X-Admin-Token": token})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows
    assert rows[0]["contact_phone"] == "0911234567"
    assert rows[0]["contact_name"] == "Oli"
