"""Language must follow the message, not the conversation's history.

Found on the live Awash demo: after greeting in Amharic, the English
question "Tell me more about Awash" came back with an Amharic intro wrapped
around English content. detect_language() returned None for it — the
English word list was 16 words and that phrase contained none of them — so
the sticky conversation language won.

The fix is detection by elimination: among the five supported languages only
English, Afaan Oromo and Somali use Latin script, so unmarked Latin prose is
English. That only holds while Oromo and Somali are positively identified
first, which is what most of these guard.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.classifier import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The message from the demo, plus ordinary English carrying none of
        # the originally-listed keywords.
        ("Tell me more about Awash", "en"),
        ("Show me the nearest branch", "en"),
        ("What are your loan rates?", "en"),
        # Latin-script languages must still be caught positively, or
        # elimination would silently label them English — a worse bug than
        # the one being fixed.
        ("Hi akkam?", "om"),
        ("waa'ee ATM beekuu barbaada", "om"),
        ("maqaan koo Oli", "om"),
        ("sidee lacag u dirtaa", "so"),
        ("waxaan doonayaa xisaab", "so"),
        ("magacaygu waa Oli", "so"),
        # Ethiopic script is unambiguous.
        ("ሰላም ኦሊ እባላለሁ", "am"),
    ],
)
def test_detection(text: str, expected: str) -> None:
    assert detect_language(text) == expected, text


@pytest.mark.parametrize("text", ["ATM", "ok", "hi", "123", ""])
def test_too_little_signal_keeps_the_conversation_language(text: str) -> None:
    # A bare token mid-conversation carries no real signal. Flipping the
    # language on it would be worse than leaving it alone.
    assert detect_language(text) is None, text


def test_switching_to_english_mid_conversation(
    client: TestClient, awash_bank: Any
) -> None:
    first = client.post("/chat/awash", json={"message": "ሰላም ኦሊ እባላለሁ"}).json()
    assert first["language"] == "am"

    second = client.post(
        "/chat/awash",
        json={
            "message": "Tell me more about Awash",
            "conversation_id": first["conversation_id"],
        },
    ).json()
    assert second["language"] == "en", "an English question must get an English reply"


def test_switching_back_to_amharic_still_works(
    client: TestClient, awash_bank: Any
) -> None:
    first = client.post("/chat/awash", json={"message": "Tell me more about Awash"}).json()
    assert first["language"] == "en"

    second = client.post(
        "/chat/awash",
        json={
            "message": "ስለ ATM ማወቅ ፈልጌ ነበር",
            "conversation_id": first["conversation_id"],
        },
    ).json()
    assert second["language"] == "am"


def test_a_bare_token_does_not_flip_an_amharic_conversation(
    client: TestClient, awash_bank: Any
) -> None:
    first = client.post("/chat/awash", json={"message": "ሰላም"}).json()
    assert first["language"] == "am"

    second = client.post(
        "/chat/awash",
        json={"message": "ATM", "conversation_id": first["conversation_id"]},
    ).json()
    assert second["language"] == "am", "one ambiguous word must not switch language"
