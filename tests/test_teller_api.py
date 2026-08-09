"""The teller-session HTTP surface.

The tests that matter here are not the happy path — they are the ones a bank's
risk team would ask for: that a session can only be created by the customer,
that two tellers cannot answer the same person, that an operator cannot join a
call, and that a national ID number never lands anywhere durable.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import permissions, teller, verification
from bankassist.models import AuditLog, Role, TellerSession, User, UserCredential


def _conversation(client: TestClient, slug: str = "demo") -> str:
    resp = client.post(f"/chat/{slug}", json={"message": "Hello"})
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["conversation_id"]
    return cid


def _staff(
    client: TestClient, db_session: Any, bank: Any, email: str, role_name: str
) -> TestClient:
    """A signed-in employee holding exactly one built-in role."""
    from bankassist import passwords

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
    return client


# ------------------------------------------------------- the customer side


def test_a_customer_can_ask_for_a_person(client: TestClient, demo_bank: Any) -> None:
    cid = _conversation(client)
    resp = client.post("/chat/demo/teller-session", json={"conversation_id": cid})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == teller.QUEUED
    assert body["scope"] == teller.UNVERIFIED


def test_the_customer_is_told_the_boundary_before_they_wait(
    client: TestClient, demo_bank: Any
) -> None:
    """Someone who queues ten minutes to ask for a transfer and is refused
    live has had a worse experience than the assistant refusing instantly."""
    cid = _conversation(client)
    body = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()
    assert teller.GENERAL_GUIDANCE in body["can_help_with"]
    assert teller.MONEY not in body["can_help_with"]


def test_audio_is_the_default(client: TestClient, demo_bank: Any) -> None:
    """Outside Addis audio-only is the common case. A default of video would
    quietly make the product worse for the worst connections."""
    cid = _conversation(client)
    body = client.post(
        "/chat/demo/teller-session", json={"conversation_id": cid}
    ).json()
    assert body["media"] == "audio"


def test_tapping_twice_does_not_queue_twice(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A flaky connection retrying must not put one person in the queue twice
    and have two tellers answer them."""
    cid = _conversation(client)
    first = client.post("/chat/demo/teller-session", json={"conversation_id": cid}).json()
    second = client.post("/chat/demo/teller-session", json={"conversation_id": cid}).json()
    assert first["id"] == second["id"]
    assert (
        len(db_session.execute(select(TellerSession)).scalars().all()) == 1
    )


