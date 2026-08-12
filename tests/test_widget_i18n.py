"""The interface itself, in all five languages — not only the replies.

The product was multilingual in what the assistant SAID and English in every
button around it. Somebody could hold an entire conversation in Amharic,
reach the moment they needed a human, and meet "Speak to a teller / Audio /
Video / Join the queue" in English — at exactly the point they are least able
to absorb a second language, and often because something has gone wrong with
their money.

The founder rule this enforces: whatever ships in English ships in all five.
A string that exists only in `en` makes a change incomplete the same way a
failing test does, so these are the tests that make the rule mechanical
rather than a thing people remember on a good day.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bankassist.i18n import SUPPORTED_LANGUAGES, all_ui_strings, ui_strings

WIDGET = Path("bankassist/static/widget.html")
UI_JSON = Path("bankassist/ui_strings.json")


def test_every_interface_string_exists_in_every_language() -> None:
    """The rule, as a test. A key present only in English is the defect."""
    table = json.loads(UI_JSON.read_text(encoding="utf-8"))
    assert set(table) == set(SUPPORTED_LANGUAGES)
    english = set(table["en"])
    assert english, "no interface strings at all"
    for lang in SUPPORTED_LANGUAGES:
        assert set(table[lang]) == english, f"{lang} does not match the English keys"


def test_a_bank_name_placeholder_survives_translation() -> None:
    """`{bank}` is substituted at render time. A translation that drops it
    silently produces "Speak to a teller" with no bank in it, and one that
    translates the token produces a literal `{ባንክ}` on screen."""
    table = json.loads(UI_JSON.read_text(encoding="utf-8"))
    for key, english in table["en"].items():
        if "{bank}" not in english:
            continue
        for lang in SUPPORTED_LANGUAGES:
            assert "{bank}" in table[lang][key], f"{lang}/{key} lost its placeholder"


def test_no_language_is_secretly_english() -> None:
    """A table copied from English and never translated passes every
    structural check while shipping nothing. The teller strings are the ones
    that matter, so they are the ones pinned."""
    table = json.loads(UI_JSON.read_text(encoding="utf-8"))
    for lang in ("am", "om", "ti", "so", "sw"):
        for key in ("connect", "end_call", "join_queue", "waiting_for_teller"):
            assert table[lang][key] != table["en"][key], f"{lang}/{key} is still English"


def test_the_config_carries_every_language(
    client: TestClient, demo_bank: Any
) -> None:
    """Sent once, with the bank config. Switching language must not cost a
    round trip — on the connection this product is used on, that pause is
    where somebody gives up."""
    body = client.get("/banks/demo/public").json()
    assert set(body["ui"]) == set(SUPPORTED_LANGUAGES)
    assert body["ui"]["am"]["end_call"] == ui_strings("am")["end_call"]


def test_an_unknown_language_falls_back_to_english() -> None:
    """A missing key must render English, never the key name and never
    nothing. A button reading "end_call" is debuggable; an empty one is
    simply broken."""
    assert ui_strings("zz")["end_call"] == "End call"
    assert all_ui_strings()["en"]["connect"] == "Connect"


def test_the_widget_has_no_hard_coded_teller_strings() -> None:
    """The regression that matters. Every one of these was English-only in
    the shipped widget, and each is a moment where somebody has asked for a
    human."""
    html = WIDGET.read_text(encoding="utf-8")
    for literal in (
        ">Connect<",
        ">Join the queue<",
        ">Waiting for a teller<",
        ">Leave the queue<",
        ">Audio<",
        ">Video<",
        ">Not now<",
        ">Straight away<",
        "Available now — audio or video",
        "Once they have checked your ID",
        "Not on this call, ever",
    ):
        assert literal not in html, f"still hard-coded in the widget: {literal}"


def test_the_widget_looks_up_rather_than_hard_codes() -> None:
    """A cheap proxy for "somebody wired the table in", so deleting the
    plumbing cannot pass while the strings file stays perfect."""
    html = WIDGET.read_text(encoding="utf-8")
    assert "function T(key" in html
    assert "applyLanguage" in html
    assert len(re.findall(r'T\("', html)) >= 25


def test_changing_the_picker_moves_the_interface() -> None:
    """The picker used to tag the next outgoing message and nothing else, so
    choosing አማርኛ changed the reply while every button around it stayed
    English."""
    html = WIDGET.read_text(encoding="utf-8")
    assert 'langSel.addEventListener("change"' in html
    assert "applyLanguage(langSel.value" in html
