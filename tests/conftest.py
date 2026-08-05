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

    from bankassist import config, db

    config.reset_settings()
    db.reset_engine()

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
