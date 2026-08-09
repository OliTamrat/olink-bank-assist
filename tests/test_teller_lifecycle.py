"""The teller-session state machine and scope model.

Tested exhaustively rather than by example, because this is the file that
decides what a bank employee is allowed to do while a customer is watching,
and because the two boundaries it enforces — no money at any scope, no session
addressed at a customer — are the ones a bank's risk team will ask about
first. "We wrote it down in the spec" is a weaker answer than "here is the
test that fails if anyone changes it."
"""

from __future__ import annotations

import itertools

import pytest

from bankassist import teller

# ------------------------------------------------------------------- states


def test_every_state_appears_in_the_transition_table() -> None:
    """A state with no entry can never be left — including by accident."""
    for state in teller.STATES:
        assert state in teller._TRANSITIONS, f"{state} has no transitions defined"


def test_terminal_states_go_nowhere() -> None:
    for state in teller.TERMINAL:
        assert teller._TRANSITIONS[state] == frozenset(), f"{state} is not terminal"


def test_every_transition_target_is_a_real_state() -> None:
    """Guards a typo that would silently make a move impossible."""
    for source, targets in teller._TRANSITIONS.items():
        for target in targets:
            assert target in teller.STATES, f"{source} -> {target} is not a state"


def test_the_happy_path_walks_end_to_end() -> None:
    state = teller.REQUESTED
    for nxt in (teller.VERIFYING, teller.QUEUED, teller.ACTIVE, teller.ENDED):
        state = teller.move(state, nxt)
    assert state == teller.ENDED


def test_a_queued_session_can_be_abandoned() -> None:
    """The common exit, not an error. Most people who wait too long just
    leave, and that is the number this feature exists to move."""
    assert teller.can_move(teller.QUEUED, teller.ABANDONED)


def test_a_second_teller_cannot_claim_an_active_session() -> None:
    with pytest.raises(teller.InvalidTransition):
        teller.move(teller.ACTIVE, teller.ACTIVE)


def test_a_session_cannot_end_twice() -> None:
    with pytest.raises(teller.InvalidTransition):
        teller.move(teller.ENDED, teller.ENDED)


def test_a_session_cannot_skip_the_queue() -> None:
    """Straight from requested to active would mean a teller joined someone
    who was never identified and never queued."""
    assert not teller.can_move(teller.REQUESTED, teller.ACTIVE)


def test_an_abandoned_session_cannot_be_revived() -> None:
    for target in teller.STATES:
        assert not teller.can_move(teller.ABANDONED, target)


def test_no_transition_leads_backwards_into_waiting() -> None:
    """Once a teller has joined, the session cannot fall back into the queue —
    that would put a customer who is being served behind people who are not.
    """
    for source, targets in teller._TRANSITIONS.items():
        if source in (teller.ACTIVE, *teller.TERMINAL):
            for target in targets:
                assert not teller.is_waiting(target), f"{source} -> {target}"


def test_move_is_the_only_way_to_change_state() -> None:
    """Every ordered pair is either explicitly legal or raises. No third
    outcome, and no silent no-op."""
    for source, target in itertools.product(teller.STATES, repeat=2):
        if teller.can_move(source, target):
            assert teller.move(source, target) == target
        else:
            with pytest.raises(teller.InvalidTransition):
                teller.move(source, target)


# ------------------------------------------------------------------- scopes


def test_money_is_permitted_at_no_scope_whatsoever() -> None:
    """The boundary the whole product is sold on.

    Not "the UI does not offer it" and not "the teller knows better" — there
    is no verification level at which this function returns True.
    """
    for scope in (*teller.SCOPES, "admin", "supervisor", "", "verified "):
        assert teller.allows(scope, teller.MONEY) is False, scope


def test_an_unverified_customer_gets_general_help_only() -> None:
    assert teller.allows(teller.UNVERIFIED, teller.GENERAL_GUIDANCE)
    for capability in (
        teller.OWN_RECORDS, teller.DOCUMENT_CAPTURE, teller.DISPUTE_INTAKE
    ):
        assert not teller.allows(teller.UNVERIFIED, capability), capability


def test_verifying_adds_only_this_customer_s_own_affairs() -> None:
    added = set(teller.capabilities(teller.VERIFIED)) - set(
        teller.capabilities(teller.UNVERIFIED)
    )
    assert added == {
        teller.OWN_RECORDS, teller.DOCUMENT_CAPTURE, teller.DISPUTE_INTAKE
    }


def test_verified_is_a_superset_of_unverified() -> None:
    """Verifying someone must never take a capability away — that would make
    identifying yourself a downgrade."""
    assert set(teller.capabilities(teller.UNVERIFIED)) <= set(
        teller.capabilities(teller.VERIFIED)
    )


def test_an_unknown_scope_grants_nothing() -> None:
    """Fails closed. A scope string edited by hand in the database should
    produce a session that can do nothing — visibly broken — rather than one
    that can do everything, which is not."""
    assert teller.capabilities("nonsense") == ()
    for capability in (teller.GENERAL_GUIDANCE, teller.OWN_RECORDS, teller.MONEY):
        assert not teller.allows("nonsense", capability)


def test_the_module_refuses_to_import_if_money_is_ever_granted() -> None:
    """The assert at the bottom of teller.py is load-bearing, not decorative.

    Reconstructing the check here means that if someone deletes it, this test
    still fails — otherwise removing the guard also removes the thing that
    would have caught its removal.
    """
    assert not any(
        teller.MONEY in grant for grant in teller._GRANTS.values()
    ), "money movement leaked into a scope — see docs/video-teller.md §2"
