"""The Dashen Bank prospect-demo tenant: prototype disclaimer, real content
on real questions, comparison intent, and guardrails — same coverage
pattern as test_cbe_demo.py, applied to the second real-bank tenant.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_disclaimer_shown_and_not_official(client: TestClient, dashen_bank: Any) -> None:
    cfg = client.get("/banks/dashen/public").json()
    assert cfg["disclaimer"]
    assert "not affiliated" in cfg["disclaimer"].lower()
    assert "unofficial" in cfg["disclaimer"].lower()
    assert "Dashen Bank" in cfg["disclaimer"]


def test_amole_question_answers_from_real_content(client: TestClient, dashen_bank: Any) -> None:
    data = client.post("/chat/dashen", json={"message": "What is Amole?"}).json()
    assert "Amole" in data["reply"]
    assert data["sources"][0]["title"] == "Amole and Dashen Mobile Plus"


def test_swift_code_question_answers_correctly(client: TestClient, dashen_bank: Any) -> None:
    data = client.post("/chat/dashen", json={"message": "What is your SWIFT code?"}).json()
    assert "DASHETAA" in data["reply"]
    assert data["sources"][0]["title"] == "International Transfers and SWIFT Code"


def test_amharic_savings_question(client: TestClient, dashen_bank: Any) -> None:
    data = client.post(
        "/chat/dashen", json={"message": "የቁጠባ ሂሳብ ለመክፈት ምን ያስፈልጋል?"}
    ).json()
    assert data["language"] == "am"
    assert "መታወቂያ" in data["reply"]


def test_comparison_question_sells_dashen_without_naming_rival(
    client: TestClient, dashen_bank: Any
) -> None:
    # "Is Dashen better?" asked of the Dashen assistant is unambiguous
    # without naming a rival — see classifier.py's bare-form comparison
    # pattern.
    data = client.post(
        "/chat/dashen", json={"message": "Is Dashen Bank better than my current bank?"}
    ).json()
    assert data["intent"] == "comparison"
    assert data["handoff_created"] is False
    assert data["sources"][0]["title"] == "Why Choose Dashen Bank"
    assert "cbe" not in data["reply"].lower() and "awash" not in data["reply"].lower()
    assert "1996" in data["reply"] or "Amole" in data["reply"]


def test_guardrails_hold_with_real_bank_branding(client: TestClient, dashen_bank: Any) -> None:
    balance = client.post(
        "/chat/dashen", json={"message": "What is my account balance?"}
    ).json()
    assert balance["intent"] == "account_specific"
    assert "security" in balance["reply"].lower()

    advice = client.post(
        "/chat/dashen", json={"message": "Should I invest my savings in the stock exchange?"}
    ).json()
    assert "not personal investment advice" in advice["reply"]

    unknown = client.post(
        "/chat/dashen", json={"message": "Do you sponsor rocket launches?"}
    ).json()
    assert unknown["handoff_created"] is True


def test_cross_tenant_isolation_from_cbe(
    client: TestClient, dashen_bank: Any, cbe_bank: Any
) -> None:
    data = client.post(
        "/chat/dashen", json={"message": "What does CBE offer that you don't?"}
    ).json()
    assert "Ordinary Savings Account" not in data["reply"]
    assert "CBE Noor" not in data["reply"]
