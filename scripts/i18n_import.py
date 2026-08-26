"""Read the corrected TSV back into strings.json.

    python scripts/i18n_import.py                    # show what would change
    python scripts/i18n_import.py --write            # apply it

Defaults to a dry run and prints a per-string diff, because this overwrites
the deployed wording of every reply the assistant gives in five languages and
that deserves a look before it happens rather than after.

What it refuses to do, and why each one is a real failure mode rather than a
hypothetical:

  * Add a key that isn't already in strings.json. A row typed into the sheet
    by hand is a typo far more often than a genuine new string, and the code
    would never look it up.
  * Drop a key that is missing from the sheet. A reviewer working through 18
    rows deletes one by accident; losing a reply's wording silently is worse
    than making them re-export.
  * Accept a translation whose {placeholders} differ from English. t() calls
    .format(), so a lost {bank} raises KeyError at runtime — in production,
    on the customer's turn, in the one language nobody on the team reads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bankassist.i18n import (  # noqa: E402
    ADMIN_STRINGS_PATH,
    STRINGS_PATH,
    SUPPORTED_LANGUAGES,
    UI_STRINGS_PATH,
)

SRC = Path(__file__).resolve().parent.parent / "review" / "strings.tsv"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# The sheet carries three tables, distinguished by a key prefix, and this
# script used to know about one of them. Every `ui.` and `admin.` row — of 551
# rows, 528 of them — was rejected as an unknown key, so a reviewer could
# correct every word the staff read and have none of it land. Longest prefix
# first: "" matches everything, so it has to be tried last.
TABLES: tuple[tuple[str, Path], ...] = (
    ("admin.", ADMIN_STRINGS_PATH),
    ("ui.", UI_STRINGS_PATH),
    ("", STRINGS_PATH),
)


def unescape(cell: str) -> str:
    """Reverse `i18n_export.escape`.

    Scanned rather than three chained `.replace()` calls, which get `\\n` — a
    real backslash followed by an n — wrong in both orders.
    """
    out: list[str] = []
    i = 0
    while i < len(cell):
        if cell[i] == "\\" and i + 1 < len(cell):
            nxt = cell[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(cell[i])
        i += 1
    return "".join(out)


def main() -> int:
    write = "--write" in sys.argv
    if not SRC.exists():
        print(f"no {SRC} — run scripts/i18n_export.py first")
        return 1

    with SRC.open(encoding="utf-8-sig") as fh:
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]

    header, body = rows[0], rows[1:]
    # Match columns by the language code that starts each header cell, so
    # reordering or renaming columns in a spreadsheet cannot silently write
    # Amharic into the Somali slot.
    col = {}
    for lang in SUPPORTED_LANGUAGES:
        found = [i for i, h in enumerate(header) if h.split(" ")[0] == lang]
        if len(found) != 1:
            print(f"expected exactly one column for {lang!r}, found {len(found)}")
            return 1
        col[lang] = found[0]

    tables: dict[str, dict[str, dict[str, str]]] = {
        prefix: json.loads(path.read_text(encoding="utf-8")) for prefix, path in TABLES
    }
    known = {prefix: set(tables[prefix]["en"]) for prefix, _ in TABLES}
    seen: dict[str, set[str]] = {prefix: set() for prefix, _ in TABLES}
    changes: list[tuple[str, str, str, str, str]] = []
    problems: list[str] = []

    for row in body:
        key = row[0].strip()
        if not key:
            continue
        # The separator rows the export writes between tables. They are
        # signposts for a human reading the sheet, not data.
        if key.startswith("—"):
            continue
        prefix = next(p for p, _ in TABLES if key.startswith(p))
        bare = key[len(prefix):]
        if bare not in known[prefix]:
            problems.append(f"unknown key {key!r} — not in the {prefix or 'assistant'} table")
            continue
        seen[prefix].add(bare)
        english = unescape(row[col["en"]]).strip()
        expected = set(_PLACEHOLDER.findall(english))
        for lang in SUPPORTED_LANGUAGES:
            # Stripped to decide whether the cell is EMPTY, never to decide
            # what it says. `couldnt_connect` ends in a space in all six
            # languages because the panel writes it as
            # `A("couldnt_connect") + err.message`; stripping the value
            # silently turned six error messages into "Couldn't
            # connect:Network error". Whitespace now survives the TSV intact
            # (see `escape`), so preserving it costs nothing and losing it
            # cost a round trip nobody could see.
            new = unescape(row[col[lang]]) if col[lang] < len(row) else ""
            if not new.strip():
                problems.append(f"{key} [{lang}] is empty")
                continue
            got = set(_PLACEHOLDER.findall(new))
            if got != expected:
                problems.append(
                    f"{key} [{lang}] placeholders {sorted(got)} != English {sorted(expected)}"
                )
                continue
            old = tables[prefix][lang].get(bare, "")
            if old != new:
                changes.append((prefix, bare, lang, old, new))

    for prefix, _ in TABLES:
        for bare in sorted(known[prefix] - seen[prefix]):
            problems.append(
                f"{prefix}{bare} is missing from the sheet — refusing to drop it"
            )

    if problems:
        print(f"{len(problems)} problem(s), nothing written:")
        for p in problems:
            print("  -", p)
        return 1

    if not changes:
        print("no changes")
        return 0

    print(f"{len(changes)} change(s):")
    for prefix, bare, lang, old, new in changes:
        print(f"\n  {prefix}{bare} [{lang}]\n    - {old}\n    + {new}")

    if not write:
        print("\ndry run — re-run with --write to apply")
        return 0

    touched = {prefix for prefix, _, _, _, _ in changes}
    for prefix, bare, lang, _old, new in changes:
        tables[prefix][lang][bare] = new
    for prefix, path in TABLES:
        # Only the files that actually changed. Rewriting an untouched table
        # would churn the diff and invite a reviewer to skim past the one file
        # that did change.
        if prefix not in touched:
            continue
        with path.open("w", encoding="utf-8") as fh:
            json.dump(tables[prefix], fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
