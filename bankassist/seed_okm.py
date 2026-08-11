"""OKM Phase 3 — "Ask OKM": an internal tenant over the fleet's own docs.

    python -m bankassist.seed_okm --source /path/to/olink-knowledge/content

`--source` is a local checkout of `olink-knowledge`'s synced `content/`
directory (run `python scripts/sync_docs.py` there first — this script does
not clone anything itself, see docs/decisions/0015-ask-okm-is-a-pull.md for
why). Everything under it becomes a `Document` on the `okm` tenant: one per
markdown file, titled by its own `# H1` (or an explicit `title:` front-matter
line on the handful of landing pages that carry one), categorised by the
product folder it lives in.

Deliberately NOT wired into `deploy.yml`. Every other seed script in this
module runs on every deploy because it seeds fixed, hand-authored content —
this one ingests a *different repo's* live docs tree, which needs that repo
cloned and built first. Run it by hand, or from a manual
`workflow_dispatch` job, exactly like `scripts/faq_export.py` and
`scripts/prune_merged_branches.py` — this repo's established shape for "a
tool that needs access an automated deploy doesn't have."

**Re-run safe, and re-run REPLACES.** Unlike `seed_common.seed_prospect_bank`
(which never touches an existing tenant's documents — the demo tenants are
hand-curated, one seed is authoritative forever), this tenant's whole point
is to track the portal, so a re-run matches existing `Document` rows by
`title` within the tenant and overwrites `content`/`category`/`source_url`,
precisely the same rule `POST /admin/api/{slug}/ingest/commit` already uses
for a human re-importing an updated page (api.py, `ingest_commit`). A file
removed from the source is left in place rather than deleted — a stale page
is a worse failure mode for an internal Q&A tool than a missing one, and the
alternative (delete-then-reinsert every run) would also spuriously bump
`updated_at` and rebuild every chunk on every run for content that didn't
change.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import get_engine, init_db
from .models import Bank, Document
from .retrieval import reindex_document
from .roles import ensure_builtin_roles

OKM_SLUG = "okm"

_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n\n?", re.DOTALL)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TITLE_LINE = re.compile(r'^title:\s*"(.+?)"\s*$', re.MULTILINE)


def parse_markdown(path: Path, root: Path) -> tuple[str, str, str]:
    """Return (title, category, content) for one markdown file.

    Pure function, no I/O beyond the read already required to call it — kept
    separate from the DB-writing loop below so it has a unit test that needs
    no database.
    """
    raw = path.read_text(encoding="utf-8")
    front_match = _FRONT_MATTER.match(raw)
    title_match = _TITLE_LINE.search(raw) if front_match else None
    body = raw[front_match.end() :] if front_match else raw

    if title_match:
        title = title_match.group(1)
    else:
        h1 = _H1.search(body)
        title = h1.group(1).strip() if h1 else path.stem.replace("-", " ").title()

    rel = path.relative_to(root)
    # content/<product>/<...>/file.md -> "<product>" for a top-level page,
    # "<product>/<subfolder>" for anything inside decisions/runbooks/etc, so
    # a category groups a product's ADRs together the same way the portal's
    # own sidebar does, without inventing a taxonomy this script would own.
    parts = rel.parts[:-1]
    category = "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "okm")

    return title, category, body.strip()


def _iter_markdown(source: Path) -> list[Path]:
    return sorted(p for p in source.rglob("*.md") if p.is_file())


def seed_okm(source: Path, *, ensure_tenant: bool = True) -> dict[str, int]:
    """Ingest every markdown file under `source` into the `okm` tenant.

    Returns {"created": n, "updated": n, "seen": n} — `seen` is the file
    count found, so a caller can sanity-check it against what they expected
    without a second query.
    """
    if not source.is_dir():
        # rglob on a missing path silently yields nothing rather than
        # raising, which here would read as "0 documents found" — a much
        # worse failure than a clear error, since it would also happily
        # leave every existing Document row untouched (the "removed pages
        # stay in place" contract) and look like a successful no-op sync.
        raise FileNotFoundError(f"not a directory: {source}")
    init_db()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as db:
        bank = db.execute(select(Bank).where(Bank.slug == OKM_SLUG)).scalar_one_or_none()
        if bank is None:
            if not ensure_tenant:
                raise SystemExit(f"tenant {OKM_SLUG!r} does not exist and ensure_tenant=False")
            bank = Bank(
                slug=OKM_SLUG,
                name="OKM — Ask the Fleet",
                short_name="Ask OKM",
                primary_color="#7c3aed",
                # Not a bank at all, so the ATM/PIN-shaped general-knowledge
                # fallback in llm.answer_from_general_knowledge() would never
                # usefully fire here — off is the correct and conservative
                # default, not a loosened one.
                allow_general_knowledge=False,
                disclaimer=(
                    "Internal tool — Olink staff only. Answers are drawn from "
                    "the OKM portal's aggregated product docs, never invented; "
                    "an unanswered question here means the docs don't say, not "
                    "that nobody was asked."
                ),
            )
            db.add(bank)
            db.flush()
            ensure_builtin_roles(db, bank.id)

        existing = {
            row.title: row
            for row in db.execute(
                select(Document).where(Document.bank_id == bank.id)
            ).scalars().all()
        }

        files = _iter_markdown(source)
        created = updated = 0
        for path in files:
            title, category, content = parse_markdown(path, source)
            if not content:
                continue  # an empty page teaches the assistant nothing
            source_url = str(path.relative_to(source))
            doc = existing.get(title)
            if doc is None:
                doc = Document(
                    bank_id=bank.id, title=title, content=content,
                    category=category, language="en", source_url=source_url,
                )
                db.add(doc)
                db.flush()
                created += 1
            else:
                doc.content = content
                doc.category = category
                doc.source_url = source_url
                updated += 1
            reindex_document(db, doc)

        db.commit()
        return {"created": created, "updated": updated, "seen": len(files)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, type=Path,
        help="local path to olink-knowledge's synced content/ directory",
    )
    args = parser.parse_args()
    if not args.source.is_dir():
        print(f"not a directory: {args.source}")
        return 2
    result = seed_okm(args.source)
    print(
        f"okm tenant: {result['seen']} files seen, "
        f"{result['created']} created, {result['updated']} updated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
