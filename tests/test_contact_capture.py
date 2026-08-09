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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist.classifier import extract_contact
from bankassist.i18n import t
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


# ------------------------------------- a guardrail is never swallowed
#
# The regression this closes: contact capture ran before the intent switch and
# returned a whole reply, so a message carrying both a phone number and
# something that had to be handled got "thanks, we will call you" and nothing
# else. A theft report filed no handoff. The account-data refusal and the
# education-not-advice disclaimer were skippable the same way — which is
# exactly what the allowlist exists to prevent.


def _awaiting(client: TestClient) -> str:
    first = _ask(client, "demo", UNANSWERABLE)
    assert first["awaiting_contact"] is True
    convo: str = first["conversation_id"]
    return convo


def test_a_complaint_alongside_a_number_is_still_routed_to_a_person(
    client: TestClient, demo_bank: Any
) -> None:
    """The worst case: a theft report answered with "thanks, we'll call you"
    and never handed to anyone."""
    convo = _awaiting(client)
    data = _ask(client, "demo", "my money was stolen, call me on 0911234567", convo)

    assert data["intent"] == "complaint"
    assert data["handoff_created"] is True
    assert "0911234567" in data["reply"]


def test_an_account_request_alongside_a_number_still_gets_the_refusal(
    client: TestClient, demo_bank: Any
) -> None:
    convo = _awaiting(client)
    data = _ask(client, "demo", "call me on 0911234567 about my account balance", convo)

    assert data["intent"] == "account_specific"
    assert "can't access individual account details" in data["reply"]


def test_an_advice_question_alongside_a_number_still_carries_the_disclaimer(
    client: TestClient, demo_bank: Any
) -> None:
    convo = _awaiting(client)
    data = _ask(
        client, "demo", "should I invest in ESX shares? call me on 0911234567", convo
    )

    assert data["intent"] == "investment_advice"
    assert "not personal investment advice" in data["reply"]


