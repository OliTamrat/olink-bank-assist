"""Universally-standard banking questions, answered without bank content.

ATM mechanics are identical on every NCR and Diebold machine on earth, and an
assistant that cannot explain what a PIN is looks broken on exactly the
questions a first-time customer asks. So this is a deliberate, bounded
exception to tool-output-is-truth.

The boundary is the whole point, and it is what these mostly test. The failure
mode is not "explains how to use an ATM" — it is helpfully appending "you can
usually withdraw up to 5,000 birr a day", inventing a policy for a bank the
model knows nothing about. A hallucinated figure in a screenshot is what loses
a bank deal.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import agent, llm
from bankassist.i18n import t
from bankassist.models import Bank, Handoff

UNIVERSAL_ANSWER = (
    "Insert your card, enter your PIN while shielding the keypad, choose the "
    "amount, then take your card and cash before leaving the machine."
)


@pytest.fixture
def _bank_content_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrieval finds something, but it does not answer the question.

    This is the live case: "how do I use an ATM" retrieves Awash's ATM *safety*
    document, and the model correctly declines because safety guidance does not
    explain usage. General knowledge is only reached after that decline.
    """

    def declined(*args: Any, **kwargs: Any) -> str:
        raise llm.LLMDeclined(llm.INSUFFICIENT_CONTEXT)

    monkeypatch.setattr(agent, "generate_answer", declined)


@pytest.fixture
def _answers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The model answers universal questions."""
    seen: list[str] = []

    def fake(question: str, language: str, bank_name: str) -> str:
        seen.append(question)
        return UNIVERSAL_ANSWER

    monkeypatch.setattr(agent, "answer_from_general_knowledge", fake)
    return seen


@pytest.fixture
def _refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model refuses, as it must for anything bank-specific."""

    def fake(question: str, language: str, bank_name: str) -> str:
        raise llm.LLMDeclined(llm.INSUFFICIENT_CONTEXT)

    monkeypatch.setattr(agent, "answer_from_general_knowledge", fake)


