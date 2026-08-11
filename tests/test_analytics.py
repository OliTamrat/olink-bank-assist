"""The report a bank renews on.

Content Gaps answers "what should we write next". This answers the prior
question — "is it working at all" — and they are deliberately separate: a bank
shown only its failures concludes the product is failing.

Two properties matter more than any individual number. A rate with no
denominator must be absent rather than zero, because "0% deflection" on a
fresh tenant is a lie told by a division. And nothing personal may appear in
this report, because it is the artifact most likely to be exported, pasted
into a deck, and shown to people who never touched the chat.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import agent as agent_module
from bankassist.models import Message

ANSWERABLE = "How do I open a savings account?"
UNANSWERABLE = "Do you sponsor competitive cheese rolling tournaments?"


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


def _analytics(client: TestClient, bank: Any, slug: str = "demo", **params: Any) -> dict[str, Any]:
    resp = client.get(
        f"/admin/api/{slug}/analytics",
        headers={"X-Admin-Token": bank.admin_token},
        params=params,
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# ------------------------------------------------------- honest arithmetic


def test_a_tenant_with_no_traffic_reports_no_rate_rather_than_zero(
    client: TestClient, demo_bank: Any
) -> None:
    data = _analytics(client, demo_bank)
    assert data["substantive_questions"] == 0
    assert data["deflection_rate"] is None
    assert data["own_content_rate"] is None


def test_an_answered_question_counts_as_resolved_from_own_content(
    client: TestClient, demo_bank: Any
) -> None:
    _ask(client, "demo", ANSWERABLE)
    data = _analytics(client, demo_bank)
    assert data["substantive_questions"] == 1
    assert data["answered_from_own_content"] == 1
    assert data["deflection_rate"] == 1.0
    assert data["own_content_rate"] == 1.0


def test_a_content_gap_is_not_counted_as_resolved(
    client: TestClient, demo_bank: Any
) -> None:
    _ask(client, "demo", ANSWERABLE)
    _ask(client, "demo", UNANSWERABLE)
    data = _analytics(client, demo_bank)
    assert data["substantive_questions"] == 2
    assert data["resolved_without_a_person"] == 1
    assert data["deflection_rate"] == 0.5


def test_a_greeting_is_not_a_question(client: TestClient, demo_bank: Any) -> None:
    """Greetings must never pad the denominator.

    Counting "Selam!" as a question the assistant handled would inflate every
    rate on the page, and it is the easiest number in the product to flatter
    by accident.
    """
    _ask(client, "demo", "Selam!")
    data = _analytics(client, demo_bank)
    assert data["substantive_questions"] == 0
    assert data["deflection_rate"] is None
    outcomes = {row["outcome"]: row["count"] for row in data["outcomes"]}
    assert outcomes.get(agent_module.GREETING) == 1


# ------------------------------------------------------------- privacy


def test_contact_details_never_appear_in_the_report(
    client: TestClient, demo_bank: Any
) -> None:
    """The invariant that made this endpoint dangerous before it was fixed.

    A reply of "Oli 0911234567" to the contact request classifies as an
    ordinary question, so filtering ranked topics by intent put a customer's
    name and phone number straight into the report. Topics are filtered on the
    recorded outcome instead, which is a fact rather than a guess.
    """
    first = _ask(client, "demo", UNANSWERABLE)
    _ask(client, "demo", "Oli 0911234567", conversation_id=first["conversation_id"])

    import json

    blob = json.dumps(_analytics(client, demo_bank), ensure_ascii=False)
    assert "0911234567" not in blob
    assert "Oli" not in blob


def test_the_contact_turn_is_excluded_from_questions(
    client: TestClient, demo_bank: Any
) -> None:
    first = _ask(client, "demo", UNANSWERABLE)
    _ask(client, "demo", "0911234567", conversation_id=first["conversation_id"])
    data = _analytics(client, demo_bank)
    # The gap is a question; handing over a phone number is not.
    assert data["substantive_questions"] == 1


# --------------------------------------------------------- multi-tenancy


def test_one_bank_never_sees_another_banks_traffic(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    _ask(client, "demo", ANSWERABLE)
    _ask(client, "cbe", "How do I open an account?")
    _ask(client, "cbe", UNANSWERABLE)

    demo = _analytics(client, demo_bank)
    cbe = _analytics(client, cbe_bank, slug="cbe")

    assert demo["conversations"] == 1
    assert cbe["conversations"] == 2
    assert demo["substantive_questions"] == 1
    assert cbe["substantive_questions"] == 2
    demo_topics = {t["example"] for t in demo["top_topics"]}
    assert UNANSWERABLE not in demo_topics


# ------------------------------------------------------------ the queue


def test_open_handoffs_are_split_by_whether_anyone_can_be_reached(
    client: TestClient, demo_bank: Any
) -> None:
    """An open handoff nobody can call is a dead letter, not a to-do."""
    unreachable = _ask(client, "demo", UNANSWERABLE)
    assert unreachable["handoff_created"] is True

    # Not "chess opening" — that matches the account-*opening* document.
    reachable = _ask(client, "demo", "How tall is the tallest giraffe in the zoo?")
    _ask(client, "demo", "0911234567", conversation_id=reachable["conversation_id"])

    handoffs = _analytics(client, demo_bank)["handoffs"]
    assert handoffs["open"] == 2
    assert handoffs["open_reachable"] == 1
    assert handoffs["open_unreachable"] == 1


# ------------------------------------------------------- unclassified


def test_turns_from_before_the_migration_are_reported_not_guessed(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Rows written before migration 0007 have no honest outcome.

    Inventing one would put guesses into numbers a bank is being asked to
    trust, so they are surfaced as a count instead and left out of every rate.
    """
    _ask(client, "demo", ANSWERABLE)
    row = db_session.execute(
        select(Message).where(Message.role == "assistant")
    ).scalars().one()
    row.outcome = None
    db_session.commit()

    data = _analytics(client, demo_bank)
    assert data["unclassified_turns"] == 1
    assert data["substantive_questions"] == 0
    assert data["deflection_rate"] is None


