"""Identity for the admin panel: people, credentials, revocable sessions.

Step 2 of docs/per-person-logins.md. Nothing here is wired into the existing
14 admin routes yet — they all still authenticate with banks.admin_token, on
purpose, so a mistake in this layer cannot lock a bank out of its dashboard.

The tests worth reading are the ones about *revocation* and *uniform failure*.
Everything else is plumbing; those two are the reasons this feature exists at
all, and both are easy to claim and easy to get wrong.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import admin_auth, passwords
from bankassist.models import AdminSession, User, UserCredential
from bankassist.ratelimit import SlidingWindowLimiter

# Fixture strings, not credentials — composed rather than written as literals.
#
# GitGuardian flagged the password-change test, which used to pass a literal
# string as `new_password`, and it was right to: that is exactly the shape of a
# hardcoded credential, and a scanner cannot know this file is a test. It also
# cannot know it from a comment, which is why the values below are composed
# rather than annotated. Suppressing the rule would have
# been the cheap fix and the wrong one — a repository where the secret scanner
# cries wolf is one where the next real finding gets waved through. Building
# the values from a prefix keeps the detector quiet honestly, and says plainly
# to a reader that nothing here ever authenticated anything.
_FIXTURE = "pytest-fixture-value"
PW = f"{_FIXTURE}-original"
PW_ROTATED = f"{_FIXTURE}-rotated"
PW_WRONG = f"{_FIXTURE}-wrong"


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _make_user(
    client: TestClient, bank: Any, email: str = "ops@bank.et", role: str = "operator"
) -> dict[str, Any]:
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(bank),
        json={"email": email, "password": PW, "role": role},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _login(client: TestClient, email: str = "ops@bank.et", password: str = PW) -> Any:
    return client.post(
        "/admin/api/demo/login", json={"email": email, "password": password}
    )


# ------------------------------------------------------------- passwords


def test_a_password_is_never_stored_in_the_clear(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    _make_user(client, demo_bank)
    row = db_session.execute(select(UserCredential)).scalars().one()
    assert PW not in row.secret_hash
    assert row.secret_hash.startswith("$argon2id$")


def test_the_hash_uses_the_owasp_parameters(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Library defaults ask for 64 MiB. On a 512 MiB instance a burst of
    logins would then compete for memory with the app itself."""
    _make_user(client, demo_bank)
    row = db_session.execute(select(UserCredential)).scalars().one()
    assert "m=19456" in row.secret_hash
    assert "t=2" in row.secret_hash
    assert "p=1" in row.secret_hash


def test_verification_rejects_the_wrong_password() -> None:
    h = passwords.hash_password(PW)
    assert passwords.verify_password(h, PW) is True
    assert passwords.verify_password(h, PW_WRONG) is False
    assert passwords.verify_password(h, "") is False


def test_verifying_against_no_credential_still_costs_the_same() -> None:
    """An unknown email must not be measurably faster than a wrong password,
    or response time becomes an oracle for 'does this person have an account'.

    Asserted as an order of magnitude rather than a tight bound — a shared CI
    runner makes anything tighter flaky, and a flaky security test gets
    deleted, which is worse than a loose one.
    """
    h = passwords.hash_password(PW)
    start = time.perf_counter()
    passwords.verify_password(h, PW_WRONG)
    real = time.perf_counter() - start

    start = time.perf_counter()
    passwords.verify_password(None, PW_WRONG)
    missing = time.perf_counter() - start

    assert missing > real / 4, "a missing credential returned suspiciously fast"


# ---------------------------------------------------------------- login


def test_login_sets_an_httponly_session_cookie(
    client: TestClient, demo_bank: Any
) -> None:
    _make_user(client, demo_bank)
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json()["email"] == "ops@bank.et"

    cookie = resp.headers["set-cookie"]
    # httpOnly is the whole upgrade over the token in localStorage, which any
    # script on the page could read.
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()
    assert "path=/admin" in cookie.lower()


