"""What customers ask that the bank has no content for, ranked.

Every gap already files a handoff carrying the customer's own words, but as
individual rows that is a pile, not a work queue. Grouped and ranked by
frequency it becomes the one artifact a bank cannot get anywhere else: a list
of what its customers actually ask and nobody can answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bankassist.models import Handoff
from bankassist.retrieval import content_signature


def _gaps(client: TestClient, bank: Any) -> list[dict[str, Any]]:
    resp = client.get(
        "/admin/api/awash/content-gaps", headers={"X-Admin-Token": bank.admin_token}
    )
    assert resp.status_code == 200, resp.text
    data: list[dict[str, Any]] = resp.json()
    return data


def _file(db: Session, bank: Any, detail: str, reason: str = "unanswered_question") -> None:
    db.add(Handoff(bank_id=bank.id, conversation_id="c", reason=reason, detail=detail))
    db.commit()


def test_the_same_question_worded_differently_is_one_gap(
    client: TestClient, db_session: Session, awash_bank: Any
) -> None:
    # The whole point: a bank should see "12 people asked about ATM usage",
    # not twelve separate rows it has to read and correlate itself.
    for wording in ("How do I use an ATM?", "how to use ATM", "ATM how to use"):
        _file(db_session, awash_bank, wording)

    gaps = _gaps(client, awash_bank)
    assert len(gaps) == 1
    assert gaps[0]["count"] == 3


def test_gaps_are_ranked_by_how_many_people_asked(
    client: TestClient, db_session: Session, awash_bank: Any
) -> None:
    _file(db_session, awash_bank, "How do I use an ATM?")
    for _ in range(3):
        _file(db_session, awash_bank, "What are your mortgage terms?")

    gaps = _gaps(client, awash_bank)
    assert gaps[0]["count"] == 3
    assert "mortgage" in gaps[0]["examples"][0].lower()


def test_the_two_reasons_are_distinguished(
    client: TestClient, db_session: Session, awash_bank: Any
) -> None:
    # They need different work: nothing-found means write the content;
    # answered-generically means the bank may want to own that answer with
    # its own limits and fees.
    _file(db_session, awash_bank, "How do I use an ATM?", "unanswered_question")
    _file(
        db_session, awash_bank, "how to use ATM", "answered_from_general_knowledge"
    )

    gaps = _gaps(client, awash_bank)
    assert gaps[0]["reasons"] == {
        "unanswered_question": 1,
        "answered_from_general_knowledge": 1,
    }


def test_complaints_are_not_content_gaps(
    client: TestClient, db_session: Session, awash_bank: Any
) -> None:
    # A complaint is a person to call back, not a document to write.
    _file(db_session, awash_bank, "Your service is terrible", "complaint")
    assert _gaps(client, awash_bank) == []


def test_examples_carry_the_customers_own_words(
    client: TestClient, db_session: Session, awash_bank: Any
) -> None:
    # Whoever writes the content needs the real phrasing, not a normalised key.
    _file(db_session, awash_bank, "How do I use an ATM?")
    gaps = _gaps(client, awash_bank)
    assert "How do I use an ATM?" in gaps[0]["examples"]


def test_gaps_are_scoped_to_one_bank(
    client: TestClient, db_session: Session, awash_bank: Any, cbe_bank: Any
) -> None:
    _file(db_session, cbe_bank, "A question only CBE customers asked")
    assert _gaps(client, awash_bank) == []


def test_the_endpoint_requires_the_admin_token(
    client: TestClient, awash_bank: Any
) -> None:
    # Customer questions are personal data; the queue must not be public.
    assert client.get("/admin/api/awash/content-gaps").status_code == 401
    assert (
        client.get(
            "/admin/api/awash/content-gaps", headers={"X-Admin-Token": "wrong"}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("How do I use an ATM?", "how to use ATM"),
        ("What are the loan requirements", "loan requirements?"),
        ("ስለ ATM ማወቅ ፈልጌ ነበር", "ATM"),
    ],
)
def test_signature_groups_equivalent_questions(a: str, b: str) -> None:
    assert content_signature(a) == content_signature(b), (a, b)


def test_signature_separates_genuinely_different_questions() -> None:
    assert content_signature("How do I use an ATM?") != content_signature(
        "What are your mortgage terms?"
    )
