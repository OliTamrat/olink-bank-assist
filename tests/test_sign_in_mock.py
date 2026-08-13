"""The sign-in card plays one question in all six languages.

The card is the product's own argument for itself, made in pictures, and its
failure mode is not a crash — it is a screen that keeps running and says
something false. Every check here is a way it has already gone wrong or
plausibly could:

- painting only from the two places that happened to call it, so a fresh
  browser showed an Amharic question answered in English;
- reading half the card from the UI language and half from the customer's,
  so a Tigrinya exchange sat under an Amharic header;
- a hard-coded list of languages that a seventh language would not reach;
- a timer with nothing to stop it, typing into a hidden card for an
  eight-hour session;
- an animation with no reduced-motion path.

These are read out of the source rather than driven in a browser, because CI
has no browser. `node --check` in `test_static_pages.py` already proves the
file parses; this proves the wiring is present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ADMIN = (
    Path(__file__).resolve().parent.parent / "bankassist" / "static" / "admin.html"
).read_text(encoding="utf-8")

LANGS = ("en", "am", "om", "ti", "so", "sw")


def _fn(name: str) -> str:
    """The body of a top-level `function name(...) {...}`, brace-matched."""
    start = ADMIN.index(f"function {name}(")
    depth, i = 0, ADMIN.index("{", start)
    for j in range(i, len(ADMIN)):
        if ADMIN[j] == "{":
            depth += 1
        elif ADMIN[j] == "}":
            depth -= 1
            if depth == 0:
                return ADMIN[start : j + 1]
    raise AssertionError(f"unterminated function {name}")


def test_the_script_is_built_from_langs() -> None:
    """A seventh language must not be able to ship and be missing here.

    The pill row had six names written out in the markup; it is generated now
    for the same reason.
    """
    body = _fn("mockScript")
    assert "LANGS.map" in body, "the mock no longer iterates LANGS"
    for lang in LANGS:
        assert f'"{lang}"' not in body, f"{lang} is hard-coded into mockScript"
    assert "LANGS.map" in _fn("paintLangRow")


def test_it_starts_on_the_panels_own_language() -> None:
    """The first exchange anyone sees should be one they can read; the other
    five are what make the point."""
    assert "LANGS.indexOf(adminLang)" in _fn("mockScript")


def test_the_whole_card_moves_together() -> None:
    """The header, the citation chip and both bubbles are one language.

    This failed once already in the opposite direction: the exchange cycled
    while `mock-name` and `mock-src` stayed in the panel's language, so
    Tigrinya text sat under an Amharic label. Everything on the card reads
    through inLang(), never A().
    """
    card = _fn("paintMockCard")
    for node in ("mock-name", "mock-status", "mock-src", "mock-lang"):
        assert node in card, f"{node} is not painted with the card"
    assert "A(" not in card, "the mock card is reading the panel's language"
    assert "inLang(lang" in card

    play = _fn("mockPlay")
    assert "paintMockCard(item.lang)" in play, "mockPlay does not repaint the card"


def test_the_still_is_a_complete_exchange() -> None:
    """What survives when the animation never starts.

    A narrow window, a browser that throws below, `/admin/strings` never
    answering — the card still has to show one coherent conversation rather
    than half of one.
    """
    still = _fn("paintMockStill")
    assert "paintMockCard(lang)" in still
    for key in ("mock_question", "mock_answer"):
        assert f'"{key}"' in still
    assert "inLang(lang" in still
    assert "A(" not in still


def test_the_markup_default_is_one_language() -> None:
    """The literals that ship in the file, before any script runs.

    The bug the founder reported was exactly this: a hard-coded Amharic
    question next to a hard-coded English answer, on a screen that never
    repainted.
    """
    for node in ("mock-question", "mock-answer", "mock-lang"):
        m = re.search(rf'id="{node}"[^>]*>(.*?)</', ADMIN, re.S)
        assert m, f"{node} is missing from the markup"
        text = m.group(1)
        # No Ge'ez in the defaults: every other literal in this markup is
        # English, and a mismatch here ships to whoever has the worst
        # connection.
        assert not re.search(r"[ሀ-፿]", text), f"{node} default is not English"


def test_the_engine_can_be_stopped_and_is() -> None:
    """A timer on a login page is the one most likely to be left running.

    Four ways in, and the sign-in path is the one that costs a real session:
    a login page left open in a background tab all day, or an animation still
    typing behind the dashboard for the whole eight hours.
    """
    assert "mockStop()" in _fn("enterApp"), "the mock is not stopped on sign-in"
    assert "mockRestart()" in _fn("signedOut"), "the mock is not resumed on sign-out"

    may = _fn("mockMayRun")
    assert "document.hidden" in may, "a hidden tab still animates"
    assert "getClientRects" in may, "the mock runs where the stage does not render"
    assert "adminUI" in may, "the mock can play six identical English exchanges"
    assert 'classList.contains("hidden")' in may

    lifecycle = _fn("wireMockLifecycle")
    assert "visibilitychange" in lifecycle
    assert '"resize"' in lifecycle


def test_a_restart_cannot_leave_two_engines_typing() -> None:
    """The language picker repaints the gate, which restarts the mock.

    Without the identity check every restart would leave the previous chain
    of timers alive, typing a second language into the same two bubbles.
    """
    assert "mockRun !== run" in _fn("mockType")
    assert "mockRun === run" in _fn("mockPlay")
    assert "clearTimeout" in _fn("mockStop")


def test_typing_speed_is_per_message_not_per_character() -> None:
    """Ge'ez packs a syllable into one character, so the Amharic answer is a
    fraction of the English one's length. A fixed ms-per-character makes the
    same sentence race past in one language and crawl in another, which is
    the opposite of what a screen comparing six languages should do."""
    body = _fn("mockType")
    assert "duration / TICK" in body, "typing is no longer duration-normalised"


def test_the_height_is_reserved_after_the_fonts_land() -> None:
    """Two bugs in one line.

    Reserving nothing means the card resizes between languages. Reserving
    before the Ge'ez face arrives measures a fallback and reserves the wrong
    number, so the card grows a line the first time Amharic plays.
    """
    assert "minHeight" in _fn("reserveMockHeight")
    assert "mockFontsReady" in _fn("mockRestart")
    warm = _fn("warmMockFonts")
    assert "Noto Sans Ethiopic Variable" in warm
    assert "Inter Variable" in warm


def test_reduced_motion_keeps_the_languages() -> None:
    """The rotation is the subject; the typing is the decoration.

    Honouring the preference by freezing the card on one language would
    remove the only thing the card is there to say.
    """
    assert "prefers-reduced-motion" in _fn("mockReduced")
    play = _fn("mockPlay")
    assert "run.reduced" in play, "there is no reduced-motion path"
    # …and it still advances rather than stopping on the first language.
    reduced = play[play.index("if (run.reduced)") :]
    assert "hold()" in reduced, "reduced motion stops on one language"


@pytest.mark.parametrize(
    "key", ["mock_question", "mock_answer", "assistant", "online", "n_sources"]
)
def test_every_string_the_card_needs_exists_in_all_six(key: str) -> None:
    """The call-site check, for the card specifically.

    A missing key does not throw — `inLang` falls back to English — so the
    symptom is the exact bug this card was rebuilt to fix: an exchange in one
    language answered in another.
    """
    import json

    tables = json.loads(
        (
            Path(__file__).resolve().parent.parent / "bankassist" / "admin_strings.json"
        ).read_text(encoding="utf-8")
    )
    for lang in LANGS:
        assert key in tables[lang], f"{key} is missing from {lang}"
        assert tables[lang][key].strip(), f"{key} is empty in {lang}"


def test_the_headline_is_composed_not_translated() -> None:
    """"Front door" is a metaphor, and all five translations rendered it as a
    physical door — Amharic መግቢያ በር, Oromo Balbala, Tigrinya መእተዊ ማዕጾ,
    Somali Albaabka hore, Swahili Mlango wa mbele. The founder read the
    Amharic and said it made no sense; he was right about all five.

    The English keeps its metaphor. The other five say the same thing the way
    a native speaker would, which is the rule this repo already follows for
    generated prose (ADR-0026) and had not applied to its own headline.
    """
    import json

    tables = json.loads(
        (
            Path(__file__).resolve().parent.parent / "bankassist" / "admin_strings.json"
        ).read_text(encoding="utf-8")
    )
    doors = {
        "am": "መግቢያ በር",
        "om": "Balbala",
        "ti": "መእተዊ ማዕጾ",
        "so": "Albaabka hore",
        "sw": "Mlango wa mbele",
    }
    for lang, literal in doors.items():
        assert literal not in tables[lang]["stage_line"], (
            f"{lang} stage_line is back to translating 'front door' literally"
        )
