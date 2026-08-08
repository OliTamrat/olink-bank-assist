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

import os

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import get_engine, init_db
from .models import Bank, Document
from .retrieval import reindex_document
from .roles import ensure_builtin_roles


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
            # Seeded even for a tenant that already exists, and deliberately so.
            # This runs on every deploy, so a bank that somehow has no roles —
            # created before they existed, or restored from a partial backup —
            # heals on the next one instead of being a tenant where nobody can
            # sign in. Idempotent: a bank that has customised its own roles
            # keeps them untouched.
            ensure_builtin_roles(db, existing.id)
            db.commit()
            return existing, False
        bank = Bank(slug=slug, name=name, primary_color=primary_color, disclaimer=disclaimer)
        db.add(bank)
        db.flush()
        ensure_builtin_roles(db, bank.id)
        for spec in docs:
            doc = Document(bank_id=bank.id, **spec)
            db.add(doc)
            db.flush()
            reindex_document(db, doc)
        db.commit()
        return bank, True


def print_seed_summary(bank: Bank, created: bool, label: str, slug: str) -> None:
    """Report what a seed run did, without writing the admin token into CI logs.

    The seed scripts run on every deploy, so an unconditional
    `print(bank.admin_token)` puts every tenant's admin credential into the
    GitHub Actions log — readable by anyone with repo access and retained by
    GitHub. Printing locally is genuinely useful for development, so this
    suppresses only under CI (GitHub Actions sets CI=true) and points at
    `python -m bankassist.show_token` as the retrieval path.
    """
    status = "created" if created else "already exists"
    print(f"{label} {status}: {bank.name} (slug={bank.slug})")
    if os.environ.get("CI"):
        print(f"Admin token: [hidden in CI] — run `python -m bankassist.show_token {slug}`")
    else:
        print(f"Admin token: {bank.admin_token}")
    print(f"Widget:  http://localhost:8100/widget?bank={slug}")
    print("Admin:   http://localhost:8100/admin")
