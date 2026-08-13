"""TOTP, checked against RFC 6238's own published test vectors.

The implementation is written out rather than pulled in, and **this file is
why that is defensible.** RFC 6238 Appendix B publishes the exact codes a
correct implementation produces for a known secret at known times. A
hand-written TOTP can therefore be *proved* right against the standard, in
this repo, with no network and no trust in a third party's release process. A
dependency could only be trusted.

That matters more than usual here: this is the second factor on the account
that can read a bank's whole conversation history. "It seemed to work when I
tried it with my phone" is not a test.
"""

from __future__ import annotations

import base64
import time

import pytest

from bankassist import totp

# RFC 6238 Appendix B uses the ASCII string "12345678901234567890" as the
# shared secret for SHA-1. The RFC prints it as hex; base32 is what an
# authenticator app and this module speak.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii").rstrip("=")

# (unix time, expected 8-digit code) straight from the RFC's SHA-1 rows. This
# module emits six digits, so each expectation is the last six of the RFC's
# eight — the truncation is the only difference between the two.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("when", "rfc_code"), RFC_VECTORS)
def test_it_matches_the_rfc_test_vectors(when: int, rfc_code: str) -> None:
    assert totp.code_for_step(RFC_SECRET, totp.step_at(when)) == rfc_code[-6:]


def test_a_secret_is_long_enough_and_needs_no_padding() -> None:
    """RFC 4226 §4 wants 128 bits minimum and recommends 160.

    The no-padding half is not cosmetic: some authenticator apps refuse a
    secret containing "=", and the failure is a user who cannot enrol with no
    explanation of why.
    """
    secret = totp.generate_secret()
    assert len(base64.b32decode(secret + "=" * (-len(secret) % 8))) == 20
    assert "=" not in secret


def test_two_secrets_are_never_the_same() -> None:
    assert len({totp.generate_secret() for _ in range(50)}) == 50


# ------------------------------------------------------------- drift


def test_a_code_from_the_previous_step_still_works() -> None:
    """A person typing six digits routinely crosses a step boundary.

    Rejecting that is how a security feature becomes the reason somebody
    turns it off.
    """
    now = 1_700_000_000.0
    previous = totp.code_for_step(RFC_SECRET, totp.step_at(now) - 1)
    assert totp.verify(RFC_SECRET, previous, now=now, last_used_step=None) is not None


def test_a_code_two_steps_old_is_refused() -> None:
    """The window is bounded. Widening it doubles how long an intercepted
    code stays usable."""
    now = 1_700_000_000.0
    stale = totp.code_for_step(RFC_SECRET, totp.step_at(now) - 2)
    assert totp.verify(RFC_SECRET, stale, now=now, last_used_step=None) is None


# ------------------------------------------------------------- replay


def test_a_code_cannot_be_used_twice() -> None:
    """The property that makes it a ONE-time password.

    Without it, a code read over a shoulder or off a phone's lock screen
    stays valid for the rest of its window and the whole drift allowance
    either side — comfortably long enough to be typed by somebody else.
    """
    now = 1_700_000_000.0
    code = totp.code_for_step(RFC_SECRET, totp.step_at(now))
    step = totp.verify(RFC_SECRET, code, now=now, last_used_step=None)
    assert step is not None
    assert totp.verify(RFC_SECRET, code, now=now, last_used_step=step) is None


def test_replay_protection_also_closes_the_drift_window() -> None:
    """Spending the current code must retire the older ones too.

    Otherwise the previous step's code — still inside the drift allowance —
    remains a second valid credential after the first has been used.
    """
    now = 1_700_000_000.0
    current = totp.step_at(now)
    previous_code = totp.code_for_step(RFC_SECRET, current - 1)
    assert totp.verify(RFC_SECRET, previous_code, now=now, last_used_step=current) is None


# ------------------------------------------------------------- input


@pytest.mark.parametrize("junk", ["", "abcdef", "12345", "1234567", "  ", "12 34 56 78"])
def test_malformed_input_is_refused_without_raising(junk: str) -> None:
    """A login form is reachable by anyone; it must never 500 on a typo."""
    assert totp.verify(RFC_SECRET, junk, now=1_700_000_000.0, last_used_step=None) is None


