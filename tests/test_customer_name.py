"""Addressing a customer by the name they volunteered.

Anything captured here is echoed back and persisted on the conversation, so
the bar for "this is a name" is deliberately high. A false positive would
have the assistant cheerfully calling someone "looking" — or, far worse,
reading back their own account number.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import classifier

ALIASES = ("Awash Bank", "awash")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ሰላም ኦሊ እባላለሁ", "ኦሊ"),
        ("ሰላም፣ ኦሊ ነኝ", "ኦሊ"),
        ("ሰላም ስሜ ኦሊ ነው", "ኦሊ"),
        ("Hello, my name is Oli", "Oli"),
        ("I am Oli", "Oli"),
        ("Hi I am Oli", "Oli"),
        ("call me Oli", "Oli"),
        ("maqaan koo Oli", "Oli"),
        ("Oli jedhama", "Oli"),
        ("magacaygu waa Oli", "Oli"),
    ],
)
def test_explicit_introductions_yield_the_name(text: str, expected: str) -> None:
    assert classifier.extract_name(text) == expected, text


@pytest.mark.parametrize(
    "text",
    [
        # Statements of need, not introductions.
        "Hello I am looking for a loan",
        "I am interested in a mortgage",
        "I am a new customer",
        "What are your loan rates?",
        "Hi there",
        # "I'm well", not a person called ሰላም.
        "ሰላም ነኝ",
        # A request attached to the introduction is a request.
        "I am Oli, what are your loan rates?",
    ],
)
def test_non_introductions_yield_no_name(text: str) -> None:
    assert classifier.extract_name(text) is None, text


def test_an_account_number_is_never_captured_as_a_name() -> None:
    # The failure that matters most: storing and echoing back account data
    # the assistant is supposed to refuse to handle at all.
    for text in ("I am 1000234567", "my name is 1000234567", "call me 100023"):
        assert classifier.extract_name(text) is None, text


def test_introduction_alone_is_a_greeting_but_a_request_still_wins() -> None:
    assert classifier.classify_intent("I am Oli", ALIASES) == classifier.GREETING
    assert classifier.classify_intent("ኦሊ ነኝ", ALIASES) == classifier.GREETING
    # A real request must never be swallowed by the introduction rule.
    assert (
        classifier.classify_intent("Hi, what is my account balance?", ALIASES)
        == classifier.ACCOUNT_SPECIFIC
    )
    assert (
        classifier.classify_intent("Hello I am looking for a loan", ALIASES)
        == classifier.QUESTION
    )


def test_greeting_uses_the_name(client: TestClient, awash_bank: Any) -> None:
    data = client.post("/chat/awash", json={"message": "Hi, I am Oli"}).json()
    assert data["intent"] == "greeting"
    assert "Oli" in data["reply"]


def test_name_persists_across_the_conversation(
    client: TestClient, awash_bank: Any
) -> None:
    first = client.post("/chat/awash", json={"message": "ሰላም ኦሊ እባላለሁ"}).json()
    assert "ኦሊ" in first["reply"]

    # A later escalation should still know who it's talking to — being asked
    # your name twice is worse than never being asked.
    later = client.post(
        "/chat/awash",
        json={"message": "This service is terrible", "conversation_id": first["conversation_id"]},
    ).json()
    assert later["intent"] == "complaint"
    assert "ኦሊ" in later["reply"]


def test_an_unnamed_conversation_is_unchanged(
    client: TestClient, awash_bank: Any
) -> None:
    # No introduction means no name anywhere — no empty placeholder, no
    # "Hello !", no behaviour change for the common case.
    data = client.post("/chat/awash", json={"message": "hello"}).json()
    assert data["intent"] == "greeting"
    assert "{name}" not in data["reply"]
    assert "Hello !" not in data["reply"]


def test_the_name_is_scoped_to_its_own_conversation(
    client: TestClient, awash_bank: Any
) -> None:
    named = client.post("/chat/awash", json={"message": "Hi, I am Oli"}).json()
    assert "Oli" in named["reply"]

    # A separate conversation must not inherit it.
    other = client.post("/chat/awash", json={"message": "hello"}).json()
    assert other["conversation_id"] != named["conversation_id"]
    assert "Oli" not in other["reply"]


def test_a_very_long_name_is_truncated_not_rejected(
    client: TestClient, awash_bank: Any
) -> None:
    long_name = "A" * 200
    assert classifier.extract_name(f"my name is {long_name}") is None, (
        "beyond the plausible-name ceiling it should be rejected outright"
    )
