"""Whether a customer is offered a live teller at all.

Three independent facts have to hold: the tenant has switched the feature on,
a media layer is configured, and somebody has declared themselves on duty this
minute. The tests here are mostly about the third, because it is the one a
reasonable implementation skips — and skipping it produces a button that
queues a customer behind nobody at 22:00, watches a counter climb, and loses
them. That is worse than the assistant saying plainly that it cannot help.

Presence used to be inferred from polling the queue page. That shipped, and it
failed in the field for a reason no test could have caught while the two were
the same thing: a teller who navigated to any other screen went off the air
silently, so the bank was staffed and the Connect button still never appeared.
Duty is now DECLARED at /teller/presence and nowhere else, which is why several
tests below assert the negative — that reading the queue does not, by itself,
put anybody on the air.
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


def _on_duty(client: TestClient, on: bool = True, slug: str = "demo") -> Any:
    """Declare duty, the way the console's heartbeat does.

    Every test that needs a present teller goes through here rather than
    through some direct write to `teller_seen_at`, so the route stays the only
    way presence is established — including in the tests.
    """
    resp = client.post(f"/admin/api/{slug}/teller/presence", json={"on_duty": on})
    assert resp.status_code == 200, resp.text
    return resp.json()


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
    assert _on_duty(client)["available"] is True
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
    _on_duty(client)
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
    # Refused outright rather than accepted and filtered out later. A watcher
    # who could record presence and simply not appear in the availability
    # query would be one join away from lighting the button with nobody
    # behind it; the route is the place to say no.
    assert client.post(
        "/admin/api/demo/teller/presence", json={"on_duty": True}
    ).status_code == 403

    # `expire_all` first: this session has the row cached from the write above
    # with `expire_on_commit=False`, so `get()` would hand back that stale copy
    # and report None no matter what the request actually wrote.
    db_session.expire_all()
    assert db_session.get(User, user.id).teller_seen_at is None


def test_a_disabled_teller_is_not_available(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Someone who has left the bank must not hold the queue open."""
    user = _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    assert _available(client) is True

    db_session.get(User, user.id).disabled_at = datetime.now(UTC)
    db_session.commit()
    assert _available(client) is False


