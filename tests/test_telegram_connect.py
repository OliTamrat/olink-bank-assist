"""`POST /admin/api/{slug}/telegram/connect` — Telegram's own rejection must
reach the operator, not vanish into a bare 500.

`telegram.set_webhook()` calls `raise_for_status()`, and until this file
existed nothing caught what that raises. A pasted token with a typo, or an
`APP_BASE_URL` Telegram can't resolve, produced an unhandled
`httpx.HTTPStatusError` — FastAPI's default handler turns that into
`{"detail": "Internal Server Error"}`, which is exactly what an operator
reported seeing on every attempt, with nothing to tell them what to fix.
`viber_connect`, immediately above this route in api.py, already gets this
right (catch, roll back, surface the real reason) — this is that same shape
applied to the sibling function that was missing it.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient


def _fake_post(status: int, body: dict[str, Any]) -> Any:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        resp = httpx.Response(status, json=body, request=httpx.Request("POST", url))
        return resp

    return post


def test_a_rejected_token_returns_telegrams_own_reason_not_a_bare_500(
    client: TestClient, dashen_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        httpx, "post",
        _fake_post(400, {"ok": False, "description": "Bad Request: wrong bot token"}),
    )
    resp = client.post(
        "/admin/api/dashen/telegram/connect",
        json={"bot_token": "not-a-real-token-but-long-enough"},
        headers={"X-Admin-Token": dashen_bank.admin_token},
    )
    assert resp.status_code == 400, resp.text
    assert "wrong bot token" in resp.json()["detail"]


def test_a_rejected_token_does_not_overwrite_a_working_connection(
    client: TestClient, dashen_bank: Any, db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed paste must not silently disconnect a channel that was
    working a moment ago — same guarantee `viber_connect` already gives."""
    from bankassist.models import Bank

    bank = db_session.get(Bank, dashen_bank.id)
    bank.telegram_bot_token = "already-connected-token"
    bank.telegram_webhook_secret = "already-set-secret"
    db_session.commit()

    monkeypatch.setattr(
        httpx, "post",
        _fake_post(400, {"ok": False, "description": "Bad Request: wrong bot token"}),
    )
    resp = client.post(
        "/admin/api/dashen/telegram/connect",
        json={"bot_token": "a-typoed-replacement-token"},
        headers={"X-Admin-Token": dashen_bank.admin_token},
    )
    assert resp.status_code == 400

    db_session.expire_all()
    bank = db_session.get(Bank, dashen_bank.id)
    assert bank.telegram_bot_token == "already-connected-token"
    assert bank.telegram_webhook_secret == "already-set-secret"


def test_telegram_unreachable_is_a_502_not_a_500(
    client: TestClient, dashen_bank: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    resp = client.post(
        "/admin/api/dashen/telegram/connect",
        json={"bot_token": "some-token-value-here"},
        headers={"X-Admin-Token": dashen_bank.admin_token},
    )
    assert resp.status_code == 502, resp.text


def test_a_valid_token_still_connects(
    client: TestClient, dashen_bank: Any, db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the success path must survive adding error handling
    around it."""
    from bankassist.models import Bank

    monkeypatch.setattr(
        httpx, "post", _fake_post(200, {"ok": True, "result": True})
    )
    resp = client.post(
        "/admin/api/dashen/telegram/connect",
        json={"bot_token": "a-genuinely-valid-token-shape"},
        headers={"X-Admin-Token": dashen_bank.admin_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["webhook_url"].endswith("/webhooks/telegram/dashen")

    db_session.expire_all()
    bank = db_session.get(Bank, dashen_bank.id)
    assert bank.telegram_bot_token == "a-genuinely-valid-token-shape"
    assert bank.telegram_webhook_secret
