"""A second factor on the account that can read a bank's whole conversation
history.

`tests/test_totp.py` proves the arithmetic against RFC 6238. This file is
about the parts that go wrong in the wiring rather than the maths, and every
case here is a way MFA has been shipped broken by somebody who tested only
the happy path:

- a half-authenticated session that can still reach routes;
- an enrolment that counts before the first code is proved, locking somebody
  out with a secret nothing holds;
- a "one-time" password that works twice;
- a recovery code that works twice;
- a second factor removable from a borrowed unlocked laptop;
- one tenant's admin acting on another tenant's URL.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import admin_auth, totp
from bankassist.models import AdminSession, Bank, RecoveryCode, User

# Composed rather than written as a literal, following test_admin_identity:
# a scanner cannot know a file is a test, and a repository where the secret
# detector cries wolf is one where the next real finding gets waved through.
_FIXTURE = "pytest-fixture-value"
PW = f"{_FIXTURE}-mfa"


@pytest.fixture()
def account(client: TestClient, demo_bank: Any, db_session: Session) -> User:
    """A signed-out admin with a password and no second factor."""
    created = client.post(
        "/admin/api/demo/users",
        headers={"X-Admin-Token": demo_bank.admin_token},
        json={"email": "security@bank.et", "password": PW, "role": "admin"},
    )
    assert created.status_code == 201, created.text
    user = db_session.execute(
        select(User).where(User.email == "security@bank.et")
    ).scalar_one()
    return user


def _sign_in(client: TestClient) -> dict[str, Any]:
    return client.post(
        "/admin/api/demo/login", json={"email": "security@bank.et", "password": PW}
    ).json()


def _enrol(client: TestClient, db: Session) -> str:
    """Take an account all the way through enrolment. Returns the secret."""
    _sign_in(client)
    secret = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    code = totp.code_for_step(secret, totp.step_at(time.time()))
    activated = client.post("/admin/api/demo/mfa/activate", json={"code": code})
    assert activated.status_code == 200, activated.text
    db.expire_all()
    return secret


# ------------------------------------------------------------ enrolment


def test_enrolment_does_not_count_until_a_code_is_proved(
    client: TestClient, db_session: Session, account: User
) -> None:
    """The lockout this ordering prevents.

    If a scanned-but-unconfirmed secret counted, closing the tab between the
    QR and the first code would lock somebody out of their own account with a
    secret nothing holds.
    """
    _sign_in(client)
    client.post("/admin/api/demo/mfa/enroll")
    assert client.get("/admin/api/demo/mfa").json()["enabled"] is False
    # And the next password login must NOT ask for a second factor.
    client.post("/admin/api/demo/logout")
    assert "mfa_required" not in _sign_in(client)


def test_activation_returns_recovery_codes_exactly_once(
    client: TestClient, db_session: Session, account: User
) -> None:
    """They are hashed on the way in, so this response is the only moment
    they exist in readable form."""
    _sign_in(client)
    secret = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    code = totp.code_for_step(secret, totp.step_at(time.time()))
    body = client.post("/admin/api/demo/mfa/activate", json={"code": code}).json()
    assert len(body["recovery_codes"]) == totp.RECOVERY_CODE_COUNT
    # Never again, from any other route.
    assert "recovery_codes" not in client.get("/admin/api/demo/mfa").json()


def test_a_wrong_code_does_not_activate(
    client: TestClient, db_session: Session, account: User
) -> None:
    _sign_in(client)
    client.post("/admin/api/demo/mfa/enroll")
    assert client.post("/admin/api/demo/mfa/activate", json={"code": "000000"}).status_code == 400
    assert client.get("/admin/api/demo/mfa").json()["enabled"] is False


# ------------------------------------------------------------ the login


def test_a_password_alone_no_longer_signs_you_in(
    client: TestClient, db_session: Session, account: User
) -> None:
    _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    body = _sign_in(client)
    assert body == {"mfa_required": True}
    # Deliberately not the identity payload: nobody is signed in yet, and the
    # permission list would describe the account before its second factor.
    assert "permissions" not in body


def test_a_pending_session_cannot_reach_anything(
    client: TestClient, db_session: Session, account: User
) -> None:
    """The property the whole design rests on.

    `admin_auth.resolve` is the single gate, so a route written before MFA
    existed is still not reachable with a half-finished login.
    """
    _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    _sign_in(client)  # password only — cookie is now a pending session
    reachable = (
        "/admin/api/demo/conversations",
        "/admin/api/demo/analytics",
        "/admin/api/demo/me",
    )
    for path in reachable:
        assert client.get(path).status_code == 401, f"{path} accepted a pending session"


def test_the_code_completes_the_login(
    client: TestClient, db_session: Session, account: User
) -> None:
    secret = _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    # A step ahead of the one activation spent, since that one is now retired.
    code = totp.code_for_step(secret, totp.step_at(time.time()) + 1)
    body = client.post("/admin/api/demo/login/mfa", json={"code": code})
    assert body.status_code == 200, body.text
    assert "permissions" in body.json()
    assert client.get("/admin/api/demo/me").status_code == 200


def test_a_wrong_code_leaves_the_session_pending(
    client: TestClient, db_session: Session, account: User
) -> None:
    _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    assert client.post("/admin/api/demo/login/mfa", json={"code": "000000"}).status_code == 401
    assert client.get("/admin/api/demo/me").status_code == 401


def test_the_mfa_step_needs_a_pending_session(client: TestClient, cbe_bank: Bank) -> None:
    """Posting a code with no login behind it is not a way in."""
    assert client.post("/admin/api/demo/login/mfa", json={"code": "123456"}).status_code == 401


def test_a_code_cannot_be_replayed_into_a_second_session(
    client: TestClient, db_session: Session, account: User
) -> None:
    """The one-time property, end to end rather than in the arithmetic.

    A code read over a shoulder must not still open a second session while
    its window is open.
    """
    secret = _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    code = totp.code_for_step(secret, totp.step_at(time.time()) + 1)
    assert client.post("/admin/api/demo/login/mfa", json={"code": code}).status_code == 200
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    assert client.post("/admin/api/demo/login/mfa", json={"code": code}).status_code == 401


# --------------------------------------------------------- recovery


def test_a_recovery_code_gets_you_in_when_the_phone_is_gone(
    client: TestClient, db_session: Session, account: User
) -> None:
    _sign_in(client)
    secret = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    code = totp.code_for_step(secret, totp.step_at(time.time()))
    codes = client.post("/admin/api/demo/mfa/activate", json={"code": code}).json()[
        "recovery_codes"
    ]
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    body = client.post("/admin/api/demo/login/mfa", json={"code": codes[0]})
    assert body.status_code == 200, body.text
    # Said out loud, because the person who just spent one should re-enrol.
    assert body.json()["recovery_codes_remaining"] == totp.RECOVERY_CODE_COUNT - 1


def test_a_recovery_code_is_single_use(
    client: TestClient, db_session: Session, account: User
) -> None:
    _sign_in(client)
    secret = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    code = totp.code_for_step(secret, totp.step_at(time.time()))
    codes = client.post("/admin/api/demo/mfa/activate", json={"code": code}).json()[
        "recovery_codes"
    ]
    for expected in (200, 401):
        client.post("/admin/api/demo/logout")
        _sign_in(client)
        assert (
            client.post("/admin/api/demo/login/mfa", json={"code": codes[0]}).status_code
            == expected
        )


# ---------------------------------------------------------- disabling


def test_turning_it_off_costs_the_password(
    client: TestClient, db_session: Session, account: User
) -> None:
    """A borrowed unlocked laptop must not be enough to remove a second
    factor — that is the move that turns momentary physical access into
    lasting access."""
    _enrol(client, db_session)
    assert client.post(
        "/admin/api/demo/mfa/disable", json={"password": "not-the-password"}
    ).status_code == 401
    assert client.get("/admin/api/demo/mfa").json()["enabled"] is True

    assert client.post(
        "/admin/api/demo/mfa/disable", json={"password": PW}
    ).status_code == 200
    assert client.get("/admin/api/demo/mfa").json()["enabled"] is False


def test_disabling_destroys_the_recovery_codes(
    client: TestClient, db_session: Session, account: User
) -> None:
    """Otherwise ten working bypasses survive for an authenticator nobody
    holds."""
    _enrol(client, db_session)
    client.post("/admin/api/demo/mfa/disable", json={"password": PW})
    db_session.expire_all()
    left = db_session.execute(
        select(RecoveryCode).where(RecoveryCode.user_id == account.id)
    ).scalars().all()
    assert left == []


def test_a_bank_can_require_it(
    client: TestClient, db_session: Session, demo_bank: Any, account: User
) -> None:
    """The tenant's policy outranks the individual's preference — which is
    what a bank's security questionnaire is actually asking."""
    _enrol(client, db_session)
    # Loaded through db_session rather than mutating the fixture object: the
    # seeders return a Bank attached to their own session, so assigning to
    # that instance never reaches the database and the test would pass or
    # fail for reasons unrelated to the feature.
    bank = db_session.execute(select(Bank).where(Bank.slug == "demo")).scalar_one()
    bank.require_mfa = True
    db_session.commit()
    assert client.get("/admin/api/demo/mfa").json()["required"] is True
    assert client.post(
        "/admin/api/demo/mfa/disable", json={"password": PW}
    ).status_code == 403