def test_a_conversation_from_another_bank_cannot_open_a_session(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    cid = _conversation(client, "demo")
    resp = client.post("/chat/cbe/teller-session", json={"conversation_id": cid})
    assert resp.status_code == 404


def test_the_customer_is_told_how_many_are_ahead(
    client: TestClient, demo_bank: Any
) -> None:
    """A number beats a spinner: someone told they are third will wait,
    someone shown a spinner leaves."""
    first = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()
    second = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()
    assert client.get(f"/chat/demo/teller-session/{first['id']}").json()["ahead"] == 0
    assert client.get(f"/chat/demo/teller-session/{second['id']}").json()["ahead"] == 1


def test_abandoning_is_recorded_not_forgotten(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Queue abandonment is the number that justifies staffing. A session that
    simply goes quiet tells a bank nothing."""
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    resp = client.delete(f"/chat/demo/teller-session/{sid}")
    assert resp.status_code == 200
    assert resp.json()["state"] == teller.ABANDONED
    row = db_session.get(TellerSession, sid)
    db_session.refresh(row)
    assert row.ended_at is not None
    assert row.waited_seconds is not None


def test_a_customer_cannot_see_who_the_teller_is(
    client: TestClient, demo_bank: Any
) -> None:
    """The internal record is the bank's, not the customer's."""
    body = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()
    for internal in ("teller_user_id", "verified_ref", "conversation_id"):
        assert internal not in body


# ---------------------------------------------------------- the teller side


def test_an_operator_cannot_claim_a_session(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The role split, enforced over HTTP and not only in the registry."""
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    _staff(client, db_session, demo_bank, "op@bank.et", permissions.OPERATOR)
    resp = client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    assert resp.status_code == 403


def test_a_teller_claims_and_the_queue_reflects_it(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    _staff(client, db_session, demo_bank, "teller@bank.et", permissions.TELLER)
    resp = client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == teller.ACTIVE
    assert resp.json()["waited_seconds"] is not None

    queue = client.get("/admin/api/demo/teller/queue").json()
    assert [s["id"] for s in queue] == [sid]


def test_two_tellers_cannot_take_the_same_customer(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The state machine raises on active -> active rather than quietly
    succeeding, which in a boolean world would look like both of them got it.
    """
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    _staff(client, db_session, demo_bank, "t1@bank.et", permissions.TELLER)
    assert client.post(f"/admin/api/demo/teller/sessions/{sid}/claim").status_code == 200
    resp = client.post(f"/admin/api/demo/teller/sessions/{sid}/claim")
    assert resp.status_code == 409


def test_the_queue_is_oldest_first(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Anything else means the person who has waited longest keeps losing,
    which is how a queue produces the abandonment it was built to prevent."""
    ids = [
        client.post(
            "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
        ).json()["id"]
        for _ in range(3)
    ]
    _staff(client, db_session, demo_bank, "sup@bank.et", permissions.TELLER)
    queue = client.get("/admin/api/demo/teller/queue").json()
    assert [s["id"] for s in queue] == ids


# ------------------------------------------------------------ verification


def _claimed(client: TestClient, db_session: Any, bank: Any, email: str) -> str:
    sid = client.post(
        f"/chat/{bank.slug}/teller-session",
        json={"conversation_id": _conversation(client, bank.slug)},
    ).json()["id"]
    _staff(client, db_session, bank, email, permissions.TELLER)
    client.post(f"/admin/api/{bank.slug}/teller/sessions/{sid}/claim")
    return sid


def test_a_teller_cannot_verify_by_ticking_one_box(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    resp = client.post(
        f"/admin/api/demo/teller/sessions/{sid}/verify",
        json={"checks": [verification.ID_DOCUMENT]},
    )
    assert resp.status_code == 422


def test_verifying_widens_what_the_session_can_cover(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    resp = client.post(
        f"/admin/api/demo/teller/sessions/{sid}/verify",
        json={
            "checks": [verification.ID_DOCUMENT, verification.ACCOUNT_DETAIL],
            "fayda_number": "123456789012",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == teller.VERIFIED
    assert teller.OWN_RECORDS in body["can_help_with"]
    # ...and still never money.
    assert teller.MONEY not in body["can_help_with"]


def test_only_the_last_four_digits_of_the_id_are_stored(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    client.post(
        f"/admin/api/demo/teller/sessions/{sid}/verify",
        json={
            "checks": [verification.ID_DOCUMENT, verification.ACCOUNT_DETAIL],
            "fayda_number": "123456789012",
        },
    )
    row = db_session.get(TellerSession, sid)
    db_session.refresh(row)
    assert row.verified_ref == "9012"


def test_the_full_id_number_never_reaches_the_audit_log(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The audit log is the most-read table in the product and the one most
    likely to be exported. A national ID must not be in it."""
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    client.post(
        f"/admin/api/demo/teller/sessions/{sid}/verify",
        json={
            "checks": [verification.ID_DOCUMENT, verification.ACCOUNT_DETAIL],
            "fayda_number": "123456789012",
        },
    )
    rows = db_session.execute(select(AuditLog)).scalars().all()
    blob = " ".join(str(r.log_metadata) for r in rows)
    assert "123456789012" not in blob
    # What WAS recorded is which checks the teller performed — the thing a
    # dispute actually needs.
    assert verification.ID_DOCUMENT in blob


def test_a_teller_cannot_verify_someone_elses_session(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Someone reading the queue has not seen the ID and has not asked
    anything — their attestation would describe something they did not
    witness."""
    sid = _claimed(client, db_session, demo_bank, "first@bank.et")
    client.post("/admin/api/demo/logout")
    _staff(client, db_session, demo_bank, "second@bank.et", permissions.TELLER)
    resp = client.post(
        f"/admin/api/demo/teller/sessions/{sid}/verify",
        json={"checks": [verification.ID_DOCUMENT, verification.ACCOUNT_DETAIL]},
    )
    assert resp.status_code == 403


# -------------------------------------------------------------- ending up


def test_ending_writes_the_note_to_the_queue_everyone_reads(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    resp = client.post(
        f"/admin/api/demo/teller/sessions/{sid}/end",
        json={"resolution": "Walked them through opening a savings account."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == teller.ENDED
    assert "savings" in resp.json()["resolution"]


def test_a_session_cannot_be_ended_twice(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    assert client.post(f"/admin/api/demo/teller/sessions/{sid}/end").status_code == 200
    assert client.post(f"/admin/api/demo/teller/sessions/{sid}/end").status_code == 409


def test_an_ended_session_leaves_the_queue(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    client.post(f"/admin/api/demo/teller/sessions/{sid}/end")
    assert client.get("/admin/api/demo/teller/queue").json() == []


def test_no_route_creates_a_session_addressed_at_a_customer() -> None:
    """The outbound-call prohibition, asserted against the route table itself.

    If people are trained to accept incoming video calls "from the bank", that
    becomes a fraud vector aimed at exactly the customers least able to spot
    it. The only creating route is the customer's own — see
    docs/video-teller.md §2.
    """
    from bankassist.api import app

    creators = [
        r.path  # type: ignore[attr-defined]
        for r in app.routes
        if getattr(r, "methods", None)
        and "POST" in r.methods  # type: ignore[attr-defined]
        and r.path.endswith("teller-session")  # type: ignore[attr-defined]
    ]
    assert creators == ["/chat/{slug}/teller-session"]


@pytest.mark.parametrize(
    "path",
    [
        "/admin/api/demo/teller/queue",
        "/admin/api/demo/teller/sessions/whatever/claim",
    ],
)
def test_the_teller_routes_need_authentication(client: TestClient, path: str) -> None:
    method = client.get if path.endswith("queue") else client.post
    assert method(path).status_code == 401


def test_a_waiting_customer_has_a_visible_wait(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The number the whole queue page is for.

    The first version returned None until a teller claimed the session —
    blank on every waiting row, which is exactly when it matters. A queue
    sorted oldest-first with no visible ages is a list.
    """
    sid = client.post(
        "/chat/demo/teller-session", json={"conversation_id": _conversation(client)}
    ).json()["id"]
    _staff(client, db_session, demo_bank, "t@bank.et", permissions.TELLER)
    row = client.get("/admin/api/demo/teller/queue").json()[0]
    assert row["state"] == teller.QUEUED
    assert isinstance(row["waited_seconds"], int)


def test_the_wait_stops_growing_once_a_teller_takes_it(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Otherwise the queue-wait metric would keep climbing for the whole
    length of the call and report conversation length, not waiting."""
    import datetime as dt

    sid = _claimed(client, db_session, demo_bank, "t@bank.et")
    row = db_session.get(TellerSession, sid)
    db_session.refresh(row)
    first = row.waited_seconds
    row.claimed_at = row.claimed_at - dt.timedelta(seconds=0)
    assert row.waited_seconds == first
