from __future__ import annotations

from bankassist.classifier import (
    ACCOUNT_SPECIFIC,
    COMPLAINT,
    GREETING,
    INVESTMENT_ADVICE,
    QUESTION,
    classify_intent,
    detect_language,
)


def test_detect_amharic() -> None:
    assert detect_language("የቁጠባ ሂሳብ መክፈት እፈልጋለሁ") == "am"


def test_detect_tigrinya_via_orthographic_tell() -> None:
    assert detect_language("ከመይ ገይረ ኣብ ባንኪ ሕሳብ ክኸፍት እኽእል?") == "ti"


def test_detect_oromo() -> None:
    assert detect_language("Akkam? Baankii keessatti herrega banuu barbaada.") == "om"


def test_detect_somali() -> None:
    assert detect_language("Sidee xisaab uga furaa bangiga? Fadlan i caawi.") == "so"


def test_detect_english() -> None:
    assert detect_language("How can I open a savings account?") == "en"


def test_no_signal_returns_none() -> None:
    assert detect_language("ok") is None
    assert detect_language("123") is None


def test_intents() -> None:
    assert classify_intent("Hello") == GREETING
    assert classify_intent("ሰላም") == GREETING
    assert classify_intent("What is my balance?") == ACCOUNT_SPECIFIC
    assert classify_intent("Should I buy shares in the brewery?") == INVESTMENT_ADVICE
    assert classify_intent("I want to complain about a failed transfer") == COMPLAINT
    assert classify_intent("What documents do I need for a loan?") == QUESTION


def test_complaint_wins_over_account_mention() -> None:
    assert classify_intent("Unauthorized transaction on my account, this is fraud!") == COMPLAINT
