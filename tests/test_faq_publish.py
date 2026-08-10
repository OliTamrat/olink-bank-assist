"""Approving curated answers in bulk.

Eight hundred answers is not a queue anybody clears one row at a time. Without
this the honest choice is between publishing nothing and clicking for an
afternoon, and nothing is what actually happens — so the languages never go
live and the work of translating them was wasted.

Bulk approval is still approval. The record it leaves must be the record a
careful one-at-a-time pass would have left, because `approved_by` is the whole
difference between a curated answer and a cache with extra steps.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist.models import AuditLog, Faq


@pytest.fixture
def fake_translate(monkeypatch: pytest.MonkeyPatch) -> None:
    def translate(text: str, language: str, language_name: str, bank: str) -> str:
        return f"[{language}] {text}"

    monkeypatch.setattr("bankassist.llm.translate_curated", translate)


def _draft(client: TestClient, bank: Any, question: str, answer: str) -> None:
    client.post(
        "/admin/api/demo/faq",
        json={"question": question, "answer": answer, "status": "draft"},
        headers={"X-Admin-Token": bank.admin_token},
    )


def test_publishing_stamps_the_same_record_as_approving_one(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The property that keeps a curated answer curated. A bulk path that
    skipped the sign-off would quietly turn the whole table into a cache."""
    _draft(client, demo_bank, "What is the fee?", "Ten birr.")
    out = client.post(
        "/admin/api/demo/faq/publish", json={},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert out["published"] == 1
    db_session.expire_all()
    row = db_session.execute(select(Faq)).scalars().one()
    assert row.status == "published"
    assert row.approved_at is not None


def test_a_published_answer_is_then_actually_served(
    client: TestClient, demo_bank: Any
) -> None:
    """End to end, because "status says published" is not the same claim as
    "a customer gets it"."""
    _draft(client, demo_bank, "What is the fee?", "Ten birr exactly.")
    client.post("/admin/api/demo/faq/publish", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    reply = client.post(
        "/chat/demo", json={"message": "What is the fee?"}
    ).json()
    assert reply["reply"].strip() == "Ten birr exactly."


def test_one_language_can_be_published_without_the_others(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """Publishing the bank's own English is a different decision from
    publishing machine translations nobody has read. Naming the language keeps
    them separate rather than folding both into one click."""
    _draft(client, demo_bank, "What is the fee?", "Ten birr.")
    client.post("/admin/api/demo/faq/publish", json={"languages": ["en"]},
                headers={"X-Admin-Token": demo_bank.admin_token})
    client.post("/admin/api/demo/faq/translate", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    db_session.expire_all()
    rows = db_session.execute(select(Faq)).scalars().all()
    published = {r.language for r in rows if r.status == "published"}
    drafts = {r.language for r in rows if r.status == "draft"}
    assert published == {"en"}
    assert drafts == {"am", "om", "ti", "so"}


def test_the_audit_says_how_many_were_machine_translations(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """"We published 640 machine translations on the tenth" is the sentence a
    linguist reviewer needs. Reconstructing it from timestamps afterwards is
    guesswork."""
    _draft(client, demo_bank, "What is the fee?", "Ten birr.")
    client.post("/admin/api/demo/faq/translate", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    out = client.post("/admin/api/demo/faq/publish", json={},
                      headers={"X-Admin-Token": demo_bank.admin_token}).json()
    assert out["published"] == 5
    assert out["machine_translations"] == 4
    db_session.expire_all()
    entry = db_session.execute(
        select(AuditLog).where(AuditLog.action == "faq_published_bulk")
    ).scalars().one()
    assert entry.log_metadata["machine_translations"] == 4
    assert entry.log_metadata["by_language"]["am"] == 1


def test_publishing_twice_does_not_republish(
    client: TestClient, demo_bank: Any
) -> None:
    """Only drafts are touched, so a second run cannot restamp an approval
    somebody made deliberately with today's date and today's operator."""
    _draft(client, demo_bank, "What is the fee?", "Ten birr.")
    client.post("/admin/api/demo/faq/publish", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    again = client.post("/admin/api/demo/faq/publish", json={},
                        headers={"X-Admin-Token": demo_bank.admin_token}).json()
    assert again["published"] == 0


def test_an_unknown_language_is_refused(
    client: TestClient, demo_bank: Any
) -> None:
    assert client.post(
        "/admin/api/demo/faq/publish", json={"languages": ["fr"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).status_code == 422


def test_publishing_is_tenant_scoped(
    client: TestClient, demo_bank: Any, second_bank: Any, db_session: Any
) -> None:
    _draft(client, demo_bank, "What is the fee?", "Ten birr.")
    out = client.post(
        "/admin/api/other/faq/publish", json={},
        headers={"X-Admin-Token": second_bank.admin_token},
    ).json()
    assert out["published"] == 0
    db_session.expire_all()
    assert db_session.execute(select(Faq)).scalars().one().status == "draft"


def test_publishing_needs_documents_write(
    client: TestClient, demo_bank: Any
) -> None:
    assert client.post(
        "/admin/api/demo/faq/publish", json={}
    ).status_code in (401, 403)