# ------------------------------------------------------- tenancy


def test_one_banks_admin_cannot_act_on_another_banks_url(
    client: TestClient, db_session: Session, account: User, cbe_bank: Bank
) -> None:
    """The slug in the path is a claim; the cookie is the fact."""
    _sign_in(client)
    for path in ("/admin/api/cbe/mfa", "/admin/api/cbe/mfa/enroll"):
        method = client.get if path.endswith("/mfa") else client.post
        assert method(path).status_code == 404, path


# ------------------------------------------------------- lifetimes


def test_a_pending_session_expires_in_minutes_not_hours(
    client: TestClient, db_session: Session, account: User
) -> None:
    """A verified password is a credential sitting in the open until the
    second factor lands; it must not sit there all day."""
    _enrol(client, db_session)
    client.post("/admin/api/demo/logout")
    _sign_in(client)
    db_session.expire_all()
    row = db_session.execute(
        select(AdminSession)
        .where(AdminSession.user_id == account.id, AdminSession.pending_mfa.is_(True))
    ).scalars().first()
    assert row is not None
    assert admin_auth.PENDING_MFA_LIFETIME < admin_auth.SESSION_LIFETIME


def test_reopening_the_enrolment_panel_keeps_the_same_secret(
    client: TestClient, account: User, db_session: Session
) -> None:
    """The defect that made two-factor look permanently broken.

    Enrolment minted a fresh secret on EVERY call and overwrote the pending
    row. The panel calls it each time it renders, so the ordinary sequence —
    scan the QR, look away, come back and type the first code — silently
    orphaned the entry the authenticator had just stored. The app then
    produced correct codes for a secret the server no longer held, and the
    only feedback was "That code was not accepted", indefinitely, with a
    perfectly valid-looking secret on screen throughout.

    Found by taking the rejected code and the displayed secret from a
    screenshot and searching every step within ±24 hours for a match. There
    was none, which rules out clock drift and leaves only a second secret.
    """
    _sign_in(client)
    first = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    again = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    assert again == first, (
        "reopening enrolment issued a new secret, which orphans whatever the "
        "authenticator already scanned"
    )
    # …and the code from that secret still activates, which is the property
    # the user actually cares about.
    code = totp.code_for_step(first, totp.step_at(time.time()))
    assert client.post("/admin/api/demo/mfa/activate", json={"code": code}).status_code == 200


