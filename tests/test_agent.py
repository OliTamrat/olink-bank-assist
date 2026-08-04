"""Guardrail behavior through the public chat API (no LLM key: extractive mode)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _chat(client: TestClient, message: str, slug: str = "demo", **extra: Any) -> dict[str, Any]:
    resp = client.post(f"/chat/{slug}", json={"message": message, **extra})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_greeting(client: TestClient, demo_bank: Any) -> None:
    data = _chat(client, "Hello")
    assert data["intent"] == "greeting"
    assert "Demo Bank Ethiopia" in data["reply"]


def test_product_question_answers_from_knowledge_base(client: TestClient, demo_bank: Any) -> None:
    data = _chat(client, "What are the fixed deposit rates and minimum amount?")
    assert data["intent"] == "question"
    assert "10,000 birr" in data["reply"]
    titles = [s["title"] for s in data["sources"]]
    assert "Fixed (Time) Deposit Accounts" in titles
    assert data["handoff_created"] is False


def test_amharic_question_detected_and_answered(client: TestClient, demo_bank: Any) -> None:
    data = _chat(client, "የቁጠባ ሂሳብ ለመክፈት ምን ያስፈልጋል?")
    assert data["language"] == "am"
    assert "መታወቂያ" in data["reply"]


def test_account_specific_is_refused_safely(client: TestClient, demo_bank: Any) -> None:
    data = _chat(client, "What is my account balance?")
    assert data["intent"] == "account_specific"
    assert "security" in data["reply"].lower()
    assert data["sources"] == []


def test_investment_advice_gets_disclaimer_not_recommendation(
    client: TestClient, demo_bank: Any
) -> None:
    data = _chat(client, "Should I invest my savings in shares on the stock exchange?")
    assert data["intent"] == "investment_advice"
    assert "not personal investment advice" in data["reply"]
    assert "you should buy" not in data["reply"].lower()


def test_unknown_question_creates_handoff_instead_of_guessing(
    client: TestClient, demo_bank: Any
) -> None:
    data = _chat(client, "Do you sponsor weather satellites for chess tournaments?")
    assert data["handoff_created"] is True
    assert "birr" not in data["reply"]

    token = demo_bank.admin_token
    handoffs = client.get(
        "/admin/api/demo/handoffs", headers={"X-Admin-Token": token}
    ).json()
    assert any(h["reason"] == "unanswered_question" for h in handoffs)


def test_complaint_routes_to_human(client: TestClient, demo_bank: Any) -> None:
    data = _chat(client, "This is a complaint: an unauthorized transfer took my money!")
    assert data["intent"] == "complaint"
    assert data["handoff_created"] is True


def test_conversation_continuity_and_language_pinning(client: TestClient, demo_bank: Any) -> None:
    first = _chat(client, "hello", language="am")
    assert first["language"] == "am"
    second = _chat(client, "hello", conversation_id=first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    assert second["language"] == "am"  # pinned language survives ambiguous input
