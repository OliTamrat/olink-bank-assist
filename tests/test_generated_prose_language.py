"""Prose the model writes in a non-English language must not read as a
translation.

The founder found an Afaan Oromoo grammar and word-choice error on the AI
Insights page (2026-08-12) — in a sentence that exists in **no table
anywhere**. The Insights headline is composed by Gemini per request from the
metrics digest, so no amount of linguist review of `admin_strings.json` could
have caught it or can fix it. The only lever on that text is the prompt.

Both generating prompts now say the same thing: compose in the language
rather than translating an English sentence into it. Everyday spoken
register, short sentences, common words over literary ones, proper nouns left
alone. That is the standard mitigation for calqued model output.

**These assertions are weak on purpose and the weakness is the point.** They
prove the instruction is present, not that the model obeys it — no sandbox
test can prove the second. What they stop is the instruction being deleted by
someone tidying a prompt, which would silently undo a fix made in response to
a defect a native speaker found by reading the live product.
"""

from __future__ import annotations

import pytest

from bankassist import llm

# Every prompt in the product that emits prose a customer or a bank manager
# reads, in a language chosen at runtime. A new one belongs in this list.
GENERATING_PROMPTS = {
    "_SYSTEM_PROMPT": llm._SYSTEM_PROMPT,
    "_INSIGHTS_PROMPT": llm._INSIGHTS_PROMPT,
}


@pytest.mark.parametrize("name", sorted(GENERATING_PROMPTS))
def test_it_is_told_to_compose_not_translate(name: str) -> None:
    lowered = GENERATING_PROMPTS[name].lower()
    assert "compose" in lowered, f"{name} lost the compose-don't-translate rule"
    assert "translat" in lowered, f"{name} no longer names translation as the failure"


@pytest.mark.parametrize("name", sorted(GENERATING_PROMPTS))
def test_it_is_told_which_register_to_write_in(name: str) -> None:
    """"Write in Oromo" is not enough — a model given only that produces
    correct-but-stilted prose. Naming the register is what moves it."""
    lowered = GENERATING_PROMPTS[name].lower()
    assert "register" in lowered
    assert "short sentences" in lowered


@pytest.mark.parametrize("name", sorted(GENERATING_PROMPTS))
def test_proper_nouns_are_left_alone(name: str) -> None:
    """Fayda, Telegram and the bank's own name are transliterated at best and
    mangled at worst when a model decides they are words to translate.
    `test_the_fayda_name_is_never_translated` pins this for the tables; this
    is the same rule for the text no table holds."""
    assert "Fayda" in GENERATING_PROMPTS[name]


def test_both_prompts_still_take_the_language_by_name() -> None:
    """The instruction is worthless if the language is not interpolated.

    `LANGUAGE_NAMES` resolves the code to a name the model recognises —
    "Afaan Oromoo", not "om". A prompt that lost the placeholder would ask
    the model to compose in a language it was never told.
    """
    for prompt in GENERATING_PROMPTS.values():
        assert "{language_name}" in prompt
