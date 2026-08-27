
"""The Awash Bank prospect-demo tenant: prototype disclaimer, real content
on real questions, comparison intent, and guardrails — same coverage
pattern as test_cbe_demo.py, applied to the third real-bank tenant.

test_swift_code_question_answers_correctly and
test_comparison_question_does_not_leak_unrelated_document are regression
tests for the retrieval informative-match boundary bug found while
building this tenant: a term sitting in *exactly* half the corpus (here,
the word "bank") slipped past the old "<=" gate and let an unrelated
document answer a short comparison-shaped query. Fixed in retrieval.py by
tightening the boundary to strictly below half.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from bankassist.i18n import t


def test_disclaimer_shown_and_not_official(client: TestClient, awash_bank: Any) -> None:
    cfg = client.get("/banks/awash/public").json()
    assert cfg["disclaimer"]
    assert "not affiliated" in cfg["disclaimer"].lower()
    assert "unofficial" in cfg["disclaimer"].lower()
    assert "Awash Bank" in cfg["disclaimer"]


def test_mobile_banking_activation_answers_from_real_content(
    client: TestClient, awash_bank: Any
) -> None:
    data = client.post(
        "/chat/awash", json={"message": "How do I activate mobile banking?"}
    ).json()
    assert "901" in data["reply"]
    assert data["sources"][0]["title"] == "AwashBIRR Mobile Banking"


def test_swift_code_question_answers_correctly(client: TestClient, awash_bank: Any) -> None:
    data = client.post("/chat/awash", json={"message": "What is your SWIFT code?"}).json()
    assert "AWINETAA" in data["reply"]
    assert data["sources"][0]["title"] == "International Transfers and SWIFT Code"


def test_amharic_savings_question(client: TestClient, awash_bank: Any) -> None:
    data = client.post(
        "/chat/awash", json={"message": "የቁጠባ ሂሳብ ለመክፈት ምን ያስፈልጋል?"}
    ).json()
    assert data["language"] == "am"
    assert "መታወቂያ" in data["reply"]


def test_comparison_question_sells_awash_without_naming_rival(
    client: TestClient, awash_bank: Any
) -> None:
    # "Is Awash better?" asked of the Awash assistant is unambiguous
    # without naming a rival — see classifier.py's bare-form comparison
    # pattern.
    data = client.post(
        "/chat/awash", json={"message": "Is Awash Bank better than my current bank?"}
    ).json()
    assert data["intent"] == "comparison"
    assert data["handoff_created"] is False
    assert "cbe" not in data["reply"].lower() and "dashen" not in data["reply"].lower()
    assert "1994" in data["reply"] or "Ikhlas" in data["reply"]


def test_comparison_question_does_not_leak_unrelated_document(
    client: TestClient, awash_bank: Any
) -> None:
    # "Is CBE Bank better?" while chatting with Awash names a bank not
    # covered by the comparison classifier's alias-scoping (see
    # classifier.py's documented scoping limits) — the important property
    # is that it must never return an unrelated Awash document as if it
    # answered the question, only an honest "I don't know".
    data = client.post("/chat/awash", json={"message": "Is CBE Bank better?"}).json()
    assert data["handoff_created"] is True
    assert data["sources"] == []


def test_guardrails_hold_with_real_bank_branding(client: TestClient, awash_bank: Any) -> None:
    balance = client.post(
        "/chat/awash", json={"message": "What is my account balance?"}
    ).json()
    assert balance["intent"] == "account_specific"
    # The refusal is the fixed template, whatever its wording. Asserting a
    # particular sentence is what made one copy change break sixteen tests.
    assert balance["reply"].startswith(t("en", "account_help"))

    advice = client.post(
        "/chat/awash", json={"message": "Should I invest my savings in the stock exchange?"}
    ).json()
    assert "not personal investment advice" in advice["reply"]

    unknown = client.post(
        "/chat/awash", json={"message": "Do you sponsor rocket launches?"}
    ).json()
    assert unknown["handoff_created"] is True


def test_cross_tenant_isolation_from_dashen(
    client: TestClient, awash_bank: Any, dashen_bank: Any
) -> None:
    data = client.post(
        "/chat/awash", json={"message": "What does Dashen offer that you don't?"}
    ).json()
    assert "Amole" not in data["reply"]
    assert "Dashen Mobile Plus" not in data["reply"]


def test_transfer_fee_question_in_everyday_words(
    client: TestClient, awash_bank: Any
) -> None:
    """Reported from the live demo, verbatim.

    "Transfers to Other Banks and Wallets" answers this — fees vary by amount
    and channel, and AwashBIRR shows the applicable fee before you confirm.
    The customer never saw it: they said "charged" and "sent", the document
    says "fees" and "transfer", and BM25 matches exact tokens.

    The tell was that suggest_topics still ranked that exact document first
    and offered it as a chip. The system knew which document answered the
    question and declined to read it.
    """
    data = client.post(
        "/chat/awash",
        json={"message": "How much do I get charged if I sent from other banks"},
    ).json()
    assert [s["title"] for s in data["sources"]] == ["Transfers to Other Banks and Wallets"]


def test_the_same_question_asked_four_other_ways(
    client: TestClient, awash_bank: Any
) -> None:
    """Vocabulary, not phrasing luck.

    One passing phrasing would only prove the synonym list was written from
    that phrasing — the mistake this project has already made once, with a
    guardrail regex tested using wording derived from itself.
    """
    for message in (
        "How much is the transfer fee to another bank?",
        "What are the fees for transfers to other banks?",
        "What does it cost to send money to another bank?",
        "Is there a charge for sending money to another bank?",
    ):
        data = client.post("/chat/awash", json={"message": message}).json()
        titles = [s["title"] for s in data["sources"]]
        assert "Transfers to Other Banks and Wallets" in titles, message
