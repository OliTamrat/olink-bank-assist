"""Read a corrected curated-answer sheet back into the database.

    python scripts/faq_import.py cbe             # show what would change
    python scripts/faq_import.py cbe --write     # apply it

The other half of `faq_export.py`, which has referred to this file since the
day it was written. Without it the loop had no return leg: a bank's answers
could be exported and translated and there was no way to get them back in.

**Dry run by default, and that is not politeness.** Everywhere else in this
product a wrong string is a wrong label. A curated answer is served
*verbatim, with no retrieval and no model call* — it is the one path with no
gate after it, so whatever this writes is exactly what a customer reads.
Printing the diff first costs a second.

What it refuses to do:

  * **Write a language whose question cell is empty.** A half-filled row is
    the normal state of a sheet mid-review, not an instruction to blank an
    answer that already exists.
  * **Create a row from a key it has never seen.** The `key` column is a
    `source_faq_id`, not free text; a value that matches nothing is a
    corrupted paste, and inventing an answer from it is the worst possible
    response.
  * **Import an answer with no question, or a question with no answer.** Both
    halves are served together and half a pair is not publishable.
  * **Publish anything.** Everything it writes lands as a **draft**, whatever
    the sheet's status column says. A translation arriving straight into the
    live path — in a language nobody on the team reads — is exactly the
    failure the review step exists to prevent. Approving is a separate,
    deliberate act in the admin panel.

Reads the `⏎` marker `faq_export.py` writes for a newline inside a cell and
puts the real line break back; a bulleted eligibility list flattened to one
line is a different answer from the one the bank approved.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from bankassist import faq  # noqa: E402
from bankassist.db import get_engine  # noqa: E402
from bankassist.i18n import SUPPORTED_LANGUAGES  # noqa: E402
from bankassist.models import Bank, Faq  # noqa: E402
from scripts.faq_export import NEWLINE  # noqa: E402

DRAFT = "draft"


def uncell(text: str) -> str:
    return text.replace(NEWLINE, "\n").strip()


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    write = "--write" in argv
    if len(args) != 1:
        print("usage: python scripts/faq_import.py <bank-slug> [--write]")
        return 2
    slug = args[0]

    src = Path(__file__).resolve().parent.parent / "review" / f"faq-{slug}.tsv"
    if not src.exists():
        print(f"no {src} — run scripts/faq_export.py {slug} first")
        return 1

    with src.open(encoding="utf-8-sig") as fh:
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    header, body = rows[0], rows[1:]

    # Columns are matched by the language code that opens each header cell,
    # so a reviewer reordering or renaming columns in a spreadsheet cannot
    # silently write Amharic into the Somali column.
    col = {}
    for i, cell in enumerate(header):
        code = cell.split()[0].strip().lower() if cell.strip() else ""
        if code in SUPPORTED_LANGUAGES:
            col[code] = i
    missing_cols = [lang for lang in SUPPORTED_LANGUAGES if lang not in col]
    if missing_cols:
        print(f"the sheet has no column for: {missing_cols}")
        return 1
    try:
        field_at = header.index("field")
    except ValueError:
        print("the sheet has no `field` column — is this a faq export?")
        return 1

    db = sessionmaker(bind=get_engine(), expire_on_commit=False)()
    bank = db.execute(select(Bank).where(Bank.slug == slug)).scalars().first()
    if bank is None:
        print(f"no such bank: {slug}")
        return 1

    existing = db.execute(select(Faq).where(Faq.bank_id == bank.id)).scalars().all()
    by_group: dict[str, dict[str, Faq]] = {}
    for row in existing:
        by_group.setdefault(row.source_faq_id or row.id, {})[row.language] = row

    # The sheet writes a question row and an answer row per group, in that
    # order, so they are paired back up before anything is written — an
    # answer with no question is not publishable and neither is the reverse.
    pending: dict[tuple[str, str], dict[str, str]] = {}
    group_order: list[str] = []
    current: str | None = None
    for row in body:
        row = row + [""] * (len(header) - len(row))
        field = row[field_at].strip()
        if field == "question":
            # A question row opens a group; the answer row beneath it belongs
            # to the same one and carries no label of its own.
            current = None
            for lang in SUPPORTED_LANGUAGES:
                value = uncell(row[col[lang]])
                if not value:
                    continue
                anchor = value if current is None else current
                current = anchor
            if current is None:
                continue
            group_order.append(current)
        if current is None:
            continue
        for lang in SUPPORTED_LANGUAGES:
            value = uncell(row[col[lang]])
            if value:
                pending.setdefault((current, lang), {})[field] = value

    # Match each sheet group back to a database group by its English question,
    # which is the column the sheet tells reviewers to leave alone.
    english_to_group = {}
    for gid, langs in by_group.items():
        en = langs.get("en")
        if en is not None:
            english_to_group[en.question.strip()] = gid

    created = updated = skipped = 0
    unmatched: list[str] = []
    for gid_key in group_order:
        group = english_to_group.get(gid_key)
        if group is None:
            unmatched.append(gid_key[:60])
            continue
        for lang in SUPPORTED_LANGUAGES:
            pair = pending.get((gid_key, lang))
            if not pair:
                continue
            question, answer = pair.get("question", ""), pair.get("answer", "")
            if not question or not answer:
                skipped += 1
                print(f"  [{lang}] half a pair, skipped: {(question or answer)[:56]!r}")
                continue
            row = by_group[group].get(lang)
            if row is None:
                created += 1
                print(f"  + [{lang}] {question[:60]}")
                if write:
                    db.add(Faq(
                        bank_id=bank.id, language=lang, question=question,
                        answer=answer, status=DRAFT,
                        lookup=faq.key(question, lang),
                        source_faq_id=None if lang == "en" else group,
                    ))
            elif row.question != question or row.answer != answer:
                updated += 1
                print(f"  ~ [{lang}] {question[:60]}")
                if write:
                    row.question, row.answer = question, answer
                    # The key is derived from the question, so correcting the
                    # wording has to move the row with it or the answer stays
                    # findable only under what it used to say.
                    row.lookup = faq.key(question, lang)
                    # Back to draft: an edited answer has not been approved in
                    # its new wording, and the old approval was of the old
                    # words. Re-approving is one click and it is the click
                    # that means something.
                    row.status = DRAFT

    if unmatched:
        print(f"\n{len(unmatched)} sheet rows matched no existing answer:")
        for u in unmatched[:10]:
            print(f"    {u}")
        print("  (the English question column is the key — leave it unedited)")

    print(
        f"\n{created} to create, {updated} to update, {skipped} skipped"
        f"{' — nothing written, pass --write' if not write else ''}"
    )
    if write:
        db.commit()
        print("written as DRAFTS — approve them in the admin panel to go live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
