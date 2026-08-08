"""Handoffs delivered into the bank's own contact-centre tool.

The admin console is one way to work the queue. A bank already running
Freshdesk, Zendesk or an in-house CRM will not adopt a second inbox for a
pilot, and asking them to is how a pilot stalls on a process question rather
than on the product.

These run against a REAL http server on localhost rather than a mocked httpx.
The thing under test is whether a request actually leaves the process, arrives
with a body the receiver can verify, and — most importantly — whether a
receiver that is down, slow or hostile can damage the customer's turn. A mock
proves none of that, and this project has already shipped a feature that was
broken in production while every test that covered it passed against a mock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bankassist import handoff_webhook
from bankassist.models import Bank, Handoff

UNANSWERABLE = "Do you sponsor competitive cheese rolling tournaments?"


class _Receiver:
    """A bank's contact-centre endpoint, for the duration of one test."""

    def __init__(self, status: int = 200, hang: float = 0.0) -> None:
        self.received: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                outer.received.append({"raw": raw, "headers": dict(self.headers)})
                if hang:
                    import time as _t
                    _t.sleep(hang)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    def stop(self) -> None:
        self.server.shutdown()


@pytest.fixture
def receiver() -> Any:
    r = _Receiver()
    yield r
    r.stop()


def _connect(db: Session, bank_id: str, url: str, secret: str = "s3cret") -> None:
    row = db.get(Bank, bank_id)
    assert row is not None
    row.handoff_webhook_url = url
    row.handoff_webhook_secret = secret
    db.commit()


# ------------------------------------------------------------- delivery


def test_a_handoff_is_delivered_and_signed(
    client: TestClient, demo_bank: Any, db_session: Session, receiver: Any
) -> None:
    _connect(db_session, demo_bank.id, receiver.url)

    client.post("/chat/demo", json={"message": UNANSWERABLE})

    assert len(receiver.received) == 1, "the bank's tool should have been called once"
    got = receiver.received[0]
    body = json.loads(got["raw"])
    assert body["event"] == "handoff.created"
    assert body["bank"] == "demo"
    assert body["reason"] == "unanswered_question"
    assert UNANSWERABLE in body["question"]

    # The signature has to verify with the tenant's own secret, computed over
    # the exact bytes that arrived — not over a re-serialised copy, which is
    # how signature checks pass in tests and fail in production.
    expected = "sha256=" + hmac.new(b"s3cret", got["raw"], hashlib.sha256).hexdigest()
    assert got["headers"][handoff_webhook.SIGNATURE_HEADER] == expected


def test_the_signature_changes_with_the_body() -> None:
    """A signature that did not depend on the body would authenticate any
    payload at all once one legitimate header leaked."""
    a = handoff_webhook.sign("k", b'{"handoff_id":"1"}')
    b = handoff_webhook.sign("k", b'{"handoff_id":"2"}')
    assert a != b


def test_nothing_is_sent_when_no_webhook_is_configured(
    client: TestClient, demo_bank: Any, receiver: Any
) -> None:
    """Off by default. This posts a customer's question and phone number to a
    third party, so it happens only where a bank has asked for it."""
    client.post("/chat/demo", json={"message": UNANSWERABLE})
    assert receiver.received == []


def test_a_url_without_a_secret_is_never_posted_to(
    client: TestClient, demo_bank: Any, db_session: Session, receiver: Any
) -> None:
    """An unsigned POST is one the receiver cannot authenticate. A
    half-configured tenant must not ship personal data to an endpoint that
    cannot tell whether the request really came from us."""
    row = db_session.get(Bank, demo_bank.id)
    assert row is not None
    row.handoff_webhook_url = receiver.url
    row.handoff_webhook_secret = None
    db_session.commit()

    client.post("/chat/demo", json={"message": UNANSWERABLE})
    assert receiver.received == []


# --------------------------------------------------- failing safely