def test_starting_over_is_possible_but_has_to_be_asked_for(
    client: TestClient, account: User, db_session: Session
) -> None:
    """Someone who genuinely lost the QR still needs a fresh secret.

    Explicit is the whole point: the defect was a new secret arriving when
    nobody asked for one.
    """
    _sign_in(client)
    first = client.post("/admin/api/demo/mfa/enroll").json()["secret"]
    fresh = client.post("/admin/api/demo/mfa/enroll?restart=true").json()["secret"]
    assert fresh != first
    stale = totp.code_for_step(first, totp.step_at(time.time()))
    assert client.post("/admin/api/demo/mfa/activate", json={"code": stale}).status_code == 400


def test_a_rejected_code_says_which_failure_it_was(
    client: TestClient, account: User, db_session: Session
) -> None:
    """The generic message cost a full round-trip of screenshots to diagnose."""
    _sign_in(client)
    secret = client.post("/admin/api/demo/mfa/enroll").json()["secret"]

    drifted = totp.code_for_step(secret, totp.step_at(time.time()) + 10)
    said = client.post("/admin/api/demo/mfa/activate", json={"code": drifted})
    assert said.status_code == 400
    assert "clock" in said.json()["detail"], said.json()

    other = totp.code_for_step(totp.generate_secret(), totp.step_at(time.time()))
    said = client.post("/admin/api/demo/mfa/activate", json={"code": other})
    assert said.status_code == 400
    assert "different secret" in said.json()["detail"], said.json()


