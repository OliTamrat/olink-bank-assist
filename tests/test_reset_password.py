"""A forgotten admin password was a total lockout.

`change_own_password` is the only route in the product that writes a password
and it requires the current one. On a tenant that has users the admin token
authenticates nothing (ADR-0031), no colleague can reset anybody, and MFA
recovery codes recover the *second* factor rather than the first. So an
administrator who forgot their password had no supported path back in at all —
only hand-written SQL against production.

That is a routine failure at any bank. `create_admin` could only offer "make a
second account under a different address and abandon the first", which is not
a recovery, it is a mess.

The properties under test, in the order they would hurt if lost:

1. the new password works and the old one does not;
2. **every other session is revoked** — a reset that left them alive leaves
   whoever knew the old password signed in, which is the opposite of the point
   and the exact case where someone resets *because* they suspect compromise;
3. the password is never an argument, same as `create_admin`;
4. the second factor is **not** touched, and the operator is told so — because
   somebody who lost their authenticator will otherwise read "password reset"
   as "back in", and meet a code prompt they cannot answer.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import admin_auth, create_admin, passwords, reset_password
from bankassist.models import AdminSession, AuditLog, User, UserCredential

OLD = "OriginalPassword9!"
NEW = "ReplacementPassword9!"


def _make_account(monkeypatch: pytest.MonkeyPatch, email: str = "boss@olink.et") -> None:
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _p: OLD)
    assert create_admin.main(["demo", "--email", email]) == 0


def _reset(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], typed: str = NEW
) -> int:
    monkeypatch.setattr(reset_password.getpass, "getpass", lambda _p: typed)
    return reset_password.main(argv)


def test_the_new_password_works_and_the_old_one_does_not(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserted through the real login route, not by reading the hash back.

    A reset that writes a row the login path will not accept is worse than no
    reset: it looks like it worked.
    """
    _make_account(monkeypatch)
    assert _reset(monkeypatch, ["demo", "--email", "boss@olink.et"]) == 0

    ok = client.post(
        "/admin/api/demo/login", json={"email": "boss@olink.et", "password": NEW}
    )
    assert ok.status_code == 200, ok.text

    stale = client.post(
        "/admin/api/demo/login", json={"email": "boss@olink.et", "password": OLD}
    )
    assert stale.status_code == 401, "the old password must stop working"