def test_a_secret_survives_being_retyped_by_a_person() -> None:
    """Apps display secrets in spaced groups and people paste them back that
    way, in whatever case they land in. Refusing that is a support ticket."""
    now = 1_700_000_000.0
    code = totp.code_for_step(RFC_SECRET, totp.step_at(now))
    spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
    assert totp.verify(spaced, code, now=now, last_used_step=None) is not None


# ------------------------------------------------------- provisioning


def test_the_uri_carries_what_an_authenticator_needs() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, account="oli@example.com", issuer="CBE")
    assert uri.startswith("otpauth://totp/")
    for part in (f"secret={RFC_SECRET}", "issuer=CBE", "digits=6", "period=30"):
        assert part in uri


def test_the_label_is_escaped_so_a_bank_name_cannot_break_the_uri() -> None:
    """Bank names contain spaces and ampersands. Unescaped, either one
    silently truncates the parameters an app reads."""
    uri = totp.provisioning_uri(
        RFC_SECRET, account="a b@example.com", issuer="Bank & Trust"
    )
    assert " " not in uri
    assert uri.count("?") == 1


# ---------------------------------------------------------- recovery


def test_recovery_codes_are_distinct_and_readable() -> None:
    codes = totp.generate_recovery_codes()
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    assert len(set(codes)) == len(codes)
    # Nothing a person can transpose under pressure: no 0/O, no 1/l.
    for code in codes:
        assert not (set(code) & set("01ilo"))


def test_a_recovery_code_matches_however_it_is_retyped() -> None:
    """It is read off paper by somebody who has just lost their phone. The
    hyphen and the case must not be why it fails."""
    code = totp.generate_recovery_codes(1)[0]
    for variant in (code, code.upper(), code.replace("-", ""), f"  {code} "):
        assert totp.hash_recovery_code(variant) == totp.hash_recovery_code(code)


def test_two_different_codes_do_not_collide() -> None:
    codes = totp.generate_recovery_codes()
    assert len({totp.hash_recovery_code(c) for c in codes}) == len(codes)


# ---------------------------------------------------------------- diagnosis
# "That code was not accepted" is true of two unrelated problems, and working
# out which one cost a round-trip of screenshots against a live deployment.


def test_a_drifted_clock_is_named_as_a_drifted_clock() -> None:
    secret = totp.generate_secret()
    centre = totp.step_at(time.time())
    for offset, wording in ((10, "ahead of"), (-10, "behind")):
        code = totp.code_for_step(secret, centre + offset)
        said = totp.explain_rejection(secret, code)
        assert "clock" in said, said
        assert wording in said, said
        assert "5 minute" in said, said


def test_a_code_from_another_secret_is_named_as_one() -> None:
    """The case that actually happened.

    Enrolment used to mint a new secret every time the panel opened, so an
    authenticator entry scanned a minute earlier was already orphaned. The
    code it produced is correct — for a secret the server threw away.
    """
    mine, theirs = totp.generate_secret(), totp.generate_secret()
    code = totp.code_for_step(theirs, totp.step_at(time.time()))
    said = totp.explain_rejection(mine, code)
    assert "different secret" in said, said
    assert "clock" not in said, said


def test_the_diagnostic_never_accepts_anything() -> None:
    """It explains; it must never widen the window that verify() enforces.

    A rejected code has to stay rejected — the diagnostic runs AFTER verify
    has already said no, and searching ±20 minutes must not become a way to
    spend a 20-minute-old code.
    """
    secret = totp.generate_secret()
    centre = totp.step_at(time.time())
    drifted = totp.code_for_step(secret, centre + 10)
    assert totp.explain_rejection(secret, drifted)  # it can explain it…
    # …and verify still refuses it.
    assert totp.verify(secret, drifted, now=time.time(), last_used_step=None) is None
    assert totp.DIAGNOSTIC_STEPS > totp.DRIFT_STEPS, (
        "the diagnostic window must be wider than the accepted one, or it "
        "explains nothing verify did not already allow"
    )
