"""`/health` must be able to tell "running" from "working".

Prompted by a production incident, and **not fixed by it** — which is the
first thing to be clear about. Every login on every tenant failed because the
four seeded tenants hold no user accounts. The database was reachable
throughout, so the probe added here would have said `db: true` and `ok` right
through the outage.

What the incident exposed is narrower and still worth closing: a route the
README and DEPLOY.md both point at for "is this working" took no database
session at all, so it could report that a process was alive and nothing more.
A database that dies *after* startup was invisible here. One that is dead
*before* startup already fails loudly — `init_db()` runs in the lifespan and
the process exits rather than serving.

Two properties, and the second is the one that is easy to get wrong in the
other direction.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

# An address that cannot resolve and cannot belong to anyone: `.invalid` is
# reserved by RFC 2606 for exactly this. The first draft used a real-looking
# bank address, which a secret scanner flagged as a hardcoded credential — and
# it was right for a better reason than pattern matching. That address turned
# out to name a live account in a different system, and a test asserting a
# login FAILS is the last place a real one belongs.
NO_SUCH_ACCOUNT = {
    "email": "nobody@example.invalid",
    "password": "this-account-does-not-exist",
}


def test_health_reports_a_reachable_database(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["db"] is True
    assert body["status"] == "ok"


def test_health_says_degraded_when_the_database_is_gone(client: TestClient) -> None:
    """The whole point: the failure must be visible in the response.

    Simulated at the session rather than by stopping a server, because the
    fact under test is "a query did not land", however it failed to land.
    """
    from bankassist import api

    with patch.object(
        api.Session, "execute", side_effect=RuntimeError("connection refused")
    ):
        body = client.get("/health").json()

    assert body["db"] is False, "a dead database must not read as healthy"
    assert body["status"] == "degraded"


def test_a_dead_database_is_still_http_200(client: TestClient) -> None:
    """Deliberately, and this is the half that would bite if reversed.

    CI's container check runs `curl -fs .../health`, and a platform readiness
    probe reads the status code too. A 5xx here would restart or fail a
    revision whose process is fine and whose dependency is not — a diagnostic
    turned into an outage amplifier. The answer belongs in the body.
    """
    from bankassist import api

    with patch.object(
        api.Session, "execute", side_effect=RuntimeError("connection refused")
    ):
        r = client.get("/health")

    assert r.status_code == 200, (
        "health must not fail the request when its dependency is down — CI "
        "and readiness probes both read this status code"
    )


def test_health_is_never_cached(client: TestClient) -> None:
    """Unchanged, and re-asserted here because the new field makes it matter
    more: a cached `db: true` outlives the outage it was meant to reveal."""
    r = client.get("/health")
    assert "no-store" in r.headers["Cache-Control"]


def test_the_probe_does_not_leak_why(client: TestClient) -> None:
    """A public route. Every way a database can be unreachable is the same
    fact to a caller; the detail belongs in the logs."""
    from bankassist import api

    with patch.object(
        api.Session, "execute", side_effect=RuntimeError("password authentication failed")
    ):
        body = client.get("/health").json()

    assert "password" not in str(body).lower()
    assert set(body) == {"status", "llm", "db", "llm_ready", "revision", "instance"}


def test_a_seeded_tenant_has_no_accounts(client: TestClient, demo_bank: Any) -> None:
    """The incident itself, pinned.

    The seeds create documents and roles and deliberately no users — a seeded
    default account with a known password would be far worse. That is correct
    and it is also why email-and-password login cannot work until somebody
    bootstraps the first administrator through the admin token (ADR-0031).

    This test exists so the fact is written down where the next person meets
    it, rather than rediscovered from a locked-out sign-in screen.
    """
    r = client.post("/admin/api/demo/login", json=NO_SUCH_ACCOUNT)
    assert r.status_code == 401, "a seeded tenant has no accounts to sign in with"
