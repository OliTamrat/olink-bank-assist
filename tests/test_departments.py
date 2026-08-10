"""Which desk an escalation lands on, and in what order it gets worked.

The queue arrived as one undifferentiated list. Every row carried a `reason` —
complaint, human_requested, unanswered_question — but that says why the
assistant let go, which is a process fact. From a desk, forty rows reading
"unanswered_question" is uncategorised.

The tests that matter here are the ordering ones. Whether "how do I open an
account" lands on Accounts is barely worth a test; whether a theft report
outranks a fee question is the difference between a queue that works and a
queue that gets ignored.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import departments as d
from bankassist.models import Handoff

# Genuinely outside any bank's material, so it always files an escalation and
# always lands on the catch-all desk — which is what makes it useful as the
# contrast in the ordering tests below.
OFF_TOPIC = "Do you sponsor competitive cheese rolling tournaments?"


# ------------------------------------------------------------- the rules


@pytest.mark.parametrize("message,desk", [
    ("How do I open a savings account?", d.ACCOUNTS),
    ("What is the minimum balance?", d.ACCOUNTS),
    ("My card was swallowed by the ATM", d.CARDS),
    ("How do I apply for a personal loan?", d.LENDING),
    ("What is the exchange rate for the dollar?", d.INTERNATIONAL),
    ("How do I send money to telebirr?", d.PAYMENTS),
    ("I cannot log in to mobile banking", d.DIGITAL),
    ("Do you sponsor football teams?", d.GENERAL),
    ("ካርዴ ጠፍቷል", d.CARDS),
    ("liqii akkamitti argadha?", d.LENDING),
])
def test_a_question_lands_on_the_desk_that_answers_it(
    message: str, desk: str
) -> None:
    assert d.classify(message) == desk, message


def test_theft_outranks_the_product_it_mentions() -> None:
    """The ordering that matters most. "Someone took money from my card" is a
    fraud matter that happens to mention a card, not a cards matter — and
    getting it backwards puts theft reports in a queue worked by close of
    business."""
    assert d.classify("Someone stole 5000 birr from my card") == d.FRAUD
    assert d.classify("There is an unauthorized transfer on my account") == d.FRAUD
    assert d.classify("ገንዘቤ ተሰርቋል") == d.FRAUD


def test_nothing_is_ever_unplaced() -> None:
    """A row nobody owns is a customer nobody calls back — worse than a row on
    the wrong desk, which an operator moves in one click."""
    for message in ("", "asdfgh", "?????", "hello"):
        assert d.classify(message) in d.DEPARTMENTS


def test_there_is_no_fees_desk() -> None:
    """Deliberate. Fees are a property of every product, not a team: a bank
    answers "what does a transfer cost" from the transfers desk and "what does
    the loan cost" from lending. A Fees category would collect questions that
    each belong somewhere else and call it organisation — the same
    undifferentiated pile, wearing a label."""
    assert "fees" not in d.DEPARTMENTS
    assert d.classify("How much is the transfer fee?") == d.PAYMENTS
    assert d.classify("How much does a loan cost?") == d.LENDING


@pytest.mark.parametrize("message", [
    "Someone stole my card",
    "My card is lost",
    "There has been fraud on my account",
    "Please block my card",
    "ካርዴ ጠፍቷል",
    "kaardii koo bade",
])
def test_money_already_gone_is_urgent(message: str) -> None:
    """Urgency is not a mood. It is whether the loss grows while the row
    waits — money that has already moved, or access somebody else has."""
    assert d.priority(message) == d.URGENT, message


@pytest.mark.parametrize("message", [
    "How do I open a savings account?",
    "What are your working hours?",
    "How much is the transfer fee?",
])
def test_an_ordinary_question_is_not_urgent(message: str) -> None:
    """The other half. If everything is urgent then nothing is, and the theft
    report goes back to being invisible."""
    assert d.priority(message) == d.NORMAL, message


def test_a_lost_card_is_urgent_in_every_language_it_is_reported_in() -> None:
    """Caught while writing these. Only one of the three Amharic ways to say
    "it is lost" was listed, so "ካርዴ ጠፍቷል" — the plainest of them — was
    routed as an ordinary question while the English was urgent. An asymmetry
    like that makes the product worse for exactly the customers it is for."""
    for message in ("My card is lost", "ካርዴ ጠፍቷል", "kaardii koo bade"):
        assert d.priority(message) == d.URGENT, message


def test_article_titles_are_a_fallback_and_not_an_override() -> None:
    """Retrieval returning the loans article for a fee question means the
    question was asked near loan wording, not that it is a lending matter. The
    customer's own words win; titles only speak when the words said nothing."""
    assert d.classify("How do I apply?", titles=("Personal and Business Loans",)) \
        == d.LENDING
    assert d.classify(
        "How do I open a savings account?", titles=("Personal and Business Loans",)
    ) == d.ACCOUNTS


