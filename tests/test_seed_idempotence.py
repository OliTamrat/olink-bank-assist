"""Re-seeding an existing tenant must converge on the intended state.

Every deployment runs the seeds against a database where the banks already
exist, so the early-return path IS the production path. A value set only in
the create branch is a value that is never set in production — which is
exactly what happened to `teller_enabled`: the showcase tenant shipped with
its flagship feature switched off and nothing failed, the button just never
appeared.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist.models import Bank


def test_reseeding_switches_live_teller_back_on_for_the_demo_tenant(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The regression. Migration 0018 backfills the flag to false for every
    bank that already exists, and the demo tenant always already exists."""
    from bankassist.seed import seed

    bank = db_session.execute(
        select(Bank).where(Bank.slug == "demo")
    ).scalar_one()
    bank.teller_enabled = False
    db_session.commit()

    seed()

    db_session.expire_all()
    assert db_session.execute(
        select(Bank).where(Bank.slug == "demo")
    ).scalar_one().teller_enabled is True


def test_reseeding_does_not_switch_it_on_for_a_prospect_tenant(
    client: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """Only the demo tenant is ours to force on. A prospect's tenant must not
    grow a live-video button because somebody ran a deploy — the whole reason
    the flag defaults off is that offering it is a decision a bank makes."""
    from bankassist.seed_cbe import seed as seed_cbe

    seed_cbe()

    db_session.expire_all()
    assert db_session.execute(
        select(Bank).where(Bank.slug == "cbe")
    ).scalar_one().teller_enabled is False


def test_reseeding_adds_documents_the_tenant_does_not_have_yet(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The third occurrence of the same trap, caught before shipping.

    Documents were only created in the branch that CREATES the bank, so a new
    article added to the seed reached production and did nothing — every
    deployment already has a demo bank. The foreign-exchange article written
    because "the assistant has no answer for a basic exchange rate question"
    would have deployed green and changed nothing at all.
    """
    from bankassist.models import Document
    from bankassist.seed import seed

    title = "Foreign Exchange and Currency"
    doc = db_session.execute(
        select(Document).where(
            Document.bank_id == demo_bank.id, Document.title == title
        )
    ).scalar_one()
    db_session.delete(doc)
    db_session.commit()

    seed()

    db_session.expire_all()
    assert db_session.execute(
        select(Document).where(
            Document.bank_id == demo_bank.id, Document.title == title
        )
    ).scalar_one_or_none() is not None


def test_reseeding_does_not_overwrite_an_edited_article(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A tenant may have edited an article in the admin panel. A deploy that
    silently replaced their wording with our seed copy would be far worse than
    a missing article — this adds what is absent and never argues with what is
    already there."""
    from bankassist.models import Document
    from bankassist.seed import seed

    doc = db_session.execute(
        select(Document).where(
            Document.bank_id == demo_bank.id, Document.title == "Savings Accounts"
        )
    ).scalar_one()
    doc.content = "The bank rewrote this themselves."
    db_session.commit()

    seed()

    db_session.expire_all()
    assert db_session.execute(
        select(Document).where(
            Document.bank_id == demo_bank.id, Document.title == "Savings Accounts"
        )
    ).scalar_one().content == "The bank rewrote this themselves."