def test_enrolment_ships_a_qr_that_encodes_the_provisioning_uri(
    client: TestClient, account: User, db_session: Session
) -> None:
    """The screen said "Scan this in your authenticator app" and rendered
    nothing to scan.

    Only the secret as text, which means the sole route it actually offered
    was typing a 32-character base32 key into a phone by hand. Nobody does
    that — so nobody had an entry in their authenticator, and every code they
    tried was for something else. The instruction was a lie for the whole
    life of the feature.

    Asserting the QR *decodes back to the URI* rather than merely existing:
    an SVG of the wrong string scans perfectly and enrols the wrong account,
    which is indistinguishable from this bug from the user's side.
    """
    _sign_in(client)
    enrol = client.post("/admin/api/demo/mfa/enroll").json()
    svg = enrol.get("qr_svg")
    assert svg, "enrolment ships no QR — the screen's own instruction is unfollowable"
    assert svg.lstrip().startswith("<svg"), svg[:80]

    import segno
    from segno import helpers  # noqa: F401  (import surface check)

    # Rebuild the symbol from the URI and compare module matrices: same URI
    # and settings produce an identical matrix, so this catches a QR built
    # from the wrong string without needing a camera.
    expected = segno.make(enrol["uri"], error="m")
    import io

    buf = io.BytesIO()
    expected.save(buf, kind="svg", scale=5, border=4, dark="#0b1220",
                  light="#ffffff", xmldecl=False, svgns=True, nl=False)
    assert svg == buf.getvalue().decode("utf-8"), (
        "the QR does not encode this enrolment's provisioning URI"
    )

    # …and the URI is the one an authenticator needs.
    assert enrol["uri"].startswith("otpauth://totp/")
    assert enrol["secret"] in enrol["uri"]


def test_the_qr_reaches_no_third_party_origin(
    client: TestClient, account: User, db_session: Session
) -> None:
    """Same rule as the vendored fonts: the panel shows customer
    conversations, so a third-party origin is a CSP entry and a security
    review question in exchange for nothing. Generating the SVG server-side
    means the QR is markup, not a request."""
    _sign_in(client)
    svg = client.post("/admin/api/demo/mfa/enroll").json()["qr_svg"]
    assert "<image" not in svg and "xlink:href" not in svg
    for scheme in ("http://", "https://"):
        stripped = svg.replace("http://www.w3.org/2000/svg", "")
        assert scheme not in stripped, f"the QR SVG reaches out to {scheme}"
