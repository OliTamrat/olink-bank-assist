"""Getting a bank's curated answers into every language it serves.

A curated answer is only ever served for the language it was written in —
`faq.key` includes the language — so an English-only table means an Amharic
customer never gets a tier-1 hit. They still get an answer from retrieval, but
they pay a model call and a second of latency for what an English speaker gets
free and instant.

The judgement this encodes is worth stating, because it is a change of mind.
Refusing to machine-translate at all sounds safe and is not: it means a hundred
and sixty answers in four more languages never get written, because nobody
starts six hundred and forty pieces of writing from a blank sheet. So the
machine drafts them, they are stored as DRAFTS, and a native speaker corrects a
sheet instead of authoring one. What must never happen is a machine draft being
served as the bank's own words, or overwriting a correction somebody made.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import faq
from bankassist.models import Faq


@pytest.fixture
def fake_translate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A translator that marks its output, so a test can tell machine text
    from a person's."""
    def translate(text: str, language: str, language_name: str, bank: str) -> str:
        return f"[{language}] {text}"

    monkeypatch.setattr("bankassist.llm.translate_curated", translate)


def _english(client: TestClient, bank: Any, question: str, answer: str) -> None:
    client.post(
        "/admin/api/demo/faq",
        json={"question": question, "answer": answer, "status": "published"},
        headers={"X-Admin-Token": bank.admin_token},
    )


def test_every_missing_language_is_drafted(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    out = client.post(
        "/admin/api/demo/faq/translate", json={},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert out["created"] == 5  # am, om, ti, so, sw
    db_session.expire_all()
    langs = {
        r.language for r in db_session.execute(select(Faq)).scalars().all()
    }
    assert langs == {"en", "am", "om", "ti", "so", "sw"}


def test_a_machine_translation_is_a_draft(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """The property the whole approach rests on. A model's Amharic has been
    read by nobody at the bank, and a curated answer is served verbatim with
    nothing downstream to catch it."""
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    client.post("/admin/api/demo/faq/translate", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    db_session.expire_all()
    drafted = db_session.execute(
        select(Faq).where(Faq.language != "en")
    ).scalars().all()
    assert drafted
    for row in drafted:
        assert row.status == "draft"
        assert row.approved_by is None


def test_a_customer_is_not_served_a_machine_translation(
    client: TestClient, demo_bank: Any, fake_translate: None
) -> None:
    """End to end: translating must not change one word of what a customer
    reads until somebody publishes it."""
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    client.post("/admin/api/demo/faq/translate", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    reply = client.post(
        "/chat/demo",
        json={"message": "[am] How do I open an account?", "language": "am"},
    ).json()
    assert "[am] Visit any branch." not in reply["reply"]


def test_a_corrected_translation_is_never_overwritten(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """The one way this could destroy real work: a reviewer spends an
    afternoon correcting the Amharic, somebody re-runs the batch, and it is
    gone."""
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    client.post("/admin/api/demo/faq/translate", json={},
                headers={"X-Admin-Token": demo_bank.admin_token})
    db_session.expire_all()
    amharic = db_session.execute(
        select(Faq).where(Faq.language == "am")
    ).scalars().one()
    amharic.answer = "የተስተካከለ መልስ"
    amharic.status = "published"
    db_session.commit()

    out = client.post("/admin/api/demo/faq/translate", json={},
                      headers={"X-Admin-Token": demo_bank.admin_token}).json()
    assert out["skipped"] >= 1
    db_session.expire_all()
    again = db_session.execute(
        select(Faq).where(Faq.language == "am")
    ).scalars().all()
    assert len(again) == 1
    assert again[0].answer == "የተስተካከለ መልስ"
    assert again[0].status == "published"


def test_one_failure_does_not_lose_the_batch(
    client: TestClient, demo_bank: Any, db_session: Any,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model outage partway through six hundred calls must leave what it
    finished, not roll back an afternoon."""
    calls = {"n": 0}

    def flaky(text: str, language: str, language_name: str, bank: str) -> str:
        calls["n"] += 1
        if language == "om":
            from bankassist.llm import LLMUnavailable
            raise LLMUnavailable("model down")
        return f"[{language}] {text}"

    monkeypatch.setattr("bankassist.llm.translate_curated", flaky)
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    out = client.post("/admin/api/demo/faq/translate", json={},
                      headers={"X-Admin-Token": demo_bank.admin_token}).json()
    assert out["failed"] == 1
    assert out["created"] == 4
    db_session.expire_all()
    langs = {r.language for r in db_session.execute(select(Faq)).scalars().all()}
    assert "om" not in langs
    assert {"am", "ti", "so"} <= langs


def test_a_subset_can_be_translated(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """A bank should be able to translate the twenty questions people actually
    ask before paying for the hundred and forty they do not."""
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    _english(client, demo_bank, "What is a PIN?", "A four digit code.")
    db_session.expire_all()
    first = db_session.execute(
        select(Faq).where(Faq.question == "What is a PIN?")
    ).scalars().one()
    out = client.post(
        "/admin/api/demo/faq/translate",
        json={"faq_ids": [first.id], "languages": ["am"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    ).json()
    assert out["created"] == 1


def test_translation_needs_documents_write(
    client: TestClient, demo_bank: Any
) -> None:
    assert client.post(
        "/admin/api/demo/faq/translate", json={}
    ).status_code in (401, 403)


def test_the_language_is_part_of_the_key() -> None:
    """Why this feature has to exist at all: an English answer can never match
    an Amharic question, however it is worded."""
    assert faq.key("How do I open an account?", "en") != faq.key(
        "How do I open an account?", "am"
    )


def test_correcting_the_translated_question_does_not_cause_a_duplicate(
    client: TestClient, demo_bank: Any, db_session: Any, fake_translate: None
) -> None:
    """The reason a translation records what it came from.

    Matching "is this language already covered" on the lookup key almost works,
    and fails exactly where it costs most: a reviewer corrects the wording of
    the Amharic *question*, which changes its key, so the next batch sees no
    Amharic and writes a second row beside the correction. The bank then has
    two Amharic answers to one question and a race over which a customer gets.
    """
    _english(client, demo_bank, "How do I open an account?", "Visit any branch.")
    client.post("/admin/api/demo/faq/translate", json={"languages": ["am"]},
                headers={"X-Admin-Token": demo_bank.admin_token})
    db_session.expire_all()
    amharic = db_session.execute(
        select(Faq).where(Faq.language == "am")
    ).scalars().one()
    assert amharic.source_faq_id is not None
    # A reviewer rewrites the question itself, not just the answer.
    amharic.question = "ሒሳብ እንዴት እከፍታለሁ?"
    amharic.lookup = faq.key(amharic.question, "am")
    db_session.commit()

    out = client.post("/admin/api/demo/faq/translate", json={"languages": ["am"]},
                      headers={"X-Admin-Token": demo_bank.admin_token}).json()
    assert out["created"] == 0
    assert out["skipped"] == 1
    db_session.expire_all()
    rows = db_session.execute(select(Faq).where(Faq.language == "am")).scalars().all()
    assert len(rows) == 1
    assert rows[0].question == "ሒሳብ እንዴት እከፍታለሁ?"