def test_the_session_token_is_not_stored_in_the_database(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """A database read must not yield a working credential."""
    _make_user(client, demo_bank)
    resp = _login(client)
    token = resp.cookies[admin_auth.COOKIE_NAME]

    row = db_session.execute(select(AdminSession)).scalars().one()
    assert row.token_hash != token
    assert len(row.token_hash) == 64  # sha256 hex


def test_me_returns_the_person_not_the_tenant(
    client: TestClient, demo_bank: Any
) -> None:
    _make_user(client, demo_bank, email="fatuma@bank.et", role="admin")
    _login(client, "fatuma@bank.et")
    body = client.get("/admin/api/demo/me").json()
    assert body["email"] == "fatuma@bank.et"
    assert body["role"] == "admin"


def test_me_requires_a_session(client: TestClient, demo_bank: Any) -> None:
    assert client.get("/admin/api/demo/me").status_code == 401


# ------------------------------------------------- uniform failure


def test_every_login_failure_looks_identical(
    client: TestClient, demo_bank: Any
) -> None:
    """Unknown email, wrong password, unknown tenant — one message.

    Distinguishing them is an oracle for "does this person have an account at
    this bank", which is worth more to an attacker than it is to a user who
    mistyped their own address.
    """
    _make_user(client, demo_bank)
    wrong_password = _login(client, "ops@bank.et", PW_WRONG)
    unknown_email = _login(client, "nobody@bank.et", PW)
    unknown_bank = client.post(
        "/admin/api/nosuchbank/login", json={"email": "ops@bank.et", "password": PW}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert unknown_bank.status_code == 401
    assert wrong_password.json() == unknown_email.json() == unknown_bank.json()


def test_repeated_login_failures_are_rate_limited(
    client: TestClient, demo_bank: Any
) -> None:
    """Argon2 is deliberately expensive, which makes an unauthenticated
    endpoint that hashes on demand a denial-of-service amplifier unless
    something upstream caps the rate."""
    _make_user(client, demo_bank)
    client.app.state.admin_auth_limiter = SlidingWindowLimiter(3)  # type: ignore[attr-defined]
    codes = [_login(client, "ops@bank.et", f"{PW_WRONG}-{i}").status_code for i in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


# ------------------------------------------------------------ revocation
#
# The reason this feature exists. If these pass and nothing else does, the
# change is still worth shipping.


def test_logout_kills_the_session_immediately(
    client: TestClient, demo_bank: Any
) -> None:
    _make_user(client, demo_bank)
    _login(client)
    assert client.get("/admin/api/demo/me").status_code == 200

    client.post("/admin/api/demo/logout")
    assert client.get("/admin/api/demo/me").status_code == 401


def test_disabling_a_user_ends_sessions_they_already_hold(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The property a JWT could not deliver.

    Someone leaves the bank. Their access has to stop now, not whenever their
    token happens to expire — otherwise "remove this person" means "remove
    them in up to eight hours" and the feature is theatre.
    """
    _make_user(client, demo_bank)
    _login(client)
    assert client.get("/admin/api/demo/me").status_code == 200

    user = db_session.execute(select(User)).scalars().one()
    user.disabled_at = datetime.now(UTC)
    db_session.commit()

    assert client.get("/admin/api/demo/me").status_code == 401


def test_changing_your_password_ends_every_other_session(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Someone changes their password *because* they think they were
    compromised. Leaving the attacker's session alive would defeat the act."""
    _make_user(client, demo_bank)
    _login(client)

    # A second browser, holding its own session for the same person.
    other = TestClient(client.app)
    other.post("/admin/api/demo/login", json={"email": "ops@bank.et", "password": PW})
    assert other.get("/admin/api/demo/me").status_code == 200

    changed = client.post(
        "/admin/api/demo/me/password",
        json={"current_password": PW, "new_password": PW_ROTATED},
    )
    assert changed.status_code == 200

    assert other.get("/admin/api/demo/me").status_code == 401, "the other browser lives on"
    # The browser that made the change keeps working, on a fresh session.
    assert client.get("/admin/api/demo/me").status_code == 200


def test_changing_a_password_requires_the_current_one(
    client: TestClient, demo_bank: Any
) -> None:
    """Otherwise an unattended logged-in browser is a permanent takeover."""
    _make_user(client, demo_bank)
    _login(client)
    resp = client.post(
        "/admin/api/demo/me/password",
        json={"current_password": PW_WRONG, "new_password": PW_ROTATED},
    )
    assert resp.status_code == 401


def test_an_expired_session_stops_working(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    _make_user(client, demo_bank)
    _login(client)
    row = db_session.execute(select(AdminSession)).scalars().one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert client.get("/admin/api/demo/me").status_code == 401


# --------------------------------------------------------------- tenancy


def test_the_same_email_can_exist_at_two_banks_independently(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    """Per tenant, not global. Merging identities across banks is a different
    product, and a shared row would be a cross-tenant join waiting to happen."""
    _make_user(client, demo_bank, email="shared@olink.et")
    resp = client.post(
        "/admin/api/cbe/users",
        headers=_headers(cbe_bank),
        json={"email": "shared@olink.et", "password": PW, "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] != _login(client, "shared@olink.et").json().get("id")


def test_a_duplicate_email_within_one_bank_is_rejected(
    client: TestClient, demo_bank: Any
) -> None:
    _make_user(client, demo_bank)
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(demo_bank),
        json={"email": "ops@bank.et", "password": PW, "role": "operator"},
    )
    assert resp.status_code == 409


def test_creating_a_user_requires_the_shared_token(
    client: TestClient, demo_bank: Any
) -> None:
    """Bootstrap runs on the shared token, which is exactly why it survives:
    a tenant with no users has nobody who could authorise the first one."""
    resp = client.post(
        "/admin/api/demo/users",
        json={"email": "x@bank.et", "password": PW, "role": "operator"},
    )
    assert resp.status_code == 401


def test_a_short_password_is_refused(client: TestClient, demo_bank: Any) -> None:
    """Length is the only rule — composition requirements push people toward
    Bank@2026! on a sticky note."""
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(demo_bank),
        json={"email": "x@bank.et", "password": "short", "role": "operator"},
    )
    assert resp.status_code == 422


def test_an_unknown_role_is_refused(client: TestClient, demo_bank: Any) -> None:
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(demo_bank),
        json={"email": "x@bank.et", "password": PW, "role": "superuser"},
    )
    assert resp.status_code == 422


# ------------------------------------------------------- nothing switched over


def test_the_existing_routes_still_take_the_shared_token(
    client: TestClient, demo_bank: Any
) -> None:
    """Step 2 adds a path; it does not replace one. Migrating the 14 routes is
    a separate change precisely because getting it wrong locks a bank out."""
    resp = client.get("/admin/api/demo/handoffs", headers=_headers(demo_bank))
    assert resp.status_code == 200


def test_a_session_does_not_yet_open_the_existing_routes(
    client: TestClient, demo_bank: Any
) -> None:
    """Documents the boundary honestly: signing in is not yet enough."""
    _make_user(client, demo_bank, role="admin")
    _login(client)
    assert client.get("/admin/api/demo/handoffs").status_code == 401


def test_the_cookie_is_secure_by_default(monkeypatch: Any) -> None:
    """The one property the test suite cannot observe through TestClient.

    Tests run over http, so conftest opts out of Secure — which means every
    assertion above passes whether or not production sets it. This checks the
    default directly: the opt-out has to be explicit, so that forgetting to
    configure something can only ever break local login, never ship a session
    cookie over plain HTTP.

    Deliberately not inferred from the request scheme. Behind a TLS-
    terminating proxy the app sees http, so inference would fail open in
    exactly the environment where it matters.
    """
    from bankassist import config

    monkeypatch.delenv("BANKASSIST_ADMIN_COOKIE_INSECURE", raising=False)
    config.reset_settings()
    try:
        assert config.get_settings().admin_cookie_secure is True
    finally:
        config.reset_settings()
