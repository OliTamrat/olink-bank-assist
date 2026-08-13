"""The sign-in gate's two routes in, and the one that went missing.

The admin token is the **break-glass** credential (ADR-0027): it is not tied
to a person, it bypasses MFA on purpose, and it exists for the case where
nobody can sign in normally. It was reachable only from inside the MFA step —
which you get to by signing in with an email and password. So the credential
that exists for when you cannot sign in sat behind the door it opens, and a
bank whose operator held the token and no user account had no way in at all.

Nothing was deleted to cause that; the link simply lived in the wrong panel.
That is exactly the kind of regression a diff review passes and a person
using the product finds, so it is pinned here rather than trusted to care.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "bankassist" / "static"
ADMIN = (STATIC / "admin.html").read_text(encoding="utf-8")

# The markup, with comments stripped — several of them discuss these very ids
# by name, and a regex that matches the prose asserts against nothing.
MARKUP = re.sub(r"<!--.*?-->", "", ADMIN, flags=re.S)


def _panel(panel_id: str) -> str:
    """The markup of one gate panel, up to the start of the next."""
    start = MARKUP.index(f'id="{panel_id}"')
    rest = MARKUP[start:]
    nxt = re.search(r'<div id="(?:pw-mode|mfa-mode|token-mode)"', rest[1:])
    return rest[: nxt.start() + 1] if nxt else rest


def test_the_token_route_is_reachable_from_the_first_screen() -> None:
    """Not from the MFA step alone — that is the defect this file is about."""
    assert 'id="to-token-pw"' in _panel("pw-mode"), (
        "the password step no longer offers the admin-token route, so the "
        "break-glass credential is reachable only by first signing in"
    )


def test_the_token_field_still_exists_and_still_posts() -> None:
    """The link is worthless if the panel behind it went away."""
    assert 'id="token"' in _panel("token-mode")
    assert "signInWithToken" in ADMIN, "the token sign-in handler is gone"


@pytest.mark.parametrize("entry", ["to-token-pw", "to-token", "to-pw"])
def test_every_gate_switch_goes_through_the_one_mode_helper(entry: str) -> None:
    """One panel at a time, named rather than toggled.

    The previous handlers each flipped two specific panels. That was right
    from the password step and wrong from the MFA step: "use an admin token"
    there revealed the token panel without hiding the MFA one, so the card
    showed both at once. A helper that takes the mode you want cannot express
    that state; a pair of toggles can, and did.
    """
    call = re.search(rf'\$\("{entry}"\)\.onclick = function \(\) \{{([^}}]*)', ADMIN)
    assert call, f"{entry} has no click handler"
    assert "gateMode(" in call.group(1), (
        f"{entry} flips panels directly instead of naming a mode — that is how "
        "two panels ended up visible together"
    )


def test_both_gate_switches_are_translated() -> None:
    """The gate is the one screen every reader meets BEFORE they can choose a
    language, so an English-only string here is the most visible kind there
    is. Both of these were hardcoded in the markup."""
    for key in ("use_admin_token", "sign_in_with_email"):
        assert f'A("{key}"' in ADMIN, f"{key} is not read through A()"


def test_the_enrolment_code_field_is_shielded_from_autofill() -> None:
    """This panel renders directly under the change-password form.

    Chromium will drop a saved password into an unnamed text input it decides
    belongs to the same credential group — which is what put a password into
    the "Authentication code" box, so activating two-factor failed with a
    message that read as "two-factor is broken".
    """
    field = re.search(r'<input id=\\?"mfa-first[^>]*', ADMIN)
    assert field, "the enrolment code field is gone"
    markup = field.group(0)
    for attr in ('autocomplete="one-time-code"', 'inputmode="numeric"', 'name="totp"'):
        assert attr in markup, f"the enrolment code field lost {attr}"


def test_the_code_is_normalised_and_checked_before_it_is_sent() -> None:
    """Two separate faults, and the second is the one that misleads.

    Authenticator apps print the code as "123 456", so a pasted code carries a
    space in the MIDDLE — `.trim()` leaves it there and the server correctly
    rejects it. And sending an obviously-invalid value only to render the
    server's generic refusal tells the operator the wrong thing about what
    went wrong.
    """
    enrol = ADMIN[ADMIN.index("function startMfaEnrolment") :]
    enrol = enrol[: enrol.index("function showRecoveryCodes")]
    assert re.search(r"replace\(/\\s\+/g,\s*[\"']{2}\)", enrol), (
        "the enrolment code is no longer stripped of internal whitespace"
    )
    assert re.search(r"\^\\d\{6\}\$", enrol), (
        "the enrolment code is no longer checked for six digits before POSTing"
    )
    assert 'A("mfa_code_digits"' in enrol, "the specific error message is gone"


def test_account_is_not_offered_to_a_session_that_has_no_account() -> None:
    """`perm` and `needsUser` are different questions.

    `perm: null` means "no capability required", which is right — nobody
    grants you your own password. But the break-glass token is not a person,
    so there is no "your" anything to manage, and offering the page anyway is
    what ejected an operator from the whole shell on one click.
    """
    entry = re.search(r'\{ id: "account".*?\}', ADMIN, re.S)
    assert entry, "the Account nav entry is gone"
    assert "needsUser: true" in entry.group(0), (
        "Account no longer declares that it needs a person, so a token "
        "session will be offered a page it cannot open"
    )


def test_every_nav_filter_asks_both_questions() -> None:
    """Three separate places decide what a session may open — the nav, the
    landing-page choice and `go()`. The bug reached the user through one of
    them, so a helper wired into two of the three would leave it in place.

    Counted rather than parametrised: the property is about how many call
    sites exist, and a parametrised version would just run one assertion three
    times over an argument it never used.
    """
    assert re.search(r"^function mayOpen\(", ADMIN, re.M), "the helper is gone"
    call_sites = len(re.findall(r"mayOpen\b", ADMIN)) - 1  # minus the definition
    assert call_sites >= 3, (
        f"mayOpen is used at {call_sites} call sites, not 3 — a nav filter is "
        "still deciding on the permission alone"
    )
    assert not re.search(r"filter\(function \(p\) \{ return can\(p\.perm\); \}\)", ADMIN), (
        "a nav filter still checks the permission without checking needsUser"
    )
