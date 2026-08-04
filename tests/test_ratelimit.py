from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist.ratelimit import SlidingWindowLimiter


def test_limiter_admits_up_to_max_then_blocks() -> None:
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
    assert [limiter.allow("k") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("other-key") is True  # independent keys


def test_limiter_window_expiry() -> None:
    limiter = SlidingWindowLimiter(max_events=1, window_seconds=0.01)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    import time

    time.sleep(0.02)
    assert limiter.allow("k") is True


def test_limiter_zero_disables() -> None:
    limiter = SlidingWindowLimiter(max_events=0)
    assert all(limiter.allow("k") for _ in range(100))


@pytest.fixture()
def strict_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("BANKASSIST_DATABASE_URL", f"sqlite:///{tmp_path}/rl.db")
    monkeypatch.setenv("BANKASSIST_CHAT_RATE_PER_IP", "3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from bankassist import config, db

    config.reset_settings()
    db.reset_engine()

    from bankassist.api import app

    with TestClient(app) as test_client:
        yield test_client

    db.reset_engine()
    config.reset_settings()


def test_chat_endpoint_returns_429_over_limit(strict_client: TestClient) -> None:
    from bankassist.seed import seed

    seed()
    statuses = [
        strict_client.post("/chat/demo", json={"message": "hello"}).status_code
        for _ in range(5)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert set(statuses[3:]) == {429}
