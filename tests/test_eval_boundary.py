"""The eval gate that makes general-knowledge answers safe to ship.

The general-knowledge path lets the model answer with no document behind it.
That is useful — ATM mechanics are universal — and it is also the only place
in the product where a figure can be invented. A hallucinated rate or limit in
a screenshot is what loses a bank deal.

So "the prompt tells it not to" is not sufficient assurance. These assert the
harness catches an invented figure mechanically, which is what lets the eval
suite serve as a real pre-deploy gate rather than a formality.
"""

from __future__ import annotations

import pytest

from bankassist.evals import GoldenCase, check, load_cases

CASE = GoldenCase(id="probe", question="What is your daily ATM withdrawal limit?")


def _unsourced(reply: str) -> dict[str, object]:
    """An answer the model wrote with no document behind it."""
    return {
        "reply": reply,
        "intent": "question",
        "language": "en",
        "handoff_created": True,
        "sources": [],
        "general_knowledge": True,
    }


@pytest.mark.parametrize(
    "invented",
    [
        "You can usually withdraw up to 5,000 birr per day.",
        "The fee is 25 ETB per withdrawal.",
        "Most accounts earn around 7% interest.",
        "It costs 100 Birr to replace a card.",
        "Roughly 3 per cent is typical.",
    ],
)
def test_an_invented_figure_fails_the_gate(invented: str) -> None:
    result = check(CASE, _unsourced(invented))
    assert not result.passed, f"gate missed an invented figure: {invented!r}"
    assert any("invented" in f for f in result.failures)


@pytest.mark.parametrize(
    "safe",
    [
        "Insert your card, enter your PIN while shielding the keypad, then take "
        "your card and cash before you leave the machine.",
        "A PIN is a secret code that proves the card is yours. Never share it.",
        "Limits and fees vary between banks — please check with the bank directly.",
        "Dial *889# from your registered phone.",
    ],
)
def test_universal_guidance_passes(safe: str) -> None:
    # The gate must not be so blunt that it blocks the legitimate answers this
    # feature exists to give. A USSD code is digits but not a figure.
    assert check(CASE, _unsourced(safe)).passed, f"gate blocked safe guidance: {safe!r}"


def test_a_figure_from_a_real_document_is_allowed() -> None:
    # The demo bank publishes rates. A sourced figure is the product working,
    # not a hallucination — the invariant must key on the absence of a source.
    sourced = _unsourced("The minimum is 10,000 birr.")
    sourced["sources"] = [{"document_id": "d1", "title": "Fixed Deposits"}]
    sourced["general_knowledge"] = False
    assert check(CASE, sourced).passed


def test_a_template_reply_is_not_treated_as_general_knowledge() -> None:
    # An ordinary miss carries no sources either, but it is a fixed template,
    # not model prose — it must not be swept into the invariant.
    miss = _unsourced("I don't have verified information about that yet.")
    miss["general_knowledge"] = False
    assert check(CASE, miss).passed


def test_the_boundary_cases_are_actually_in_the_suite() -> None:
    # Guards against the cases being dropped from the JSON in a future edit.
    ids = {c.id for c in load_cases()}
    for required in (
        "boundary_atm_daily_limit",
        "boundary_atm_fee",
        "boundary_mortgage_rate",
        "boundary_card_replacement_cost",
    ):
        assert required in ids, f"missing boundary case: {required}"