def test_a_universal_question_is_answered(
    client: TestClient,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert "Insert your card" in data["reply"]
    assert data["general_knowledge"] is True


def test_the_answer_claims_no_source(
    client: TestClient,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    # It genuinely came from no document. A source chip would say otherwise.
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert data["sources"] == []


def test_the_answer_is_labelled_as_general_guidance(
    client: TestClient,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    # It must never read as the bank speaking.
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert "General guidance" in data["reply"]
    assert "Awash Bank" in data["reply"], "should point at the bank for specifics"


def test_it_still_records_the_content_gap(
    client: TestClient,
    db_session: Session,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    # Answering must not hide the fact that the bank has no content here —
    # that record is what prompts the bank to write some.
    client.post("/chat/awash", json={"message": "How do I use an ATM?"})
    reasons = [
        h.reason
        for h in db_session.execute(
            select(Handoff).where(Handoff.bank_id == awash_bank.id)
        ).scalars()
    ]
    assert "answered_from_general_knowledge" in reasons


def test_a_refusal_falls_back_to_the_ordinary_miss(
    client: TestClient,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _refuses: None,
) -> None:
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert data["general_knowledge"] is False
    assert data["handoff_created"] is True
    assert data["suggestions"], "still offers somewhere to go"


def test_it_is_never_reached_when_the_bank_has_real_content(
    client: TestClient, awash_bank: Any, _answers: list[str]
) -> None:
    # A question the corpus answers must come from the corpus, not from
    # general knowledge.
    data = client.post(
        "/chat/awash", json={"message": "How can I protect myself from fraud?"}
    ).json()
    assert data["sources"], "should answer from the bank's own documents"
    assert data["general_knowledge"] is False
    assert _answers == [], "general knowledge must not run when content exists"


def test_the_account_data_refusal_is_unaffected(
    client: TestClient, awash_bank: Any, _answers: list[str]
) -> None:
    # The security guardrail is a separate path and must not be softened by
    # any of this.
    data = client.post(
        "/chat/awash", json={"message": "What is my account balance?"}
    ).json()
    assert data["intent"] == "account_specific"
    assert data["general_knowledge"] is False
    # The refusal is the fixed template, whatever its wording. Asserting a
    # particular sentence is what made one copy change break sixteen tests.
    assert data["reply"].startswith(t("en", "account_help"))
    assert _answers == []


def test_a_bank_can_switch_it_off(
    client: TestClient,
    db_session: Session,
    awash_bank: Any,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    # A compliance-conservative bank must be able to require that every answer
    # come from its own published content.
    bank = db_session.execute(
        select(Bank).where(Bank.slug == "awash")
    ).scalar_one()
    bank.allow_general_knowledge = False
    db_session.commit()

    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert data["general_knowledge"] is False
    assert _answers == [], "must not be called at all when disabled"
    assert data["handoff_created"] is True


def test_the_boundary_prompt_forbids_the_dangerous_categories() -> None:
    """The prompt is the enforcement mechanism, so assert it says so.

    Every item here is something that varies by bank or country. Getting one
    wrong invents a policy for the bank — the failure that costs a deal.
    """
    prompt = llm._GENERAL_PROMPT
    for forbidden in (
        "fee",
        "interest rate",
        "limit",
        "eligibility",
        "phone numbers",
        "branch locations",
        "Never state or imply a number",
        "INSUFFICIENT_CONTEXT",
    ):
        assert forbidden in prompt, f"boundary must forbid: {forbidden}"


def test_the_model_declining_raises_rather_than_leaking_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from bankassist import config

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    config.reset_settings()

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "INSUFFICIENT_CONTEXT"}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(llm.LLMDeclined):
        llm.answer_from_general_knowledge("What is your daily ATM limit?", "en", "Awash Bank")


def test_a_general_knowledge_answer_puts_nobody_in_the_queue(
    client: TestClient,
    awash_bank: Any,
    db_session: Session,
    _bank_content_does_not_answer: None,
    _answers: list[str],
) -> None:
    """The exact case a bank reported from its live dashboard.

    A customer asked about service fees, got a complete answer, and left. The
    dashboard counted them among "9 escalations waiting for someone" — with no
    contact details, because the assistant had correctly not asked for any. An
    operator opening that queue found most of it was nobody.

    The row still exists: the bank having no published content on a subject
    customers ask about is exactly what Content Gaps reports. What changed is
    that it is no longer somebody's work.
    """
    from bankassist.models import Handoff

    # A universally-answerable question the bank has published nothing on —
    # the same shape as the reported case, but one Awash's seeded content does
    # not already cover, so the general-knowledge path is actually taken.
    resp = client.post(
        "/chat/awash",
        json={"message": "How do I use an ATM?", "language": "en"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # The customer is answered, and promised no callback.
    assert body["general_knowledge"] is True
    assert body["handoff_created"] is False

    row = db_session.execute(
        select(Handoff).where(Handoff.reason == "answered_from_general_knowledge")
    ).scalars().first()
    assert row is not None, "the content signal must still be recorded"
    assert row.needs_person is False

    # The queue an operator opens does not contain them...
    queue = client.get(
        "/admin/api/awash/handoffs?status=open",
        headers={"X-Admin-Token": awash_bank.admin_token},
    ).json()
    assert all(h["reason"] != "answered_from_general_knowledge" for h in queue)

    # ...and the number on the dashboard agrees with the queue, which is the
    # property that actually broke: a count the queue could not account for.
    analytics = client.get(
        "/admin/api/awash/analytics",
        headers={"X-Admin-Token": awash_bank.admin_token},
    ).json()
    assert analytics["handoffs"]["open"] == len(queue)

    # But Content Gaps still sees it — the row is the whole point there.
    gaps = client.get(
        "/admin/api/awash/content-gaps",
        headers={"X-Admin-Token": awash_bank.admin_token},
    ).json()
    assert any("atm" in g["examples"][0].lower() for g in gaps)