def test_a_real_question_alongside_a_number_is_answered(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Not a safety property, but the same bug: the question was thrown away."""
    convo = _awaiting(client)
    data = _ask(
        client, "demo", "call me on 0911234567. What are your transfer fees?", convo
    )

    assert data["sources"], "the question should have been answered from content"
    assert "0911234567" in data["reply"]

    stored = db_session.execute(
        select(Conversation).where(Conversation.id == convo)
    ).scalars().one()
    assert stored.contact_phone == "0911234567"


def test_a_plain_contact_reply_stays_a_plain_contact_reply(
    client: TestClient, demo_bank: Any
) -> None:
    """The fix must not make every contact reply run through retrieval —
    "my name is Oli, call me on 0911 234 567" is not a question about names."""
    for message in ("Oli 0911234567", "my name is Oli, call me on 0911 234 567"):
        convo = _awaiting(client)
        data = _ask(client, "demo", message, convo)
        assert data["handoff_created"] is False, message
        assert "I don't have verified information" not in data["reply"], message


# ------------------------------------------------- the ask has to be the ask


def test_the_contact_request_is_the_last_thing_said(
    client: TestClient, demo_bank: Any
) -> None:
    """One question per turn, and it is this one.

    Reported from the live Awash demo: the assistant asked for a name and
    number, then closed the same message with "Were you asking about one of
    these?" over a row of tappable topic chips. People answer the last
    question they were asked, so the ask collected nothing — and from the
    outside it looked exactly like the ask had never happened at all.

    Asserting on the tail of the reply rather than on mere presence is the
    whole point: the previous version *contained* the ask and still failed.
    """
    data = _ask(client, "demo", UNANSWERABLE)
    assert data["awaiting_contact"] is True
    assert data["suggestions"], "setup: this miss should also offer topics"
    assert data["reply"].rstrip().endswith(t(data["language"], "ask_contact"))


def test_related_topics_do_not_ask_a_competing_question(
    client: TestClient, demo_bank: Any
) -> None:
    """The topic offer is a statement. A second question mark in the turn is
    how the ask got buried in the first place.

    The endswith assertion has to come first. Slicing the ask off the tail is
    only meaningful once the ask *is* the tail — without it this passes on the
    very ordering it exists to reject, which is how it was first written.
    """
    data = _ask(client, "demo", UNANSWERABLE)
    body = data["reply"].rstrip()
    ask = t(data["language"], "ask_contact")
    assert body.endswith(ask)
    assert "?" not in body[: -len(ask)], "only the contact request may ask anything"


@pytest.mark.parametrize("language,message", [
    ("am", "ወደ ማርስ ስለሚደረግ የገንዘብ ዝውውር ፖሊሲዎ ምንድን ነው?"),
    ("om", "Imaammanni keessan waa'ee maallaqa gara Maarsitti ergamuu maali?"),
])
def test_the_ask_closes_the_turn_in_every_language(
    client: TestClient, demo_bank: Any, language: str, message: str
) -> None:
    """Ordering is composed in agent.py, not in the templates — but a
    language whose reply is assembled differently would break the promise
    silently, and only for the customers least able to report it."""
    data = _ask(client, "demo", message)
    if not data["awaiting_contact"]:
        pytest.skip("this phrasing found an answer; ordering is untested here")
    assert data["reply"].rstrip().endswith(t(data["language"], "ask_contact"))


# ---------------------------------------------- the name in a real sentence


@pytest.mark.parametrize("reply,expected", [
    # Reported verbatim from the live CBE demo. The operator's queue got the
    # number and no name, so the callback would open with "who am I speaking
    # to?" — after the customer had already answered that.
    ("Oli Oli and I can be reached at 0911234567", "Oli Oli"),
    ("Oli Tamrat, you can reach me on 0911234567", "Oli Tamrat"),
    ("Abebe Kebede and my phone is 0911234567", "Abebe Kebede"),
    ("Oli oli@example.com", "Oli"),
    # The short forms that already worked, so the looser rule can't lose them.
    ("Oli 0911234567", "Oli"),
    ("Oli, 0911234567", "Oli"),
    ("My name is Oli and my number is 0911234567", "Oli"),
])
def test_the_name_survives_a_natural_sentence(reply: str, expected: str) -> None:
    assert extract_contact(reply)[0] == expected


@pytest.mark.parametrize("reply", [
    # No name given. Storing one here would mean addressing a customer by a
    # preposition for the rest of the conversation, and handing an operator a
    # fabricated name is worse than handing them none.
    "call me on 0911234567",
    "you can reach me at 0911234567",
    "my number is 0911234567",
    "I am looking for a loan, 0911234567",
    "0911234567",
])
def test_a_reply_with_no_name_stores_no_name(reply: str) -> None:
    name, contact = extract_contact(reply)
    assert contact is not None, "setup: the number must still be captured"
    assert name is None, reply


def test_the_captured_name_is_used_when_acknowledging(
    client: TestClient, demo_bank: Any
) -> None:
    """Capturing the name is only half of it — the acknowledgement in the
    screenshot said "Thank you —" rather than "Thank you Oli —" precisely
    because the name never made it out of extract_contact."""
    first = _ask(client, "demo", UNANSWERABLE)
    data = _ask(
        client, "demo", "Oli Oli and I can be reached at 0911234567",
        first["conversation_id"],
    )
    assert t(data["language"], "contact_saved_named",
             name="Oli Oli", contact="0911234567") in data["reply"]


# ------------------------------------- saying how the callback will happen


def test_a_known_number_is_confirmed_rather_than_silently_assumed(
    client: TestClient, demo_bank: Any
) -> None:
    """Reported from the live CBE demo.

    Told "I've passed you to our customer service team" with no mention of
    how, the customer asked "How did a manager contact me if you do not have
    my information?" — a fair question, and one the assistant could already
    answer. Not re-asking for a number we hold is right; saying nothing about
    it looks identical to not holding one.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    convo = first["conversation_id"]
    _ask(client, "demo", "Oli 0911234567", convo)

    again = _ask(client, "demo", "I need to speak to a manager", convo)
    assert again["awaiting_contact"] is False, "must not ask twice"
    assert "0911234567" in again["reply"], "but must say how they'll be reached"
    assert t(again["language"], "ask_contact") not in again["reply"]


def test_the_number_is_only_confirmed_on_a_callback_turn(
    client: TestClient, demo_bank: Any
) -> None:
    """An answered question is not a promise of a callback, so it has no
    business echoing the customer's phone number back at them."""
    first = _ask(client, "demo", UNANSWERABLE)
    convo = first["conversation_id"]
    _ask(client, "demo", "Oli 0911234567", convo)

    answered = _ask(client, "demo", "How do I open a savings account?", convo)
    assert answered["sources"], "setup: this should be answered from content"
    assert "0911234567" not in answered["reply"]


def test_the_turn_reports_what_it_actually_did(
    client: TestClient, demo_bank: Any
) -> None:
    """The contact-capture path returns a placeholder "question" intent, so a
    channel labelling turns by intent alone showed "Product guidance" over a
    reply that stored a phone number. outcome is what makes that fixable
    without changing the stored intent."""
    first = _ask(client, "demo", UNANSWERABLE)
    assert first["outcome"] == "unanswered"

    saved = _ask(client, "demo", "Oli 0911234567", first["conversation_id"])
    assert saved["intent"] == "question", "the placeholder intent is unchanged"
    assert saved["outcome"] == "contact_captured"


def test_every_turn_carries_an_outcome(client: TestClient, demo_bank: Any) -> None:
    """A null outcome would silently fall back to the intent label, which is
    how the mislabel hid in the first place."""
    for message in (
        "Hello",
        "How do I open a savings account?",
        "What is my account balance?",
        "I got scammed at the branch",
        "Can I speak to a manager",
        UNANSWERABLE,
    ):
        data = _ask(client, "demo", message)
        assert data["outcome"], message


def test_the_number_confirmation_is_its_own_paragraph(
    client: TestClient, demo_bank: Any
) -> None:
    """Reported from the live demo, glued onto the end of a topic list:

        • Personal and Consumer Loans They will reach you on 0911122334.

    Joined with a space it read fine after a one-line acknowledgement, which
    is the only shape it was checked in. A reply that ends in a bullet list is
    the shape that breaks, and it is the commonest one on the miss path.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    convo = first["conversation_id"]
    _ask(client, "demo", "Oli 0911234567", convo)

    again = _ask(client, "demo", SECOND_UNANSWERABLE, convo)
    assert again["suggestions"], "setup: this miss should end with a topic list"
    line = t(again["language"], "contact_on_file", contact="0911234567")
    assert again["reply"].endswith(line)
    assert f"\n\n{line}" in again["reply"], "must not continue the last bullet"


def test_a_customer_we_cannot_reach_is_never_promised_a_callback(
    client: TestClient, demo_bank: Any
) -> None:
    """Reported from the live demo. After the asks ran out, "Can I speak to a
    manager" was answered with "I've passed you to our customer service team so
    a person can help you directly" — a callback promised to someone whose
    number nobody has.

    The mirror of the lesson already in `_request_contact`: silence about a
    number we hold looks like not holding one, and silence about holding none
    looks exactly like holding one.
    """
    cid = None
    replies = []
    for message in (
        "Can I speak to a manager",
        "Can I speak to a manager",
        "Can I speak to a manager",
        "I still want a person",
    ):
        body: dict[str, Any] = {"message": message}
        if cid:
            body["conversation_id"] = cid
        data = client.post("/chat/demo", json=body).json()
        cid = data["conversation_id"]
        replies.append(data)

    exhausted = [r for r in replies if not r["awaiting_contact"]]
    assert exhausted, "the ask cap was never reached, so this proves nothing"
    for r in exhausted:
        assert t("en", "no_contact_yet") in r["reply"], (
            "a customer with no contact details on file was left believing "
            "someone would call them back"
        )


def test_the_note_is_not_shown_once_we_can_actually_reach_them(
    client: TestClient, demo_bank: Any
) -> None:
    """Telling someone we have no way to contact them, right after they gave
    us their number, would be worse than saying nothing."""
    first = client.post("/chat/demo", json={"message": "Can I speak to a manager"})
    cid = first.json()["conversation_id"]
    client.post(
        "/chat/demo", json={"message": "Oli, 0911223344", "conversation_id": cid}
    )
    again = client.post(
        "/chat/demo",
        json={"message": "Can I speak to a manager", "conversation_id": cid},
    ).json()
    assert t("en", "no_contact_yet") not in again["reply"]
    assert "0911223344" in again["reply"]
