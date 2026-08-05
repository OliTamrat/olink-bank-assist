"""The CBE prospect-demo tenant: prototype disclaimer, retrieval ranking on
real content, and guardrails still hold with a real institution's branding.

Two of the "must rank first" assertions here (savings, contact) are
regression tests for content-tuning bugs found while building this demo:
BM25 has no stemming, so verbose comparison text in one document can
out-rank the document that's actually about the query. Fixed by writing the
target document densely in the query's own terms — see seed_cbe.py history.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_disclaimer_shown_and_not_official(client: TestClient, cbe_bank: Any) -> None:
    cfg = client.get("/banks/cbe/public").json()
    assert cfg["disclaimer"]
    assert "not affiliated" in cfg["disclaimer"].lower()
    assert "unofficial" in cfg["disclaimer"].lower()


def test_savings_rate_question_leads_with_ordinary_savings(
    client: TestClient, cbe_bank: Any
) -> None:
    data = client.post(
        "/chat/cbe", json={"message": "What is the interest rate on a savings account?"}
    ).json()
    assert data["sources"][0]["title"] == "Ordinary Savings Account"
    assert "7%" in data["reply"]


def test_contact_question_leads_with_branches_doc(client: TestClient, cbe_bank: Any) -> None:
    data = client.post(
        "/chat/cbe", json={"message": "What are your customer care contact details?"}
    ).json()
    assert data["sources"][0]["title"] == "Branches, Hours, and Customer Care"


def test_diaspora_question_answers_from_real_content(client: TestClient, cbe_bank: Any) -> None:
    data = client.post(
        "/chat/cbe", json={"message": "How do I open a diaspora account from abroad?"}
    ).json()
    assert "USD 100" in data["reply"] or "USD 5,000" in data["reply"]


def test_amharic_mobile_banking_question(client: TestClient, cbe_bank: Any) -> None:
    data = client.post(
        "/chat/cbe", json={"message": "የሞባይል ባንኪንግ እንዴት አስጀምራለሁ?"}
    ).json()
    assert data["language"] == "am"
    assert "889" in data["reply"]


def test_guardrails_hold_with_real_bank_branding(client: TestClient, cbe_bank: Any) -> None:
    balance = client.post("/chat/cbe", json={"message": "What is my account balance?"}).json()
    assert balance["intent"] == "account_specific"
    assert "security" in balance["reply"].lower()

    advice = client.post(
        "/chat/cbe", json={"message": "Should I invest my savings in the stock exchange?"}
    ).json()
    assert "not personal investment advice" in advice["reply"]

    unknown = client.post(
        "/chat/cbe", json={"message": "Do you sponsor rocket launches?"}
    ).json()
    assert unknown["handoff_created"] is True
