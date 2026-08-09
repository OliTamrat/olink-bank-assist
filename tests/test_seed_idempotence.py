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
