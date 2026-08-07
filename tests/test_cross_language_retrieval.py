"""Lexical retrieval cannot match across languages.

Measured against the real Awash corpus: "loan" retrieves Personal and
Business Loans, while "liqii" — the same word in Afaan Oromo — retrieves
nothing at all. "liqii" and "loan" share no characters, so BM25 has nothing
to work with, and no amount of good content on the bank's side changes that.

So the question is rendered as an English search query and retrieval is
retried. Only the search text is translated: the answer is still generated
from the retrieved documents in the customer's own language, and the
informativeness gate still decides whether anything was really found — a bad
translation costs a miss, never a wrong answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import agent, llm

# The real Oromo -> English mapping, standing in for the model.
OROMO_TO_ENGLISH = {
    "Waa'ee liqii barbaada": "I want to know about loans",
    "liqii akkamitti argadha": "how do I get a loan",
    "herrega banachuu": "open an account",
}


@pytest.fixture
def _translates(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record what gets sent for translation, and translate it."""
    seen: list[str] = []

    def fake(question: str) -> str:
        seen.append(question)
        return OROMO_TO_ENGLISH.get(question, question)

    monkeypatch.setattr(agent, "translate_for_search", fake)
    return seen


@pytest.mark.parametrize("question", list(OROMO_TO_ENGLISH))
def test_oromo_questions_now_retrieve(
    client: TestClient, awash_bank: Any, _translates: list[str], question: str
) -> None:
    data = client.post("/chat/awash", json={"message": question}).json()
    assert data["sources"], f"{question!r} should retrieve after translation"
    assert data["handoff_created"] is False


def test_the_answer_stays_in_the_customers_language(
    client: TestClient, awash_bank: Any, _translates: list[str]
) -> None:
    # Translating the query must not switch the reply to English.
    data = client.post(
        "/chat/awash", json={"message": "Waa'ee liqii barbaada"}
    ).json()
    assert data["language"] == "om"


def test_english_questions_are_never_translated(
    client: TestClient, awash_bank: Any, _translates: list[str]
) -> None:
    # An English question that retrieves must not pay for a model call.
    client.post("/chat/awash", json={"message": "How do I get a loan?"})
    assert _translates == []


def test_a_successful_retrieval_is_never_translated(
    client: TestClient, awash_bank: Any, _translates: list[str]
) -> None:
    # Amharic that already matches (shared tokens like ATM) must not either.
    client.post("/chat/awash", json={"message": "ስለ ATM ማወቅ ፈልጌ ነበር"})
    assert _translates == [], "translation is a miss-path affordance only"


def test_a_failed_translation_degrades_to_the_normal_miss(
    client: TestClient, awash_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unreachable model must not turn a miss into an error.
    def unavailable(question: str) -> str:
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(agent, "translate_for_search", unavailable)
    data = client.post("/chat/awash", json={"message": "Waa'ee liqii barbaada"}).json()
    assert data["handoff_created"] is True
    assert data["suggestions"], "still offers somewhere to go"


def test_a_translation_that_still_misses_behaves_like_any_miss(
    client: TestClient, awash_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The gate still applies to the translated query — translation buys a
    # second attempt, not a bypass.
    monkeypatch.setattr(
        agent, "translate_for_search", lambda q: "quantum astrophysics syllabus"
    )
    data = client.post("/chat/awash", json={"message": "Waa'ee liqii barbaada"}).json()
    assert data["handoff_created"] is True
    assert data["sources"] == []


def test_translation_is_not_retried_when_it_returns_the_same_text(
    client: TestClient, awash_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"retrieve": 0}
    real_retrieve = agent.retrieve

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls["retrieve"] += 1
        return real_retrieve(*args, **kwargs)

    monkeypatch.setattr(agent, "retrieve", counting)
    monkeypatch.setattr(agent, "translate_for_search", lambda q: q)
    client.post("/chat/awash", json={"message": "Waa'ee liqii barbaada"})
    assert calls["retrieve"] == 1, "an unchanged translation must not re-search"
