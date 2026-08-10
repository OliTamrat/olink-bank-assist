from __future__ import annotations

import os
from collections.abc import Iterator

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


os.environ.setdefault("BANKASSIST_DATABASE_URL", "sqlite:///:memory:")
