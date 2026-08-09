"""Teller-attested identity verification.

The control that decides whether a stranger on a video call gets treated as
the account holder. Everything here is testing that the bar cannot be cleared
by accident — a teller ticking a box, a caller passing the wrong string, a
truncation helper handing back what it was meant to truncate.
"""

from __future__ import annotations

import dataclasses

import pytest

from bankassist import verification as v

# --------------------------------------------------------------- the bar


def test_an_id_alone_is_not_enough() -> None:
    """A document proves who someone is, not that the account is theirs."""
    with pytest.raises(v.AttestationRejected):
        v.attest(checks={v.ID_DOCUMENT}, teller_user_id="u1")


def test_an_account_question_alone_is_not_enough() -> None:
    """Details about an account leak. The document is what ties the answers to
    a person standing in front of a camera."""
    with pytest.raises(v.AttestationRejected):
        v.attest(checks={v.ACCOUNT_DETAIL}, teller_user_id="u1")


def test_nothing_at_all_is_certainly_not_enough() -> None:
    with pytest.raises(v.AttestationRejected):
        v.attest(checks=set(), teller_user_id="u1")


def test_the_document_plus_an_account_question_clears_it() -> None:
    att = v.attest(
        checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL}, teller_user_id="u1"
    )
    assert att.method == v.TELLER_ATTESTED
    assert att.teller_user_id == "u1"


def test_an_audio_only_session_can_still_verify() -> None:
    """Outside Addis, audio-only is the common case rather than the exception.

    If the photo match were required, identity verification would silently
    stop working for exactly the customers with the worst connections — while
    appearing to work fine everywhere it was tested.
    """
    assert v.ID_PHOTO_MATCHES not in v.REQUIRED_CHECKS
    att = v.attest(checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL}, teller_user_id="u1")
    assert v.ID_PHOTO_MATCHES not in att.checks


def test_a_photo_match_is_recorded_when_it_happens() -> None:
    """Not required, but it strengthens the record and must not be discarded."""
    att = v.attest(
        checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL, v.ID_PHOTO_MATCHES},
        teller_user_id="u1",
    )
    assert v.ID_PHOTO_MATCHES in att.checks
    assert len(att.describes()) == 3


def test_an_invented_check_is_refused() -> None:
    """Otherwise a typo in a client silently satisfies nothing while looking
    like it satisfied something."""
    with pytest.raises(v.AttestationRejected):
        v.attest(
            checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL, "vibes"}, teller_user_id="u1"
        )


def test_an_attestation_must_name_someone() -> None:
    """The whole point is that a person is answerable for it."""
    with pytest.raises(v.AttestationRejected):
        v.attest(checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL}, teller_user_id="")


# ------------------------------------------------------- the Fayda number


def test_only_the_tail_of_a_fayda_number_is_kept() -> None:
    """Holding the full 12-digit number would tie every row we own to a
    national identity, for a benefit the bank already has in its own records.
    """
    assert v.tail("123456789012") == "9012"


def test_the_same_number_reduces_the_same_way_however_it_was_typed() -> None:
    """A teller typing spaces or dashes must not produce a different reference
    for the same customer — reconciliation would silently fail."""
    assert v.tail("1234 5678 9012") == v.tail("1234-5678-9012") == v.tail("123456789012")


def test_a_number_too_short_to_truncate_returns_nothing() -> None:
    """The failure this guards is the obvious one: a truncation helper that
    hands back the full value when it cannot truncate is worse than none,
    because every call site believes it is safe."""
    assert v.tail("12") is None
    assert v.tail("1234") is None
    assert v.tail("") is None
    assert v.tail(None) is None


def test_the_full_number_never_reaches_the_attestation() -> None:
    full = "987654321098"
    att = v.attest(
        checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL},
        teller_user_id="u1",
        fayda_number=full,
    )
    assert att.reference == "1098"
    assert full not in repr(att)


def test_a_missing_fayda_number_is_allowed() -> None:
    """A customer may verify on account knowledge with the ID held to camera
    but the number unreadable. The attestation still stands; the reference is
    simply absent."""
    att = v.attest(checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL}, teller_user_id="u1")
    assert att.reference is None


# ------------------------------------------------------------- the record


def test_an_attestation_cannot_be_edited_afterwards() -> None:
    """This is evidence about who vouched for a stranger. Later code must not
    be able to quietly revise it."""
    att = v.attest(checks={v.ID_DOCUMENT, v.ACCOUNT_DETAIL}, teller_user_id="u1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        att.teller_user_id = "someone-else"  # type: ignore[misc]


def test_identical_attestations_read_identically() -> None:
    """Fixed order, not set order — otherwise the same facts render differently
    on two screens and a supervisor comparing them sees a difference that is
    not there."""
    a = v.attest(
        checks={v.ACCOUNT_DETAIL, v.ID_DOCUMENT, v.ID_PHOTO_MATCHES},
        teller_user_id="u1",
    )
    b = v.attest(
        checks={v.ID_PHOTO_MATCHES, v.ID_DOCUMENT, v.ACCOUNT_DETAIL},
        teller_user_id="u1",
    )
    assert a.describes() == b.describes()


def test_every_method_and_check_has_a_human_label() -> None:
    """A method or check nobody can name is one nobody can audit."""
    for method in v.METHODS:
        assert v.METHOD_LABELS.get(method)
    for check in v.CHECKS:
        assert v.CHECK_LABELS.get(check)


def test_the_required_checks_are_real_checks() -> None:
    """Guards a rename that would make the bar unreachable — every attestation
    would be refused, which at least fails loudly, or unenforceable."""
    assert set(v.CHECKS) >= v.REQUIRED_CHECKS
