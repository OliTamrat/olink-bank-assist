"""Write a bank's curated answers to a TSV a native speaker can correct.

    python scripts/faq_export.py dashen          # -> review/faq-dashen.tsv

Deliberately the same shape and the same workflow as `i18n_export.py`, so a
reviewer learns one process rather than two. Edit the language columns, leave
the first three alone, then `faq_import.py <slug> --write` reads it back —
as drafts, always, whatever the status column says.

**Why this exists rather than "ask the bank to translate it".** A hundred and
sixty answers in four more languages is six hundred and forty pieces of
writing. Nobody starts that from a blank sheet, so the languages never ship.
A machine draft is not the bank's word and is never served as one — it is a
first pass a native speaker can correct in an afternoon, which is the only
version of this that actually gets done.

One row per question, one column per language, and the answer text on the row
beneath it so a reviewer sees the question and its answer together rather than
scrolling between two sheets.

TSV rather than CSV because Ge'ez text is full of commas in ordinary use and
quoting rules are the commonest way a review sheet arrives corrupted. Tabs and
newlines inside a cell would silently lose a column, so they are replaced by a
visible marker rather than written raw — the reviewer can see where a line
break belongs and `faq_import.py` puts it back.

The BOM is what makes Excel read this as UTF-8 instead of mojibake. Without it
Amharic arrives as garbage and the reviewer's first impression is that the tool
is broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from bankassist import faq  # noqa: E402
from bankassist.db import get_engine  # noqa: E402
from bankassist.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES  # noqa: E402
from bankassist.models import Bank, Faq  # noqa: E402

# A line break a reviewer can see and a spreadsheet cannot corrupt. Answers are
# multi-line often enough — bulleted eligibility lists, prize tiers — that
# flattening them would change the text a customer reads.
NEWLINE = "⏎"


def cell(text: str) -> str:
    return text.replace("\t", " ").replace("\r\n", "\n").replace("\n", NEWLINE)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/faq_export.py <bank-slug>")
        return 2
    slug = argv[1]

    db = sessionmaker(bind=get_engine(), expire_on_commit=False)()
    bank = db.execute(select(Bank).where(Bank.slug == slug)).scalars().first()
    if bank is None:
        print(f"no such bank: {slug}")
        return 1

    # Group by the answer a row was translated FROM, falling back to its own
    # id for anything written directly. Grouping by the question text cannot
    # work: a translation is by definition a different string from its
    # original, so every language would land on its own row and the reviewer
    # would get five unrelated lines instead of one to correct.
    rows_by_key: dict[str, dict[str, Faq]] = {}
    for row in db.execute(
        select(Faq).where(Faq.bank_id == bank.id)
    ).scalars().all():
        rows_by_key.setdefault(row.source_faq_id or row.id, {})[row.language] = row

    header = ["question (en)", "status", "field"]
    header += [f"{lang} ({LANGUAGE_NAMES[lang]})" for lang in SUPPORTED_LANGUAGES]
    header.append("reviewer notes")
    out: list[list[str]] = [header]

    def sort_key(group_id: str) -> str:
        langs = rows_by_key[group_id]
        anchor = langs.get("en") or next(iter(langs.values()))
        return faq.normalise(anchor.question)

    for key in sorted(rows_by_key, key=sort_key):
        langs = rows_by_key[key]
        english = langs.get("en")
        label = english.question if english else next(iter(langs.values())).question
        status = english.status if english else "—"
        for field in ("question", "answer"):
            row = [cell(label) if field == "question" else "", status, field]
            for lang in SUPPORTED_LANGUAGES:
                held = langs.get(lang)
                row.append(cell(getattr(held, field)) if held else "")
            row.append("")
            out.append(row)

    OUT = Path(__file__).resolve().parent.parent / "review" / f"faq-{slug}.tsv"
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="\n") as fh:
        for row in out:
            fh.write("\t".join(row) + "\n")

    missing = sum(
        1
        for key in rows_by_key
        for lang in SUPPORTED_LANGUAGES
        if lang not in rows_by_key[key]
    )
    print(
        f"wrote {OUT} — {len(rows_by_key)} questions x "
        f"{len(SUPPORTED_LANGUAGES)} languages, {missing} cells still empty"
    )
    print(f"a line break inside an answer is written as {NEWLINE} — leave them in place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
