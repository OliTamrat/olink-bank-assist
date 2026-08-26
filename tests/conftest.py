from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def client(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("BANKASSIST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # TestClient speaks http, and a Secure cookie is never sent over http — so
    # without this every session test fails at the second request with a 401
    # that looks like an auth bug rather than a transport one. Production
    # defaults to Secure; this is the explicit opt-out, and it lives here so a
    # test can never quietly disable it for the real app.
    monkeypatch.setenv("BANKASSIST_ADMIN_COOKIE_INSECURE", "1")

    from bankassist import config, db, index

    config.reset_settings()
    db.reset_engine()
    # The search index is a process-level cache keyed by bank id, and every
    # test builds a brand-new database. Ids are uuids so a collision is
    # vanishingly unlikely, but "vanishingly unlikely" is how you get one
    # flaky test a month that nobody can reproduce.
    index.clear()

    from bankassist.api import app

    with TestClient(app) as test_client:
        yield test_client

    db.reset_engine()
    config.reset_settings()


@pytest.fixture()
def db_session(client: TestClient) -> Iterator[Session]:
    from bankassist.db import get_engine

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def demo_bank(client: TestClient, db_session: Session) -> object:
    from bankassist.seed import seed

    bank, _ = seed()
    return bank


@pytest.fixture()
def cbe_bank(client: TestClient, db_session: Session) -> object:
    from bankassist.seed_cbe import seed as seed_cbe

    bank, _ = seed_cbe()
    return bank


@pytest.fixture()
def dashen_bank(client: TestClient, db_session: Session) -> object:
    from bankassist.seed_dashen import seed as seed_dashen

    bank, _ = seed_dashen()
    return bank


@pytest.fixture()
def awash_bank(client: TestClient, db_session: Session) -> object:
    from bankassist.seed_awash import seed as seed_awash

    bank, _ = seed_awash()
    return bank


@pytest.fixture()
def second_bank(client: TestClient, db_session: Session) -> object:
    from bankassist.models import Bank, Document
    from bankassist.retrieval import reindex_document

    bank = Bank(slug="other", name="Other Bank")
    db_session.add(bank)
    db_session.flush()
    doc = Document(
        bank_id=bank.id,
        title="Secret Gold Account",
        content=(
            "The Secret Gold Account is exclusive to Other Bank. Minimum opening "
            "balance 1,000,000 birr. Includes a personal golden concierge."
        ),
    )
    db_session.add(doc)
    db_session.flush()
    reindex_document(db_session, doc)
    db_session.commit()
    return bank


@pytest.fixture()
def bare_bank(client: TestClient, db_session: Session) -> object:
    """A tenant with nothing in it — no documents, no traffic, default colour.

    What a pilot bank actually is on the morning somebody first signs in, and
    the state every other fixture skips past: `demo_bank` and the prospect
    tenants all arrive pre-seeded, so nothing in the suite had ever rendered
    the product empty. That is how a dashboard of zeroes with no explanation
    survived to be found in a browser instead.

    Roles are seeded because a tenant created through the product gets them;
    a bank row inserted without them cannot create its first administrator.
    """
    from bankassist.models import Bank
    from bankassist.roles import ensure_builtin_roles

    bank = Bank(slug="bare", name="Bare Bank")
    db_session.add(bank)
    db_session.flush()
    ensure_builtin_roles(db_session, bank.id)
    db_session.commit()
    return bank


os.environ.setdefault("BANKASSIST_DATABASE_URL", "sqlite:///:memory:")


# ---------------------------------------------------------------- users
#
# The break-glass token can create a tenant's FIRST user and nothing else
# (see `_token_is_still_a_credential` in api.py — retiring the MFA bypass,
# founder decision 2026-08-14). Before that, every test that wanted three
# colleagues made three token calls, because the token was a standing power
# to mint administrators. That is precisely the power that was removed.
#
# So this mirrors what a real tenant does: bootstrap one administrator with
# the token, then create everyone else as that administrator. Tests get the
# same convenience they had, and none of them can quietly reassert a
# capability the product no longer has.

# The first user created in each bank, remembered so later calls can act as
# them. Keyed by bank id; the fixtures build a fresh database per test, so
# this never leaks between them.
_FIRST_ADMIN: dict[str, tuple[str, str]] = {}


def create_user(
    client: TestClient,
    bank: Any,
    email: str,
    *,
    password: str,
    role: str = "operator",
    slug: str = "demo",
) -> dict[str, Any]:
    """Create a user the way the product allows, whichever user this is.

    The token creates the FIRST user and nothing else, so the test's own first
    user claims that door and every later one is created by them — which is
    exactly what a real tenant does.

    No phantom bootstrap account is injected. An earlier version of this
    helper quietly added its own admin to every bank so it always had a
    session to work with, and that broke every test that counts or enumerates
    people: a fixture inventing an extra colleague is a worse problem than the
    one it solved.

    Consequence, and it is a fair one: **the first user a test creates must be
    an admin**, because somebody has to be able to create the rest. That is
    true of the product too.
    """
    token_headers = {"X-Admin-Token": bank.admin_token}
    first = client.post(
        f"/admin/api/{slug}/users",
        headers=token_headers,
        json={"email": email, "password": password, "role": role},
    )
    if first.status_code == 201:
        _FIRST_ADMIN.setdefault(bank.id, (email, password))
        data: dict[str, Any] = first.json()
        return data

    assert first.status_code == 403, first.text
    known = _FIRST_ADMIN.get(bank.id)
    assert known, (
        "the bootstrap door is shut and no user was created through this "
        "helper, so there is nobody to create colleagues as. Create the "
        "tenant's first (admin) user with create_user() before the others."
    )
    admin = TestClient(client.app)
    signed_in = admin.post(
        f"/admin/api/{slug}/login", json={"email": known[0], "password": known[1]}
    )
    assert signed_in.status_code == 200, (
        f"could not sign in as {known[0]} to create {email}: {signed_in.text}"
    )
    resp = admin.post(
        f"/admin/api/{slug}/users",
        json={"email": email, "password": password, "role": role},
    )
    assert resp.status_code == 201, (
        f"{known[0]} could not create {email} — the first user a test creates "
        f"must be an admin: {resp.text}"
    )
    out: dict[str, Any] = resp.json()
    return out


@pytest.fixture(autouse=True)
def _forget_first_admins() -> Iterator[None]:
    """Bank ids are seeded deterministically, so without this a stale entry
    from a previous test would be consulted against a fresh database — and the
    password would silently be the wrong one."""
    _FIRST_ADMIN.clear()
    yield
    _FIRST_ADMIN.clear()