def test_switching_the_feature_off_takes_the_offer_away(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    assert _available(client) is True

    _set_enabled(db_session, "demo", False)
    assert _available(client) is False


def test_presence_does_not_leak_across_tenants(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any
) -> None:
    """A teller at one bank must not light another bank's button."""
    _set_enabled(db_session, "cbe", True)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
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


# ------------------------------------------- availability on the chat itself


def test_every_reply_carries_whether_a_teller_can_be_reached_now(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Reported from the live demo: the queue page read "Customers can reach a
    teller now" while the widget in the next window still would not offer one.

    The widget read availability once, from /public at page load, and never
    again — so a customer who opened the chat before anyone came on duty was
    pinned to "no teller" for the whole conversation. This is the fix: the
    fact travels on the turn where it is used.
    """
    # Exactly the reported sequence. The customer is already chatting.
    first = client.post("/chat/demo", json={"message": "Hello"})
    assert first.json()["teller_available"] is False

    # A teller signs in and opens the queue — after the customer's page loaded.
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)

    later = client.post(
        "/chat/demo",
        json={
            "message": "Can I speak to a live agent?",
            "conversation_id": first.json()["conversation_id"],
        },
    )
    assert later.json()["teller_available"] is True, (
        "the reply does not know a teller arrived, so the widget cannot either"
    )


def test_the_reply_stops_offering_when_the_last_teller_leaves(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The same staleness in the other direction: a customer who opened the
    chat while somebody was on duty must not be offered a call after everyone
    has gone home."""
    user = _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    assert client.post("/chat/demo", json={"message": "Hello"}).json()[
        "teller_available"
    ] is True

    db_session.get(User, user.id).teller_seen_at = (
        datetime.now(UTC) - api_module.TELLER_PRESENCE_WINDOW - timedelta(seconds=5)
    )
    db_session.commit()
    assert client.post("/chat/demo", json={"message": "Hello again"}).json()[
        "teller_available"
    ] is False


# ------------------------------------------------------------------- on duty
#
# The section that exists because the first design of this shipped and failed.
# Presence was a side effect of the Live queue page polling, which meant the
# product-level fact "customers can talk to a person" was really the fact
# "somebody has one particular browser tab in front of them". The bank was
# switched on, a teller was signed in, and the Connect button never appeared.


def test_duty_survives_leaving_the_queue_page(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """THE REGRESSION. A teller on duty stays on the air while working
    anywhere else in the console.

    The heartbeat now runs from the shell, so the only thing that ends duty is
    ending it. Expressed here as: presence is established, the queue is never
    read again, and the offer stays up.
    """
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)

    # Working elsewhere. Any authenticated request that is not the queue —
    # `/me` is the one every signed-in person can make regardless of role, so
    # this test does not quietly become a permissions test.
    assert client.get("/admin/api/demo/me").status_code == 200
    assert _available(client) is True


def test_reading_the_queue_does_not_put_anyone_on_duty(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The other half of the same correction, and the one that stops the old
    behaviour creeping back.

    While polling was presence, a teller who had deliberately gone OFF duty
    was put straight back on by their own page's next poll — the switch could
    not be honoured by the screen it lived on. Duty is a declaration; reading
    a list is not one.
    """
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    assert client.get("/admin/api/demo/teller/queue").status_code == 200
    assert _available(client) is False


def test_going_off_duty_takes_the_offer_away_at_once(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Not after the staleness window — immediately.

    Waiting 90s to honour "I am leaving" would queue customers behind somebody
    who has already stood up, which is the exact experience the whole presence
    check exists to prevent.
    """
    user = _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    assert _available(client) is True

    assert _on_duty(client, False)["available"] is False
    assert _available(client) is False
    # Cleared, not backdated. NULL is a statement — "not taking calls" — where
    # an old timestamp merely says they were once here.
    db_session.expire_all()
    assert db_session.get(User, user.id).teller_seen_at is None


def test_signing_out_takes_you_off_the_air(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The one moment we know for certain the person has left.

    Leaving presence set here would hold the button lit for the rest of the
    staleness window with nobody behind it — the failure the window bounds,
    arriving by the one route where it is entirely avoidable.
    """
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    assert _available(client) is True

    assert client.post("/admin/api/demo/logout").status_code == 200
    assert _available(client) is False


def test_the_break_glass_token_cannot_go_on_duty(
    client: TestClient, demo_bank: Any
) -> None:
    """The shared token is nobody in particular, and a customer cannot be
    routed to nobody in particular. Presence is a claim about a person."""
    resp = client.post(
        "/admin/api/demo/teller/presence",
        json={"on_duty": True},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 403, resp.text


def test_duty_reports_what_the_customer_will_see(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Going on duty in a tenant that has the feature switched off must say so.

    Otherwise a teller flips the switch, sees it turn green, and waits all
    afternoon for calls that were never going to be offered — with the real
    cause two screens away.
    """
    _set_enabled(db_session, "demo", False)
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    body = _on_duty(client)
    assert body["on_duty"] is True
    assert body["available"] is False, "on duty, but the tenant offers nothing"


def test_the_heartbeat_is_faster_than_the_staleness_window(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A heartbeat at or slower than the window means every teller flickers
    off between beats. Both numbers are served to the browser precisely so
    they cannot drift apart; this asserts the relationship itself."""
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    beat = _on_duty(client)["heartbeat_seconds"]
    window = client.get("/admin/api/demo/teller/settings").json()[
        "presence_window_seconds"
    ]
    assert beat * 2 <= window, (
        "at least two beats must fit inside the window, or one dropped request "
        "takes the bank off the air"
    )


def test_going_on_and_off_duty_is_audited_but_the_heartbeat_is_not(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Auditing every beat would write 2,880 rows a day per teller and bury
    the events an auditor reads. The edges are the event; still being there is
    not."""
    from bankassist.models import AuditLog

    def rows() -> int:
        return len(
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.action.in_(("teller_on_duty", "teller_off_duty"))
                )
            ).scalars().all()
        )

    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    _on_duty(client)
    after_first = rows()
    assert after_first == 1

    _on_duty(client)   # the heartbeat, repeatedly
    _on_duty(client)
    assert rows() == after_first, "a heartbeat is not an event"

    _on_duty(client, False)
    assert rows() == after_first + 1
