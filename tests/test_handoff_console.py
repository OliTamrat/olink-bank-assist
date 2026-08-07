"""The handoff queue as work, not history.

Before this the queue could only move a row from open to closed. That is
enough to make it disappear and not enough to run a support function: nobody
could tell whether a customer was called back, whether the answer got written
into the knowledge base, or whether someone closed it to clear the list.

The ordering matters as much as the fields. Newest-first is the wrong order
for work — a customer who has waited three days outranks one who asked five
minutes ago, and the old default buried them under 200 rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist.models import AuditLog, Handoff

UNANSWERABLE = "Do you sponsor competitive cheese rolling tournaments?"
ALSO_UNANSWERABLE = "How tall is the tallest giraffe in the zoo?"


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _ask(client: TestClient, message: str) -> dict[str, Any]:
    resp = client.post("/chat/demo", json={"message": message})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _handoffs(client: TestClient, bank: Any, status: str = "open") -> list[dict[str, Any]]:
    resp = client.get(f"/admin/api/demo/handoffs?status={status}", headers=_headers(bank))
    assert resp.status_code == 200, resp.text
    rows: list[dict[str, Any]] = resp.json()
    return rows


# --------------------------------------------------------------- ordering


def test_the_open_queue_is_oldest_first(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The longest wait is the next call to make."""
    _ask(client, UNANSWERABLE)
    _ask(client, ALSO_UNANSWERABLE)

    # Age the first one so the ordering is unambiguous rather than incidental.
    rows = db_session.execute(select(Handoff).order_by(Handoff.created_at)).scalars().all()
    rows[0].detail = "OLDEST"
    rows[0].created_at = datetime.now(UTC) - timedelta(days=3)
    db_session.commit()

    queue = _handoffs(client, demo_bank)
    assert len(queue) == 2
    assert queue[0]["detail"] == "OLDEST"


def test_closed_handoffs_are_newest_first(
    client: TestClient, demo_bank: Any
) -> None:
    """That view is history, not a queue, so recency is the useful order."""
    _ask(client, UNANSWERABLE)
    _ask(client, ALSO_UNANSWERABLE)
    for row in _handoffs(client, demo_bank):
        client.post(
            f"/admin/api/demo/handoffs/{row['id']}/close", headers=_headers(demo_bank)
        )

    closed = _handoffs(client, demo_bank, status="closed")
    assert len(closed) == 2
    assert closed[0]["created_at"] >= closed[1]["created_at"]


def test_the_default_view_hides_closed_work(
    client: TestClient, demo_bank: Any
) -> None:
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]
    client.post(f"/admin/api/demo/handoffs/{row['id']}/close", headers=_headers(demo_bank))

    assert _handoffs(client, demo_bank) == []
    assert len(_handoffs(client, demo_bank, status="all")) == 1


def test_an_unknown_status_is_rejected(client: TestClient, demo_bank: Any) -> None:
    resp = client.get(
        "/admin/api/demo/handoffs?status=everything", headers=_headers(demo_bank)
    )
    assert resp.status_code == 400


# ------------------------------------------------------------- resolution


def test_closing_records_what_was_done(
    client: TestClient, demo_bank: Any
) -> None:
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]

    resp = client.post(
        f"/admin/api/demo/handoffs/{row['id']}/close",
        headers=_headers(demo_bank),
        json={"resolution": "Called back, sent the rate sheet."},
    )
    assert resp.status_code == 200

    closed = _handoffs(client, demo_bank, status="closed")[0]
    assert closed["resolution"] == "Called back, sent the rate sheet."
    assert closed["resolved_at"] is not None


def test_closing_without_a_note_still_works(
    client: TestClient, demo_bank: Any
) -> None:
    """Requiring prose would only produce a queue full of "done".

    This is also the exact call the admin panel made before resolutions
    existed — a POST with a JSON content type and no body at all.
    """
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]

    resp = client.post(
        f"/admin/api/demo/handoffs/{row['id']}/close",
        headers={**_headers(demo_bank), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["resolution"] is None


def test_reopening_puts_it_back_in_the_queue_and_keeps_the_note(
    client: TestClient, demo_bank: Any
) -> None:
    """Nobody picked up is the realistic case, and closing was otherwise the
    only irreversible action in the panel. The previous note stays — it is the
    record of the attempt that did not work."""
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]
    client.post(
        f"/admin/api/demo/handoffs/{row['id']}/close",
        headers=_headers(demo_bank),
        json={"resolution": "No answer, will retry."},
    )

    resp = client.post(
        f"/admin/api/demo/handoffs/{row['id']}/reopen", headers=_headers(demo_bank)
    )
    assert resp.status_code == 200

    queue = _handoffs(client, demo_bank)
    assert len(queue) == 1
    assert queue[0]["resolution"] == "No answer, will retry."
    assert queue[0]["resolved_at"] is None


# ------------------------------------------------------- tenancy + privacy


def test_one_bank_cannot_touch_another_banks_handoff(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    client.post("/chat/cbe", json={"message": UNANSWERABLE})
    cbe_row = client.get(
        "/admin/api/cbe/handoffs", headers=_headers(cbe_bank)
    ).json()[0]

    for action in ("close", "reopen"):
        resp = client.post(
            f"/admin/api/demo/handoffs/{cbe_row['id']}/{action}",
            headers=_headers(demo_bank),
        )
        assert resp.status_code == 404, action


def test_the_resolution_text_never_reaches_the_audit_log(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """A note may quote the customer, so it is audited as a fact rather than a
    value — the same rule chat text follows everywhere else."""
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]
    client.post(
        f"/admin/api/demo/handoffs/{row['id']}/close",
        headers=_headers(demo_bank),
        json={"resolution": "Reached Oli on 0911234567."},
    )

    entries = db_session.execute(
        select(AuditLog).where(AuditLog.action == "handoff_closed")
    ).scalars().all()
    assert entries
    for entry in entries:
        assert "0911234567" not in str(entry.log_metadata)
        assert entry.log_metadata is not None
        assert entry.log_metadata["had_resolution"] is True


def test_reopening_is_audited(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    _ask(client, UNANSWERABLE)
    row = _handoffs(client, demo_bank)[0]
    client.post(f"/admin/api/demo/handoffs/{row['id']}/close", headers=_headers(demo_bank))
    client.post(f"/admin/api/demo/handoffs/{row['id']}/reopen", headers=_headers(demo_bank))

    entries = db_session.execute(
        select(AuditLog).where(AuditLog.action == "handoff_reopened")
    ).scalars().all()
    assert len(entries) == 1


def test_the_queue_requires_the_admin_token(client: TestClient, demo_bank: Any) -> None:
    assert client.get("/admin/api/demo/handoffs").status_code == 401
    assert client.post("/admin/api/demo/handoffs/anything/reopen").status_code == 401