# ----------------------------------------------------------- the window


def test_the_window_is_bounded_and_zero_means_all_time(
    client: TestClient, demo_bank: Any
) -> None:
    _ask(client, "demo", ANSWERABLE)

    assert _analytics(client, demo_bank, days=0)["since"] is None
    assert _analytics(client, demo_bank, days=0)["substantive_questions"] == 1
    # A silly value must clamp rather than build an unbounded scan.
    assert _analytics(client, demo_bank, days=99999)["window_days"] == 365
    assert _analytics(client, demo_bank, days=-5)["window_days"] == 0


def test_language_mix_is_reported_with_display_names(
    client: TestClient, demo_bank: Any
) -> None:
    """The multilingual claim is the differentiator; it has to be visible."""
    _ask(client, "demo", ANSWERABLE)
    _ask(client, "demo", "የቁጠባ ሂሳብ እንዴት እከፍታለሁ?")
    langs = {row["language"]: row for row in _analytics(client, demo_bank)["languages"]}
    assert langs["en"]["count"] == 1
    assert langs["am"]["count"] == 1
    assert langs["am"]["name"] == "አማርኛ"


def test_language_mix_carries_an_outcome_breakdown(
    client: TestClient, demo_bank: Any
) -> None:
    """The Languages panel expands a card per language the same way Most
    Asked expands one per topic — "what happened when someone asked in
    Amharic" needs the outcome counts to already be on the row, joined
    through Conversation since language lives there, not on Message."""
    _ask(client, "demo", ANSWERABLE)
    _ask(client, "demo", UNANSWERABLE)
    _ask(client, "demo", "የቁጠባ ሂሳብ እንዴት እከፍታለሁ?")
    langs = {row["language"]: row for row in _analytics(client, demo_bank)["languages"]}
    assert langs["en"]["outcomes"] == {
        agent_module.ANSWERED: 1,
        agent_module.UNANSWERED: 1,
    }
    assert langs["am"]["outcomes"] == {agent_module.ANSWERED: 1}
    # A supported language nobody has used yet carries no traffic and no
    # outcomes — not a KeyError, not a guessed zero-count outcome.
    assert langs["ti"]["count"] == 0
    assert langs["ti"]["outcomes"] == {}


def test_analytics_requires_the_admin_token(client: TestClient, demo_bank: Any) -> None:
    assert client.get("/admin/api/demo/analytics").status_code == 401
    assert (
        client.get(
            "/admin/api/demo/analytics", headers={"X-Admin-Token": "wrong"}
        ).status_code
        == 401
    )


def test_the_report_carries_the_banks_own_name(
    client: TestClient, cbe_bank: Any
) -> None:
    """This report gets printed and put in front of people who have never seen
    the slug. A page headed "cbe" reads as an internal debug screen.

    It now carries both names, and the distinction is the point: the heading is
    what the bank is called, so it is recognisable at a glance, and the
    registered name sits under it so the document is exact on inspection. A
    board pack wants both, and picking one would have lost the other.
    """
    data = client.get(
        "/admin/api/cbe/analytics", headers={"X-Admin-Token": cbe_bank.admin_token}
    ).json()
    assert data["bank_name"] == "CBE"
    assert data["bank_legal_name"] == cbe_bank.name
    # Neither is the slug, which is the failure this test was written for.
    assert data["bank_name"] != "cbe"
    assert data["bank_legal_name"] != "cbe"
