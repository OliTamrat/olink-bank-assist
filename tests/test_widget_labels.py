"""The chips a bank reads over the assistant's shoulder must be true.

Every reply in the widget carries a label saying what the assistant just did.
Those labels were keyed off *intent*, which describes what was asked — so any
turn that wasn't answering a question inherited "Product guidance" from the
placeholder intent. Storing a customer's phone number was shown as "Product
guidance"; so was failing to find an answer at all.

In a product whose entire pitch is "it tells you when it doesn't know", a chip
claiming the bank's own information was given when it wasn't is the worst one
to get wrong.

The mapping now keys off outcome, which is why this file exists: the widget is
static HTML with no test runner of its own, and a renamed outcome would send
the label silently back to the intent fallback with nothing failing.
"""

from __future__ import annotations

import re
from pathlib import Path

from bankassist import agent

WIDGET = Path(agent.__file__).parent / "static" / "widget.html"


def _outcome_keys() -> set[str]:
    """The keys of the OUTCOMES object in widget.html."""
    block = re.search(r"var OUTCOMES = \{(.*?)\n  \};", WIDGET.read_text(), re.S)
    assert block, "OUTCOMES table not found — did the widget's meta chips change?"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def test_every_outcome_label_names_a_real_outcome() -> None:
    """A typo or a rename here fails open, into the label this file exists to
    stop being shown."""
    known = {
        agent.ANSWERED, agent.GENERAL_GUIDANCE, agent.UNANSWERED, agent.COMPLAINT,
        agent.ACCOUNT_BLOCKED, agent.COMPARISON, agent.GREETING,
        agent.CONTACT_CAPTURED, agent.HUMAN_REQUEST,
    }
    unknown = _outcome_keys() - known
    assert not unknown, f"widget labels an outcome the agent never emits: {unknown}"


def test_the_turns_that_give_no_product_guidance_are_all_relabelled() -> None:
    """These three are the ones that were actively lying.

    contact_captured stored a number, unanswered found nothing, and
    general_guidance is explicitly NOT this bank's published content — the
    exact opposite of what "Product guidance" claims.
    """
    keys = _outcome_keys()
    for outcome in (agent.CONTACT_CAPTURED, agent.UNANSWERED, agent.GENERAL_GUIDANCE):
        assert outcome in keys, outcome
