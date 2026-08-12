"""The operations report — desks, resolution, staffing, load.

Overview answers "is the assistant working"; `/analytics/operations` answers
"is the operation keeping up". These tests hold its reporting rules the same
way test_analytics.py holds Overview's: averages are null when nothing was
measured (never 0), every desk appears zero-filled in a fixed order, the
window actually windows, and one tenant's operation never leaks into
another's report.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import departments, passwords, permissions
from bankassist.models import Handoff, Role, TellerSession, User, UserCredential


def _ops(client: TestClient, bank: Any, **params: Any) -> dict[str, Any]:
    resp = client.get(
        f"/admin/api/{bank.slug}/analytics/operations",
        headers={"X-Admin-Token": bank.admin_token},
        params=params,
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_a_fresh_tenant_reports_nulls_not_zeros(
    client: TestClient, demo_bank: Any
) -> None:
    data = _ops(client, demo_bank)
    assert data["escalations"]["avg_resolution_seconds"] is None
    assert data["live"]["avg_wait_seconds"] is None
    assert data["live"]["avg_handle_seconds"] is None
    assert data["escalations"]["open"] == 0
    assert data["busy"] == []


def test_every_desk_appears_zero_filled_in_the_fixed_order(
    client: TestClient, demo_bank: Any
) -> None:
    desks = _ops(client, demo_bank)["escalations"]["desks"]
    assert [d["department"] for d in desks] == list(departments.DEPARTMENTS)
    for d in desks:
        assert d["open"] == 0 and d["filed"] == 0 and d["resolved"] == 0
        assert d["avg_resolution_seconds"] is None
        assert d["label"]  # human name, not the code


def test_resolution_time_is_measured_on_the_desk_that_did_the_work(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Handoff(
            bank_id=demo_bank.id,
            conversation_id="c1",
            reason="unanswered_question",
            detail="my card was swallowed",
            department=departments.CARDS,
            priority=departments.NORMAL,
            status="closed",
            created_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
        )
    )
    db_session.add(
        Handoff(
            bank_id=demo_bank.id,
            conversation_id="c2",
            reason="complaint",
            detail="someone stole money from my account",
            department=departments.FRAUD,
            priority=departments.URGENT,
            status="open",
            created_at=now - timedelta(minutes=30),
        )
    )
    db_session.commit()

    data = _ops(client, demo_bank)
    esc = data["escalations"]
    assert esc["open"] == 1
    assert esc["urgent_open"] == 1
    assert esc["filed"] == 2
    assert esc["resolved"] == 1
    assert esc["avg_resolution_seconds"] == 3600

    by_desk = {d["department"]: d for d in esc["desks"]}
    assert by_desk[departments.CARDS]["resolved"] == 1
    assert by_desk[departments.CARDS]["avg_resolution_seconds"] == 3600
    assert by_desk[departments.CARDS]["open"] == 0
    assert by_desk[departments.FRAUD]["open"] == 1
    assert by_desk[departments.FRAUD]["urgent"] == 1
    assert by_desk[departments.FRAUD]["avg_resolution_seconds"] is None


def test_open_work_is_not_hidden_by_the_window(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """A row filed before the window and still open is the row a manager most
    needs to see — "open" is a present fact, not a windowed one."""
    db_session.add(
        Handoff(
            bank_id=demo_bank.id,
            conversation_id="c3",
            reason="unanswered_question",
            detail="loan eligibility",
            department=departments.LENDING,
            priority=departments.NORMAL,
            status="open",
            created_at=datetime.now(UTC) - timedelta(days=45),
        )
    )
    db_session.commit()

    data = _ops(client, demo_bank, days=7)
    assert data["escalations"]["open"] == 1
    assert data["escalations"]["filed"] == 0  # outside the 7-day window


def test_an_abandoned_session_counts_as_abandoned_not_handled(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        TellerSession(
            bank_id=demo_bank.id,
            conversation_id="c4",
            state="ended",
            requested_at=now - timedelta(minutes=10),
            ended_at=now - timedelta(minutes=7),
        )
    )
    db_session.add(
        TellerSession(
            bank_id=demo_bank.id,
            conversation_id="c5",
            state="ended",
            teller_user_id="someone",
            requested_at=now - timedelta(minutes=20),
            claimed_at=now - timedelta(minutes=19),
            ended_at=now - timedelta(minutes=14),
        )
    )
    db_session.commit()

    live = _ops(client, demo_bank)["live"]
    assert live["requested"] == 2
    assert live["claimed"] == 1
    assert live["abandoned"] == 1
    assert live["avg_wait_seconds"] == 60
    assert live["avg_handle_seconds"] == 300


def test_the_busy_buckets_count_only_what_customers_sent(
    client: TestClient, demo_bank: Any
) -> None:
    r = client.post("/chat/demo", json={"message": "How do I open an account?"})
    assert r.status_code == 200

    busy = _ops(client, demo_bank)["busy"]
    # One user message -> exactly one bucket with count 1; the assistant's
    # reply must not be in it.
    assert len(busy) == 1
    dow, hour, count = busy[0]
    assert count == 1
    now = datetime.now(UTC)
    assert (dow, hour) == (now.weekday(), now.hour)


def test_staffing_counts_front_line_tellers_not_admins(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    def _person(email: str, role_name: str, *, seen: bool) -> None:
        role = db_session.execute(
            select(Role).where(
                Role.bank_id == demo_bank.id, Role.name == role_name
            )
        ).scalar_one()
        user = User(
            bank_id=demo_bank.id, email=email, display_name=email,
            role_id=role.id,
            teller_seen_at=datetime.now(UTC) if seen else None,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(
            UserCredential(
                user_id=user.id, kind="password",
                secret_hash=passwords.hash_password("CorrectHorse9!x"),
            )
        )

    _person("on-air@bank.et", permissions.TELLER, seen=True)
    _person("off-air@bank.et", permissions.TELLER, seen=False)
    # An admin holds teller.serve too, but is not front-line staff — the same
    # rule /teller-performance applies to its roster.
    _person("boss@bank.et", permissions.ADMIN, seen=True)
    db_session.commit()

    staffing = _ops(client, demo_bank)["staffing"]
    assert staffing["front_line"] == 2
    assert staffing["on_duty_now"] == 1


def test_one_banks_operation_never_appears_in_anothers_report(
    client: TestClient, db_session: Any, demo_bank: Any, cbe_bank: Any
) -> None:
    db_session.add(
        Handoff(
            bank_id=demo_bank.id,
            conversation_id="c6",
            reason="complaint",
            detail="stolen card",
            department=departments.FRAUD,
            priority=departments.URGENT,
            status="open",
        )
    )
    db_session.commit()

    ours = _ops(client, demo_bank)
    theirs = _ops(client, cbe_bank)
    assert ours["escalations"]["open"] == 1
    assert theirs["escalations"]["open"] == 0


def test_a_teller_cannot_read_the_operations_report(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """`analytics.read` is the gate, and the teller role does not hold it —
    the same boundary Overview draws."""
    role = db_session.execute(
        select(Role).where(
            Role.bank_id == demo_bank.id, Role.name == permissions.TELLER
        )
    ).scalar_one()
    user = User(
        bank_id=demo_bank.id, email="teller@bank.et",
        display_name="teller@bank.et", role_id=role.id,
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

    session_client = TestClient(client.app)
    resp = session_client.post(
        "/admin/api/demo/login",
        json={"email": "teller@bank.et", "password": "CorrectHorse9!x"},
    )
    assert resp.status_code == 200, resp.text
    resp = session_client.get("/admin/api/demo/analytics/operations")
    assert resp.status_code == 403


@pytest.mark.parametrize("days", [-5, 9999])
def test_the_window_is_clamped_not_trusted(
    client: TestClient, demo_bank: Any, days: int
) -> None:
    data = _ops(client, demo_bank, days=days)
    assert 0 <= data["window_days"] <= 365
