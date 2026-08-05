"""Shared machinery for the per-bank prospect-demo seed scripts
(seed_cbe.py, seed_dashen.py, seed_awash.py, ...).

Each of those is a private pitch-demo prototype built from a real bank's
own public information, to show that bank's own team during a sales
meeting — never a live public product acting under a real institution's
name without their knowledge. The `disclaimer` this module generates is
mandatory, not optional, and is rendered as a persistent banner in the
widget (see `bankassist/static/widget.html`) for every prospect tenant.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import get_engine, init_db
from .models import Bank, Document
from .retrieval import reindex_document


def prospect_disclaimer(short_name: str, full_name: str) -> str:
    """Standard disclaimer text for a prospect-demo tenant. `short_name` is
    what a demo audience would call the bank in speech (e.g. "CBE");
    `full_name` is the full legal/display name for the second sentence."""
    return (
        f"Unofficial prototype built from {short_name}'s public information "
        f"for a product demo. Not affiliated with, endorsed by, or an "
        f"official channel of {full_name}."
    )


def seed_prospect_bank(
    *,
    slug: str,
    name: str,
    primary_color: str,
    disclaimer: str,
    docs: list[dict[str, str]],
) -> tuple[Bank, bool]:
    """Create a prospect-demo tenant if it doesn't already exist. Returns
    (bank, created) — created=False means it was already seeded, and `docs`
    was NOT re-applied (re-run the specific seed_<bank>.py's own update path
    if content changed, same as the existing seed.py/seed_cbe.py convention)."""
    init_db()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as db:
        existing = db.execute(select(Bank).where(Bank.slug == slug)).scalar_one_or_none()
        if existing is not None:
            return existing, False
        bank = Bank(slug=slug, name=name, primary_color=primary_color, disclaimer=disclaimer)
        db.add(bank)
        db.flush()
        for spec in docs:
            doc = Document(bank_id=bank.id, **spec)
            db.add(doc)
            db.flush()
            reindex_document(db, doc)
        db.commit()
        return bank, True
