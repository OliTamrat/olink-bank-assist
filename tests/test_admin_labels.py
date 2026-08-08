"""The admin dashboard's outcome vocabulary must match the agent's.

Three constants describe the same set of things in two languages: agent.py's
outcome names, admin.html's OUTCOME_LABEL (how each is written for a bank),
and admin.html's SUBSTANTIVE (which ones count as questions). Nothing made
them agree, and two had already drifted by the time this file was written —
human_request was rendering to a bank as the raw key "human_request", and was
in the server's rate denominator while being drawn under "not counted as
questions", so the bars silently stopped summing to their own total.

The dashboard is static HTML with no test runner of its own, and both failures
are silent: a wrong label still renders, and a wrong denominator still adds
up to a plausible-looking percentage. Those are the two ways a number in front
of a bank goes wrong without anyone noticing.
"""

from __future__ import annotations

import re
from pathlib import Path

from bankassist import agent

ADMIN = Path(agent.__file__).parent / "static" / "admin.html"


def _label_keys() -> set[str]:
    block = re.search(r"var OUTCOME_LABEL = \{(.*?)\n\};", ADMIN.read_text(), re.S)
    assert block, "OUTCOME_LABEL not found — did the dashboard's labels move?"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def _substantive() -> set[str]:
    block = re.search(
        r"var SUBSTANTIVE = \[(.*?)\];", ADMIN.read_text(), re.S
    )
    assert block, "SUBSTANTIVE not found in admin.html"
    return set(re.findall(r'"(\w+)"', block.group(1)))


def test_every_outcome_the_agent_emits_has_a_label() -> None:
    """An outcome with no label renders to a bank as its internal key."""
    emitted = {
        agent.ANSWERED, agent.GENERAL_GUIDANCE, agent.UNANSWERED, agent.COMPLAINT,
        agent.ACCOUNT_BLOCKED, agent.COMPARISON, agent.GREETING,
        agent.CONTACT_CAPTURED, agent.HUMAN_REQUEST,
    }
    missing = emitted - _label_keys()
    assert not missing, f"no dashboard label for: {sorted(missing)}"


def test_no_label_exists_for_an_outcome_that_never_happens() -> None:
    """A stale label is a promise of a row that will never appear."""
    emitted = {
        agent.ANSWERED, agent.GENERAL_GUIDANCE, agent.UNANSWERED, agent.COMPLAINT,
        agent.ACCOUNT_BLOCKED, agent.COMPARISON, agent.GREETING,
        agent.CONTACT_CAPTURED, agent.HUMAN_REQUEST,
    }
    stale = _label_keys() - emitted
    assert not stale, f"dashboard labels an outcome the agent never emits: {sorted(stale)}"


def test_the_dashboard_and_the_server_agree_on_what_counts_as_a_question() -> None:
    """The server computes every rate over agent.SUBSTANTIVE. If the dashboard
    charts a different set, the bars are drawn against a denominator that does
    not contain them — and the percentages beside them are wrong rather than
    merely incomplete."""
    assert _substantive() == set(agent.SUBSTANTIVE), (
        "admin.html SUBSTANTIVE has drifted from agent.SUBSTANTIVE"
    )


def _reason_keys() -> set[str]:
    block = re.search(r"var REASON_LABEL = \{(.*?)\n\};", ADMIN.read_text(), re.S)
    assert block, "REASON_LABEL not found — did the escalation queue's labels move?"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def test_every_handoff_reason_has_a_label() -> None:
    """The queue rendered `reason` raw until someone looked at it.

    A card headed "human_request" is the same failure the outcome labels are
    checked for, in a field nothing was checking — and it was invisible in the
    diff, because the raw string is a perfectly valid thing to render.
    """
    missing = set(agent.HANDOFF_REASONS) - _reason_keys()
    assert not missing, f"no label for handoff reason: {sorted(missing)}"


def test_no_label_exists_for_a_handoff_reason_never_filed() -> None:
    stale = _reason_keys() - set(agent.HANDOFF_REASONS)
    assert not stale, f"labels a reason the agent never files: {sorted(stale)}"


def test_there_is_only_one_copy_of_the_question_set() -> None:
    """The chart and the CSV export must read the same constant.

    This replaces a test that compared two copies — `SUBSTANTIVE` for the chart
    and `SUBSTANTIVE_OUT` for the export — which was the right test while two
    copies existed. The dashboard rewrite collapsed them into one, so the drift
    is now impossible by construction rather than merely detected, and what is
    worth pinning is that nobody reintroduces the second copy.
    """
    text = ADMIN.read_text()
    definitions = re.findall(r"var (SUBSTANTIVE\w*) *= *\[", text)
    assert definitions == ["SUBSTANTIVE"], (
        f"expected exactly one question-set constant, found {definitions}"
    )
    # And it is genuinely used by both readers, not defined and ignored.
    assert text.count("SUBSTANTIVE.indexOf") >= 2
