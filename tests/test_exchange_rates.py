"""Foreign exchange: answer the question, never quote the number.

Reported from the demo — "a basic rate exchange question the chat assistant
doesn't have answer". The demo tenant had no currency document at all, so
retrieval found nothing and the assistant correctly said so. Correct, and the
worst possible first impression: exchange rates are among the first things
anyone asks an Ethiopian bank.

The content is the fix. The test that matters is the second one.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from bankassist.seed import _DOCS

FX_TITLES = ("Foreign Exchange and Currency", "የውጭ ምንዛሬ (Foreign Exchange — Amharic)")


def _fx_docs() -> list[dict[str, str]]:
    return [d for d in _DOCS if d["title"] in FX_TITLES]


def test_the_demo_bank_can_answer_a_currency_question(
    client: TestClient, demo_bank: Any
) -> None:
    for question in (
        "What is the exchange rate today?",
        "Do you exchange dollars?",
        "Can I buy euros for travel?",
    ):
        body = client.post("/chat/demo", json={"message": question}).json()
        assert body["outcome"] == "answered", f"{question} -> {body['outcome']}"
        assert body["sources"], question


def test_an_amharic_currency_question_is_answered_in_amharic(
    client: TestClient, demo_bank: Any
) -> None:
    """The Amharic document exists so that this does not fall back to English
    or to nothing — currency is exactly the question a walk-in customer asks
    in their own language."""
    body = client.post("/chat/demo", json={"message": "የውጭ ምንዛሬ ዋጋ ስንት ነው?"}).json()
    assert body["language"] == "am"
    assert body["outcome"] == "answered"


def test_no_exchange_rate_figure_is_ever_written_into_the_content() -> None:
    """THE INVARIANT. A rate in a static document is wrong the next morning,
    and a confidently stale rate is far worse than an honest pointer to where
    the live one lives.

    This will fail the moment somebody helpfully adds "1 USD = 57.20 birr" to
    make the demo look richer. That is the point: the demo looks richer and
    starts lying the following day.
    """
    assert _fx_docs(), "the currency documents are gone"
    for doc in _fx_docs():
        # A decimal number is what a quoted rate looks like in every phrasing
        # of it — "57.20", "1:57.2", "57.20 birr".
        assert not re.search(r"\d+[.,]\d", doc["content"]), (
            f"{doc['title']} appears to quote a rate"
        )


def test_the_content_says_where_the_live_rate_is() -> None:
    """Refusing to quote a figure is only honest if it also says where to get
    one. Otherwise it is a dead end wearing the costume of integrity."""
    english = [d for d in _fx_docs() if d["language"] == "en"][0]["content"].lower()
    assert "website" in english
    assert "app" in english
    assert "branch" in english
