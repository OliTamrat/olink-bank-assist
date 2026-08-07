"""Greeting handling across the five supported languages.

Found on the live Awash demo: "Hi akkam?" and "ሰላም ኦሊ እባላለሁ" both failed and
returned "I don't have verified information about that". Single greetings
already worked — the pattern accepted exactly ONE greeting token and anchored
to end-of-string, so the most natural openings a bilingual customer types
(two greetings together, or a greeting plus a name) fell through to
retrieval, matched nothing and handed off.

Language detection was never the problem and was correct throughout; these
also pin that down so a future fix doesn't "correct" the wrong layer.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import classifier

ALIASES = ("Awash Bank", "awash")


@pytest.mark.parametrize(
    "text",
    [
        # The two that actually failed in the demo.
        "Hi akkam?",
        "ሰላም ኦሊ እባላለሁ",
        # Single greetings, which already worked — keep them working.
        "hi",
        "Hello",
        "Selam",
        "akkam",
        "ሰላም",
        "Good morning",
        # Combinations and full greetings.
        "Hello selam",
        "Hi, akkam jirta?",
        "selam, hello",
        "ደህና ነህ",
        "Akkam jirtu",
        "ሰላም፣ ጤና ይስጥልኝ",
    ],
)
def test_greetings_are_recognised(text: str) -> None:
    assert classifier.classify_intent(text, ALIASES) == classifier.GREETING, text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A greeting prefix must not swallow the actual request.
        ("Hello, what are your loan rates?", classifier.QUESTION),
        ("Hi, what is my account balance?", classifier.ACCOUNT_SPECIFIC),
        ("Selam, what makes Awash Bank different?", classifier.COMPARISON),
        ("Hi, this service is terrible", classifier.COMPLAINT),
        # "I am" alone must stay a question — only explicit name
        # introductions count as part of the greeting.
        ("Hello I am looking for a loan", classifier.QUESTION),
        ("Hi, I need a mortgage", classifier.QUESTION),
    ],
)
def test_greeting_prefix_does_not_swallow_the_real_request(
    text: str, expected: str
) -> None:
    assert classifier.classify_intent(text, ALIASES) == expected, text


def test_strip_greeting_returns_the_question_only() -> None:
    remainder, had = classifier.strip_greeting("Selam, how do I open an account?")
    assert had is True
    assert remainder == "how do I open an account?"

    remainder, had = classifier.strip_greeting("How do I open an account?")
    assert had is False
    assert remainder == "How do I open an account?"


def test_language_detection_was_never_the_problem() -> None:
    # Pinned so a future change doesn't "fix" the wrong layer: detection
    # was already correct on both failing messages.
    assert classifier.detect_language("Hi akkam?") == "om"
    assert classifier.detect_language("ሰላም ኦሊ እባላለሁ") == "am"


def test_greeted_question_is_answered_not_handed_off(
    client: TestClient, cbe_bank: Any
) -> None:
    # Greeting words are ordinary content words to BM25, so leaving them in
    # raised the informativeness bar and made a greeted question harder to
    # answer than a blunt one. It must retrieve just as well either way.
    greeted = client.post(
        "/chat/cbe", json={"message": "Selam, how do I open a diaspora account?"}
    ).json()
    blunt = client.post(
        "/chat/cbe", json={"message": "How do I open a diaspora account?"}
    ).json()
    assert blunt["sources"], "baseline phrasing should retrieve"
    assert greeted["sources"], "a greeting must not cost the answer"
    assert greeted["handoff_created"] is False


def test_greeting_replies_in_the_detected_language(
    client: TestClient, awash_bank: Any
) -> None:
    data = client.post("/chat/awash", json={"message": "Hi akkam?"}).json()
    assert data["intent"] == "greeting"
    assert data["language"] == "om"
    assert data["handoff_created"] is False

    data = client.post("/chat/awash", json={"message": "ሰላም ኦሊ እባላለሁ"}).json()
    assert data["intent"] == "greeting"
    assert data["language"] == "am"
    assert data["handoff_created"] is False
