"""A rejected admin attempt has to be visible, and has to slow down.

Neither was true. The admin panel sits on the public internet behind a single
shared bearer token per tenant, and a credential-stuffing run against it left
no trace at all — no log line, no counter, nothing a bank's security review
could point at. The token is 192 bits so guessing it was never the realistic
threat; not knowing anyone tried is.

The rate limit counts FAILURES ONLY. That is the property most worth pinning:
a limiter that also counted successful calls would throttle an operator
working a busy handoff queue, which is a denial of service dressed up as a
security control — and it is exactly the kind of protection that gets turned
off in month two and never turned back on.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.testclient import TestClient

from bankassist.ratelimit import SlidingWindowLimiter


def _set_failure_limit(client: TestClient, n: int) -> None:
    client.app.state.admin_auth_limiter = SlidingWindowLimiter(n)  # type: ignore[attr-defined]


# --------------------------------------------------------------- logging


def test_a_bad_token_is_logged_without_the_token(
    client: TestClient, demo_bank: Any, caplog: Any
) -> None:
    """The attempted value is never recorded. It may be a real credential for
    another tenant — someone pasting the wrong one — and a log is the easiest
    place for a secret to end up somewhere nobody audits."""
    with caplog.at_level(logging.INFO):
        resp = client.get(
            "/admin/api/demo/handoffs", headers={"X-Admin-Token": "hunter2-wrong"}
        )
    assert resp.status_code == 401

    events = [r for r in caplog.records if r.getMessage() == "admin_auth_failed"]
    assert events, "a rejected attempt must leave a trace"
    fields = events[-1].extra_fields  # type: ignore[attr-defined]
    assert fields["bank"] == "demo"
    assert fields["reason"] == "bad_token"
    assert fields["token_present"] is True
    assert "hunter2-wrong" not in str(fields)


def test_a_missing_token_is_distinguishable_from_a_wrong_one(
    client: TestClient, demo_bank: Any, caplog: Any
) -> None:
    """A misconfigured client sends nothing; an attacker sends guesses. Both
    are 401 to the caller, and they should not look the same in the log — one
    is somebody's integration to fix, the other is somebody probing."""
    with caplog.at_level(logging.INFO):
        client.get("/admin/api/demo/handoffs")
    fields = [
        r for r in caplog.records if r.getMessage() == "admin_auth_failed"
    ][-1].extra_fields  # type: ignore[attr-defined]
    assert fields["token_present"] is False


def test_a_successful_call_logs_no_failure(
    client: TestClient, demo_bank: Any, caplog: Any
) -> None:
    """Otherwise the signal is buried in noise the first time anyone uses it."""
    with caplog.at_level(logging.INFO):
        resp = client.get(
            "/admin/api/demo/handoffs", headers={"X-Admin-Token": demo_bank.admin_token}
        )
    assert resp.status_code == 200
    assert not [r for r in caplog.records if r.getMessage() == "admin_auth_failed"]


# ----------------------------------------------------------- rate limit


def test_repeated_failures_are_rate_limited(client: TestClient, demo_bank: Any) -> None:
    _set_failure_limit(client, 3)
    codes = [
        client.get(
            "/admin/api/demo/handoffs", headers={"X-Admin-Token": f"guess-{i}"}
        ).status_code
        for i in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429], "a stuffing run must hit a wall"


def test_a_valid_token_is_never_throttled(client: TestClient, demo_bank: Any) -> None:
    """The property that keeps this switched on.

    An operator working a queue makes far more calls than any limit worth
    setting. If success counted toward it they would be locked out of their
    own console, and the control would be removed rather than tuned.
    """
    _set_failure_limit(client, 2)
    headers = {"X-Admin-Token": demo_bank.admin_token}
    for _ in range(25):
        assert client.get("/admin/api/demo/handoffs", headers=headers).status_code == 200


def test_a_locked_out_attacker_does_not_lock_out_the_real_admin(
    client: TestClient, demo_bank: Any
) -> None:
    """The counter is keyed per client IP, so exhausting it from one source
    must not deny the tenant access to their own dashboard — otherwise the
    control becomes the outage."""
    _set_failure_limit(client, 1)
    client.get("/admin/api/demo/handoffs", headers={"X-Admin-Token": "wrong"})
    assert client.get(
        "/admin/api/demo/handoffs", headers={"X-Admin-Token": "wrong"}
    ).status_code == 429

    ok = client.get(
        "/admin/api/demo/handoffs", headers={"X-Admin-Token": demo_bank.admin_token}
    )
    assert ok.status_code == 200, "a valid token must still work while failures are capped"


# ------------------------------------------------------ tenant probing


def test_an_unknown_slug_answers_exactly_like_a_wrong_token(
    client: TestClient, demo_bank: Any
) -> None:
    """A probe should not be able to tell a typo from a wrong credential."""
    unknown = client.get(
        "/admin/api/nosuchbank/handoffs", headers={"X-Admin-Token": "x"}
    )
    wrong = client.get("/admin/api/demo/handoffs", headers={"X-Admin-Token": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_an_unknown_slug_is_logged_with_its_own_reason(
    client: TestClient, demo_bank: Any, caplog: Any
) -> None:
    """Same response to the caller, different line in the log — someone
    sweeping slugs is a different event from someone guessing a token."""
    with caplog.at_level(logging.INFO):
        client.get("/admin/api/nosuchbank/handoffs", headers={"X-Admin-Token": "x"})
    fields = [
        r for r in caplog.records if r.getMessage() == "admin_auth_failed"
    ][-1].extra_fields  # type: ignore[attr-defined]
    assert fields["reason"] == "unknown_bank"
