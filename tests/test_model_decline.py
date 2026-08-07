"""When the model declines, that is a knowledge gap — not an answer.

Found on the live Awash demo. Asked in Afaan Oromo how to *use* an ATM, the
assistant replied "Odeeffannoo sana hin qabu" ("I don't have that
information") — correctly, since Awash's only ATM document covers fraud
safety. But retrieval had succeeded, so the reply shipped down the answer
path: a source chip attached to a non-answer, nothing offered to the
customer, and no handoff filed, so the bank never learned the content was
missing.

The model refusing to invent ATM instructions is the safety doctrine
working. Treating that refusal as a delivered answer is the bug.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import agent, llm


@pytest.fixture
def _decline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the model to decline, as it does when context is off-target."""

    def declined(*args: Any, **kwargs: Any) -> str:
        raise llm.LLMDeclined(llm.INSUFFICIENT_CONTEXT)

    monkeypatch.setattr(agent, "generate_answer", declined)


def test_a_decline_files_a_handoff(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    # The bank has to see that customers are asking for content it lacks.
    data = client.post(
        "/chat/awash", json={"message": "Waa'ee ATM beekuu barbaade, Akkamitan fayyadama?"}
    ).json()
    assert data["handoff_created"] is True


def test_a_decline_offers_somewhere_to_go(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    data = client.post(
        "/chat/awash", json={"message": "Waa'ee ATM beekuu barbaade, Akkamitan fayyadama?"}
    ).json()
    assert data["suggestions"], "a decline must not be a dead end"


def test_a_decline_claims_no_source(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    # A source chip on a non-answer implies the reply came from that
    # document. It did not.
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert data["sources"] == []


def test_the_sentinel_never_reaches_the_customer(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert llm.INSUFFICIENT_CONTEXT not in data["reply"]


def test_a_decline_answers_in_the_asked_language(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    data = client.post(
        "/chat/awash", json={"message": "Waa'ee ATM beekuu barbaade, Akkamitan fayyadama?"}
    ).json()
    assert data["language"] == "om"


def test_a_decline_does_not_fall_back_to_quoting_the_rejected_text(
    client: TestClient, awash_bank: Any, _decline: None
) -> None:
    # LLMUnavailable falls back to an extractive quote; LLMDeclined must not.
    # The model just judged that text does not answer the question, so
    # pasting it back would be a worse answer than admitting the gap.
    data = client.post("/chat/awash", json={"message": "How do I use an ATM?"}).json()
    assert "shield the keypad" not in data["reply"].lower()


def test_an_unreachable_model_still_falls_back_to_extractive(
    client: TestClient, awash_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other direction must be unchanged: an outage still degrades to a
    # sourced quote rather than an admission of ignorance.
    def unavailable(*args: Any, **kwargs: Any) -> str:
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(agent, "generate_answer", unavailable)
    data = client.post(
        "/chat/awash", json={"message": "How can I protect myself from fraud?"}
    ).json()
    assert data["handoff_created"] is False
    assert data["sources"], "an outage must still answer from retrieved text"


def test_generate_answer_raises_declined_on_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from bankassist import config
    from bankassist.retrieval import RetrievedChunk

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    config.reset_settings()

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "INSUFFICIENT_CONTEXT"}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    chunk = RetrievedChunk("c", "d", "T", "text", 1.0)
    with pytest.raises(llm.LLMDeclined):
        llm.generate_answer("q", [chunk], "en", "Awash Bank")