def test_every_existing_session_is_revoked(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property that makes this a security action rather than a convenience."""
    _make_account(monkeypatch)
    user = db_session.execute(select(User)).scalars().one()
    admin_auth.issue(db_session, user, ip=None, user_agent="a browser")
    admin_auth.issue(db_session, user, ip=None, user_agent="another")
    db_session.commit()

    live = select(AdminSession).where(
        AdminSession.user_id == user.id, AdminSession.revoked_at.is_(None)
    )
    assert len(db_session.execute(live).scalars().all()) == 2

    assert _reset(monkeypatch, ["demo", "--email", "boss@olink.et"]) == 0
    db_session.expire_all()
    assert db_session.execute(live).scalars().all() == []


def test_it_is_audited_without_recording_the_password(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone regaining access to every customer conversation a tenant holds
    is exactly what an audit log is for. The value never appears in it — the
    same rule the rest of the log follows for chat text and phone numbers."""
    _make_account(monkeypatch)
    _reset(monkeypatch, ["demo", "--email", "boss@olink.et"])

    row = db_session.execute(
        select(AuditLog).where(AuditLog.action == "password_reset")
    ).scalars().one()
    assert row.actor == reset_password.ACTOR
    assert row.entity_type == "user"
    assert NEW not in str(row.log_metadata)
    assert OLD not in str(row.log_metadata)


def test_an_unknown_address_writes_nothing_and_names_no_one(
    client: TestClient, demo_bank: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It reports the account COUNT, never the addresses.

    This runs in terminals and CI logs, and an email address is personal data.
    The count still answers the question actually being asked — "am I on the
    right tenant?" — which is the likeliest way to run this wrong.
    """
    _make_account(monkeypatch, email="someone@olink.et")
    capsys.readouterr()

    assert _reset(monkeypatch, ["demo", "--email", "typo@olink.et"]) == 1
    err = capsys.readouterr().err
    assert "1 account" in err
    assert "someone@olink.et" not in err


def test_an_empty_tenant_is_pointed_at_the_other_command(
    client: TestClient, demo_bank: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to reset is not the same failure as a mistyped address, and
    sending someone to `create_admin` beats letting them retry the spelling."""
    assert _reset(monkeypatch, ["demo", "--email", "boss@olink.et"]) == 1
    assert "create_admin" in capsys.readouterr().err


def test_a_short_password_is_refused_and_the_old_one_survives(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal must not have already destroyed the credential it refused to
    replace — that would turn a typo into the lockout this command fixes."""
    _make_account(monkeypatch)
    assert _reset(monkeypatch, ["demo", "--email", "boss@olink.et"], typed="short") == 1

    row = db_session.execute(select(UserCredential)).scalars().one()
    assert passwords.verify_password(row.secret_hash, OLD)


def test_a_mistyped_confirmation_writes_nothing(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_account(monkeypatch)
    answers = iter([NEW, "SomethingElse9!"])
    monkeypatch.setattr(reset_password.getpass, "getpass", lambda _p: next(answers))
    assert reset_password.main(["demo", "--email", "boss@olink.et"]) == 1

    row = db_session.execute(select(UserCredential)).scalars().one()
    assert passwords.verify_password(row.secret_hash, OLD)


def test_the_second_factor_is_never_removed(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deliberate, not unfinished.

    Clearing MFA from a command line would make ADR-0027's second factor
    something one command removes. It is reported instead, so whoever runs
    this knows a new password alone will not get them in — and so that
    removing a second factor stays a decision somebody takes on purpose.
    """
    _make_account(monkeypatch)
    user = db_session.execute(select(User)).scalars().one()
    db_session.add(
        UserCredential(
            user_id=user.id,
            kind="totp",
            secret_hash="JBSWY3DPEHPK3PXP",
            verified_at=user.created_at,
        )
    )
    db_session.commit()

    capsys_free = _reset(monkeypatch, ["demo", "--email", "boss@olink.et"])
    assert capsys_free == 0

    db_session.expire_all()
    totp = db_session.execute(
        select(UserCredential).where(UserCredential.kind == "totp")
    ).scalars().one()
    assert totp.verified_at is not None, "a reset must not disable two-factor"


def test_it_says_so_when_a_second_factor_will_still_be_asked_for(
    client: TestClient, demo_bank: Any, db_session: Any, capsys: Any,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence here reads as "you are back in", and the person most likely to
    run this is the one who has lost something."""
    _make_account(monkeypatch)
    user = db_session.execute(select(User)).scalars().one()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="totp", secret_hash="JBSWY3DPEHPK3PXP",
            verified_at=user.created_at,
        )
    )
    db_session.commit()
    capsys.readouterr()

    _reset(monkeypatch, ["demo", "--email", "boss@olink.et"])
    assert "two-factor" in capsys.readouterr().out


def test_an_unenrolled_second_factor_is_not_announced(
    client: TestClient, demo_bank: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`verified_at is None` is an abandoned enrolment, not a second factor —
    the same rule ADR-0027 draws for whether MFA counts at all. Warning about
    one would send somebody hunting for an authenticator they never finished
    setting up."""
    _make_account(monkeypatch)
    capsys.readouterr()
    _reset(monkeypatch, ["demo", "--email", "boss@olink.et"])
    assert "two-factor" not in capsys.readouterr().out


def test_the_password_can_never_be_an_argument() -> None:
    """The same guard as create_admin, for the same reason, on the command
    that is *more* likely to be scripted: argv is the shell's history, the
    process list, and every CI log that echoes the command."""
    with pytest.raises(SystemExit):
        reset_password.main(["demo", "--email", "a@b.et", "--password", NEW])