# --------------------------------------------------------- end to end


def test_an_escalation_is_filed_with_a_desk_and_a_priority(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    client.post("/chat/demo", json={"message": "Someone stole money from my card"})
    row = db_session.execute(select(Handoff)).scalars().first()
    assert row is not None
    assert row.department == d.FRAUD
    assert row.priority == d.URGENT


def test_the_queue_puts_urgent_work_first(
    client: TestClient, demo_bank: Any, db_session: Any, admin_client: Any = None
) -> None:
    """Urgent first, then oldest. Both halves: a theft report filed an hour ago
    outranks a fee question from yesterday, and within one lane the person who
    has waited longest keeps winning."""
    client.post("/chat/demo", json={"message": OFF_TOPIC})
    client.post("/chat/demo", json={"message": "Someone stole money from my account"})

    rows = client.get(
        "/admin/api/demo/handoffs",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert len(rows) >= 2
    assert rows[0]["priority"] == d.URGENT
    assert rows[0]["department"] == d.FRAUD
    assert rows[0]["department_label"] == "Fraud & security"


def test_the_queue_can_be_narrowed_to_one_desk(
    client: TestClient, demo_bank: Any
) -> None:
    client.post("/chat/demo", json={"message": "Someone stole money from my account"})
    client.post("/chat/demo", json={"message": OFF_TOPIC})

    only = client.get(
        "/admin/api/demo/handoffs?department=fraud",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert only and all(r["department"] == d.FRAUD for r in only)


def test_every_desk_is_listed_even_when_it_is_empty(
    client: TestClient, demo_bank: Any
) -> None:
    """A list that only shows the busy desks reorders itself as the day goes
    on, so an operator who has learned where their queue sits has to re-find
    it every time they look."""
    client.post("/chat/demo", json={"message": "Someone stole money from my account"})
    desks = client.get(
        "/admin/api/demo/handoffs/desks",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert [x["department"] for x in desks] == list(d.DEPARTMENTS)
    fraud = next(x for x in desks if x["department"] == d.FRAUD)
    assert fraud["open"] == 1 and fraud["urgent"] == 1


def test_an_operator_can_move_a_row_to_the_right_desk(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The rules will be wrong sometimes — they are rules — and the operator
    who notices is the one holding the row."""
    client.post("/chat/demo", json={"message": OFF_TOPIC})
    hid = client.get(
        "/admin/api/demo/handoffs",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()[0]["id"]

    resp = client.put(
        f"/admin/api/demo/handoffs/{hid}/department",
        json={"department": d.INTERNATIONAL},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert db_session.get(Handoff, hid).department == d.INTERNATIONAL


def test_a_move_to_an_invented_desk_is_refused(
    client: TestClient, demo_bank: Any
) -> None:
    """Coercing it to `general` would look like the move worked and leave the
    row somewhere nobody expected."""
    client.post("/chat/demo", json={"message": OFF_TOPIC})
    hid = client.get(
        "/admin/api/demo/handoffs",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()[0]["id"]
    assert client.put(
        f"/admin/api/demo/handoffs/{hid}/department",
        json={"department": "vibes"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).status_code == 422


def test_moving_a_row_is_audited(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The log of what got moved, and from where to where, is the only honest
    way to find out which rule is wrong."""
    from bankassist.models import AuditLog

    client.post("/chat/demo", json={"message": OFF_TOPIC})
    hid = client.get(
        "/admin/api/demo/handoffs",
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()[0]["id"]
    client.put(
        f"/admin/api/demo/handoffs/{hid}/department",
        json={"department": d.CARDS},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    row = db_session.execute(
        select(AuditLog).where(AuditLog.action == "handoff_moved")
    ).scalars().first()
    assert row is not None
    assert row.log_metadata["to"] == d.CARDS
