"""The same question must not be harder to answer because of the language
it is asked in.

The stopword set was English-only, and the informativeness gate scales its
bar with a query's content-word count — so untagged function words in
Amharic, Afaan Oromo, Tigrinya and Somali inflated the denominator and
raised the burden of proof. Found on the live Awash demo: "ስለ ATM ማወቅ ፈልጌ
ነበር" handed off while a bare "ATM" answered fine, purely because the
Amharic function words counted as content.

That is the worst possible place for an asymmetry in a product sold on
native-language support, so these pin the parity down directly.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.retrieval import (
    _STOPWORDS,
    MIN_INFORMATIVE_RATIO,
    SHORT_QUERY_CONTENT_WORDS,
    tokenize,
)


def _bar(query: str) -> int:
    """The informative-match bar retrieve() will apply to this query."""
    content = [t for t in tokenize(query) if t not in _STOPWORDS]
    if not content:
        return 0
    if len(content) <= SHORT_QUERY_CONTENT_WORDS:
        return 1
    return math.ceil(len(content) * MIN_INFORMATIVE_RATIO)


@pytest.mark.parametrize(
    ("english", "translated"),
    [
        ("I wanted to know about ATM", "ስለ ATM ማወቅ ፈልጌ ነበር"),
        ("I want to know about ATM", "waa'ee ATM beekuu barbaada"),
        ("What is a savings account?", "ብዛዕባ savings account እንታይ እዩ"),
    ],
)
def test_translated_question_is_not_held_to_a_higher_bar(
    english: str, translated: str
) -> None:
    assert _bar(translated) <= _bar(english), (
        f"{translated!r} needs {_bar(translated)} informative matches vs "
        f"{_bar(english)} for {english!r} — the non-English phrasing is harder"
    )


def test_amharic_function_words_do_not_count_as_content() -> None:
    # The exact words from the failing demo message.
    for word in ("ስለ", "ማወቅ", "ፈልጌ", "ነበር", "እንዴት", "ምን"):
        assert word in _STOPWORDS, word


def test_the_live_demo_question_now_answers(
    client: TestClient, awash_bank: Any
) -> None:
    # "I wanted to know about ATM" in Amharic — handed off before this fix.
    resp = client.post("/chat/awash", json={"message": "ስለ ATM ማወቅ ፈልጌ ነበር"})
    data = resp.json()
    assert data["handoff_created"] is False, "the Amharic phrasing must answer"
    assert data["sources"], "and must cite a real document"


def test_amharic_and_english_reach_the_same_answer(
    client: TestClient, awash_bank: Any
) -> None:
    am = client.post("/chat/awash", json={"message": "ስለ ATM ማወቅ ፈልጌ ነበር"}).json()
    en = client.post("/chat/awash", json={"message": "I wanted to know about ATM"}).json()
    assert am["handoff_created"] == en["handoff_created"]
    assert [s["title"] for s in am["sources"]] == [s["title"] for s in en["sources"]]


def test_amharic_content_words_still_count(client: TestClient, awash_bank: Any) -> None:
    # Guard the other direction: the stopword lists must not have swallowed
    # real banking vocabulary, or Amharic retrieval would answer from noise.
    data = client.post(
        "/chat/awash", json={"message": "የሞባይል ባንኪንግ እንዴት እጠቀማለሁ"}
    ).json()
    assert data["handoff_created"] is False
    assert data["sources"], "a real Amharic question must still retrieve"
