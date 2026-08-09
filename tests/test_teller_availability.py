"""Whether a customer is offered a live teller at all.

Two independent facts have to hold: the tenant has switched the feature on,
and somebody is actually watching the queue this minute. The tests here are
mostly about the second one, because it is the one a reasonable implementation
skips — and skipping it produces a button that queues a customer behind nobody
at 22:00, watches a counter climb, and loses them. That is worse than the
assistant saying plainly that it cannot help.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import api as api_module
from bankassist import passwords, permissions, teller
from bankassist.models import Bank, Role, RolePermission, TellerSession, User, UserCredential


@pytest.fixture(autouse=True)
def _livekit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Availability now needs a configured media layer as well as a present
    teller, so these tests have to supply one.

    Without this every `teller_available is True` assertion here fails and
    every `is False` one passes for the wrong reason — they would be measuring
    the missing LIVEKIT_* variables rather than the presence logic they name.
    """
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APItest")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s" * 32)


def _conversation(client: TestClient, slug: str = "demo") -> str:
    resp = client.post(f"/chat/{slug}", json={"message": "Hello"})
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["conversation_id"]
    return cid


def _staff(
    client: TestClient, db_session: Any, bank: Any, email: str, role_name: str
) -> User:
    role = db_session.execute(
        select(Role).where(Role.bank_id == bank.id, Role.name == role_name)
    ).scalar_one()
    user = User(bank_id=bank.id, email=email, display_name=email, role_id=role.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    resp = client.post(
        f"/admin/api/{bank.slug}/login",
        json={"email": email, "password": "CorrectHorse9!x"},
    )
    assert resp.status_code == 200, resp.text
    return user


def _set_enabled(db_session: Any, slug: str, value: bool) -> None:
    """Flip the tenant flag through the session that owns the row.

    Not `bank_fixture.teller_enabled = ...` — the seed helpers build their own
    session, so the fixture object is attached to a session nobody commits.
    Assigning to it and committing `db_session` writes nothing at all, and a
    test whose setup silently no-ops still passes whenever it asserts the
    unchanged behaviour. Two of these did.
    """
    bank = db_session.execute(select(Bank).where(Bank.slug == slug)).scalar_one()
    bank.teller_enabled = value
    db_session.commit()


def _available(client: TestClient, slug: str = "demo") -> bool:
    body = client.get(f"/banks/{slug}/public").json()
    assert "teller_available" in body, "the widget decides on this field"
    return bool(body["teller_available"])


# ------------------------------------------------------------- availability


def test_a_bank_with_nobody_watching_offers_nothing(
    client: TestClient, demo_bank: Any
) -> None:
    """The feature is on for the demo tenant, but no teller has ever polled.

    This is the state every deployment starts in and the one that must not
    light the button.
    """
    assert demo_bank.teller_enabled is True
    assert _available(client) is False


def test_a_teller_watching_the_queue_turns_the_offer_on(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Polling the queue IS the presence signal — no separate heartbeat to
    forget to send, and no way to appear online without a page that could
    actually answer."""
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    assert _available(client) is False, "signing in is not being at the desk"
    assert client.get("/admin/api/demo/teller/queue").status_code == 200
    assert _available(client) is True


def test_presence_goes_stale(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A teller who closed the tab an hour ago is not available.

    Without this the first poll of the day would leave the button lit until
    the next deploy — the failure mode is silent and permanent, which is the
    worst combination.
    """
    user = _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.get("/admin/api/demo/teller/queue")
    assert _available(client) is True

    stale = datetime.now(UTC) - api_module.TELLER_PRESENCE_WINDOW - timedelta(seconds=5)
    db_session.get(User, user.id).teller_seen_at = stale
    db_session.commit()
    assert _available(client) is False


def test_a_supervisor_watching_is_not_a_teller_answering(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """`sessions.read` can watch the queue; only `teller.serve` can take the
    call. Counting a watcher as presence lights the button with nobody behind
    it — precisely the failure the presence check exists to prevent.

    A custom role, because no built-in one separates these: operator holds
    neither permission and admin deliberately holds both. This is the shape a
    bank actually builds — a floor supervisor who watches the queue all day
    and never answers — so the distinction has to hold for roles the bank
    invents, not just the three we ship.
    """
    role = Role(bank_id=demo_bank.id, name="supervisor", is_builtin=False)
    db_session.add(role)
    db_session.flush()
    db_session.add(
        RolePermission(role_id=role.id, permission=permissions.Perm.SESSIONS_READ)
    )
    db_session.commit()

    user = User(
        bank_id=demo_bank.id, email="sup@bank.et", display_name="Sup", role_id=role.id
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    assert client.post(
        "/admin/api/demo/login",
        json={"email": "sup@bank.et", "password": "CorrectHorse9!x"},
    ).status_code == 200

    assert client.get("/admin/api/demo/teller/queue").status_code == 200
    assert _available(client) is False
    # And the reason is that the poll did not count as presence, not merely
    # that the availability query filters them out later.
    #
    # `expire_all` first: this session has the row cached from the write above
    # with `expire_on_commit=False`, so `get()` would hand back that stale copy
    # and report None no matter what the request actually wrote. Verified by
    # mutation — without the expire, removing the permission check from the
    # queue route leaves this assertion still passing.
    db_session.expire_all()
    assert db_session.get(User, user.id).teller_seen_at is None


def test_a_disabled_teller_is_not_available(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Someone who has left the bank must not hold the queue open."""
    user = _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.get("/admin/api/demo/teller/queue")
    assert _available(client) is True

    db_session.get(User, user.id).disabled_at = datetime.now(UTC)
    db_session.commit()
    assert _available(client) is False


def test_switching_the_feature_off_takes_the_offer_away(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.get("/admin/api/demo/teller/queue")
    assert _available(client) is True

    _set_enabled(db_session, "demo", False)
    assert _available(client) is False


def test_presence_does_not_leak_across_tenants(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any
) -> None:
    """A teller at one bank must not light another bank's button."""
    _set_enabled(db_session, "cbe", True)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    client.get("/admin/api/demo/teller/queue")
    assert _available(client, "demo") is True
    assert _available(client, "cbe") is False


# --------------------------------------------------------------- the gate


def test_a_tenant_without_the_feature_refuses_to_queue_anyone(
    client: TestClient, cbe_bank: Any
) -> None:
    """Enforced on the server, not by hiding a button.

    The widget is public JavaScript on a bank's own website — anyone can read
    it, find this route and POST to it. A tenant that has not turned the
    feature on must not accumulate a queue of customers no employee can see.
    """
    assert cbe_bank.teller_enabled is False
    cid = _conversation(client, "cbe")
    resp = client.post("/chat/cbe/teller-session", json={"conversation_id": cid})
    assert resp.status_code == 409, resp.text


def test_the_queue_position_is_there_from_the_first_response(
    client: TestClient, demo_bank: Any
) -> None:
    """Returned by create, not only by poll.

    Shipping it on poll alone left the customer looking at a spinner with no
    number until the first poll landed — three seconds of exactly the screen
    the panel exists to avoid, and invisible to any test that only read the
    poll.
    """
    cid = _conversation(client)
    body = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()
    assert body["ahead"] == 0

    second = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()
    assert second["ahead"] == 1


# ------------------------------------------------------------- the setting


def test_a_teller_cannot_switch_the_product_on_for_the_bank(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Answering calls and deciding the bank offers calls are different jobs.

    `integrations.manage`, the same bar as repointing the handoff webhook.
    """
    _set_enabled(db_session, "demo", False)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    resp = client.put("/admin/api/demo/teller/settings", json={"enabled": True})
    assert resp.status_code == 403, resp.text


def test_an_administrator_can_switch_it_on_and_off(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _staff(client, db_session, demo_bank, "boss@bank.et", permissions.ADMIN)
    off = client.put("/admin/api/demo/teller/settings", json={"enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert client.get("/admin/api/demo/teller/settings").json()["enabled"] is False

    on = client.put("/admin/api/demo/teller/settings", json={"enabled": True})
    assert on.json()["enabled"] is True


def test_switching_off_does_not_drop_people_already_waiting(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Those are real people in a queue. Dropping them silently to make a
    toggle tidy loses a customer mid-conversation; the queue drains and no new
    sessions start."""
    cid = _conversation(client)
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()["id"]

    _staff(client, db_session, demo_bank, "boss@bank.et", permissions.ADMIN)
    assert client.put(
        "/admin/api/demo/teller/settings", json={"enabled": False}
    ).status_code == 200

    still = client.get(f"/chat/demo/teller-session/{sid}").json()
    assert still["state"] == teller.QUEUED
    assert db_session.get(TellerSession, sid).state == teller.QUEUED
