"""The differentiator question — "what makes you different from other banks?"
— is the one a bank's own executives ask a sales demo first. It used to fall
through to retrieval and hand off, because no bank's knowledge base discusses
how it compares to competitors, so the assistant looked unable to sell the
very institution it represents.

These lock in that the question routes to COMPARISON (and therefore the
why-choose document) across all three real tenants and all the natural
phrasings, while product questions that merely contain "different" still go
to retrieval.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import classifier

# Phrasings a real person uses, in place of the narrow "is X better than Y"
# the classifier originally required.
DIFFERENTIATOR_PHRASINGS = [
    "What makes {name} different from other banks in Ethiopia?",
    "What makes {name} different?",
    "What sets {name} apart?",
    "How is {name} different from other banks?",
    "Why should I bank with {name}?",
    "Why {name} over other banks?",
    "What is the difference between {name} and other banks?",
]


@pytest.mark.parametrize("phrasing", DIFFERENTIATOR_PHRASINGS)
@pytest.mark.parametrize("name", ["Awash Bank", "CBE", "Dashen Bank"])
def test_differentiator_phrasings_classify_as_comparison(phrasing: str, name: str) -> None:
    text = phrasing.format(name=name)
    assert classifier.classify_intent(text, (name,)) == classifier.COMPARISON, text


def test_bank_agnostic_differentiator_also_classifies() -> None:
    # No tenant name at all — "you"/"this bank" must work the same, since the
    # customer is already talking to the bank.
    for text in (
        "What makes you different from other banks?",
        "What sets you apart?",
        "How are you different?",
        "Why should I bank with you?",
    ):
        assert classifier.classify_intent(text, ()) == classifier.COMPARISON, text


def test_product_question_containing_different_is_not_a_comparison() -> None:
    # "different" alone must not hijack an ordinary product question — this
    # names a product, not the bank, so it belongs on the retrieval path.
    for text in (
        "What makes Sharik different from a normal savings account?",
        "How is a fixed deposit different from a savings account?",
    ):
        assert classifier.classify_intent(text, ("Dashen Bank", "dashen")) != (
            classifier.COMPARISON
        ), text


def test_awash_answers_the_live_demo_question_from_its_why_choose_doc(
    client: TestClient, awash_bank: Any
) -> None:
    # The exact question asked in the live demo, which previously handed off.
    resp = client.post(
        "/chat/awash",
        json={"message": "What makes awash bank different from others banks in Ethiopia"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["intent"] == "comparison"
    assert data["handoff_created"] is False
    assert data["sources"], "should cite the why-choose document"
    assert data["sources"][0]["title"] == "Why Choose Awash Bank"


def test_dashen_answers_the_differentiator_question_too(
    client: TestClient, dashen_bank: Any
) -> None:
    resp = client.post("/chat/dashen", json={"message": "What sets Dashen Bank apart?"})
    data = resp.json()
    assert data["intent"] == "comparison"
    assert data["handoff_created"] is False
    assert data["sources"][0]["title"] == "Why Choose Dashen Bank"


def test_differentiator_answer_never_names_a_competitor(
    client: TestClient, awash_bank: Any, cbe_bank: Any
) -> None:
    # Selling itself must not become disparaging a named rival — the same
    # property the CBE adversarial battery already asserts.
    resp = client.post(
        "/chat/awash",
        json={"message": "What makes Awash Bank different from CBE and Dashen?"},
    )
    data = resp.json()
    assert data["intent"] == "comparison"
    lowered = data["reply"].lower()
    assert "cbe" not in lowered
    assert "dashen" not in lowered


def test_widget_and_admin_pages_are_not_cached(client: TestClient) -> None:
    # A cached copy pins the whole inlined UI, so a deploy can silently fail
    # to reach a returning visitor.
    for path in ("/widget", "/admin"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "no-store" in resp.headers.get("cache-control", ""), path