def test_a_dead_endpoint_never_breaks_the_customers_turn(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """The whole reason delivery happens after the commit.

    A bank's CRM being down is not the customer's problem, and the handoff is
    already in our console — so the worst case is a missed notification.
    """
    # Nothing is listening on this port.
    _connect(db_session, demo_bank.id, "http://127.0.0.1:9/nowhere")

    resp = client.post("/chat/demo", json={"message": UNANSWERABLE})
    assert resp.status_code == 200
    assert resp.json()["handoff_created"] is True

    filed = db_session.query(Handoff).filter(Handoff.bank_id == demo_bank.id).all()
    assert len(filed) == 1, "the handoff must survive a failed delivery"


def test_an_erroring_endpoint_is_reported_as_undelivered(
    demo_bank: Any, db_session: Session
) -> None:
    r = _Receiver(status=500)
    try:
        _connect(db_session, demo_bank.id, r.url)
        bank = db_session.get(Bank, demo_bank.id)
        handoff = Handoff(
            bank_id=demo_bank.id, conversation_id="c1",
            reason="unanswered_question", detail="x",
        )
        db_session.add(handoff)
        db_session.commit()
        assert bank is not None
        assert handoff_webhook.deliver(bank, handoff) is False
    finally:
        r.stop()


# ----------------------------------------------------------- privacy


def test_the_payload_carries_no_transcript(
    client: TestClient, demo_bank: Any, db_session: Session, receiver: Any
) -> None:
    """A customer says things to a machine they would not put in a ticket.
    This is the one path where the data leaves our control, so it carries the
    question that caused the handoff and nothing else from the conversation."""
    first = client.post(
        "/chat/demo", json={"message": "How do I open a savings account?"}
    ).json()
    client.post(
        "/chat/demo",
        json={"message": UNANSWERABLE, "conversation_id": first["conversation_id"]},
    )
    _connect(db_session, demo_bank.id, receiver.url)
    client.post(
        "/chat/demo",
        # Deliberately shares no words with the demo corpus. "interplanetary
        # transfers to Mars" was the first attempt and it retrieved three
        # documents on the word "transfers" alone — so it was answered, filed
        # no handoff, and this test failed for a reason unrelated to privacy.
        json={"message": "Do you sponsor competitive yodelling championships?",
              "conversation_id": first["conversation_id"]},
    )

    assert receiver.received
    body = json.loads(receiver.received[-1]["raw"])
    assert "savings account" not in json.dumps(body)
    assert set(body) == {
        "event", "bank", "handoff_id", "conversation_id", "reason",
        "question", "contact_name", "contact_phone", "created_at",
    }


# ------------------------------------------------------------- admin


def test_connect_returns_the_secret_once_and_requires_https(
    client: TestClient, demo_bank: Any
) -> None:
    headers = {"X-Admin-Token": demo_bank.admin_token}

    bad = client.post(
        "/admin/api/demo/handoff-webhook", headers=headers,
        json={"url": "http://crm.example.com/hook"},
    )
    assert bad.status_code == 422, "plain http would put a phone number on the wire"

    ok = client.post(
        "/admin/api/demo/handoff-webhook", headers=headers,
        json={"url": "https://crm.example.com/hook"},
    )
    assert ok.status_code == 200
    assert ok.json()["secret"]

    # Not retrievable afterwards: a leaked admin token must not also hand over
    # the means to forge handoffs into the bank's ticketing system.
    listing = client.get("/admin/api/demo/handoffs", headers=headers).json()
    assert ok.json()["secret"] not in json.dumps(listing)


def test_disconnecting_clears_both_fields(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    headers = {"X-Admin-Token": demo_bank.admin_token}
    client.post(
        "/admin/api/demo/handoff-webhook", headers=headers,
        json={"url": "https://crm.example.com/hook"},
    )
    client.post("/admin/api/demo/handoff-webhook", headers=headers, json={"url": None})

    db_session.expire_all()
    row = db_session.get(Bank, demo_bank.id)
    assert row is not None
    assert row.handoff_webhook_url is None
    assert row.handoff_webhook_secret is None, "a stale secret is a live credential"


def test_configuring_it_requires_the_admin_token(client: TestClient, demo_bank: Any) -> None:
    resp = client.post(
        "/admin/api/demo/handoff-webhook", json={"url": "https://crm.example.com/hook"}
    )
    assert resp.status_code == 401
