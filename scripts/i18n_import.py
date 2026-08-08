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

from bankassist.i18n import STRINGS_PATH, SUPPORTED_LANGUAGES  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "review" / "strings.tsv"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


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

    current: dict[str, dict[str, str]] = json.loads(STRINGS_PATH.read_text(encoding="utf-8"))
    known = set(current["en"])
    seen: set[str] = set()
    changes: list[tuple[str, str, str, str]] = []
    problems: list[str] = []

    for row in body:
        key = row[0].strip()
        if not key:
            continue
        if key not in known:
            problems.append(f"unknown key {key!r} — not in strings.json")
            continue
        seen.add(key)
        english = row[col["en"]].strip()
        expected = set(_PLACEHOLDER.findall(english))
        for lang in SUPPORTED_LANGUAGES:
            new = row[col[lang]].strip() if col[lang] < len(row) else ""
            if not new:
                problems.append(f"{key} [{lang}] is empty")
                continue
            got = set(_PLACEHOLDER.findall(new))
            if got != expected:
                problems.append(
                    f"{key} [{lang}] placeholders {sorted(got)} != English {sorted(expected)}"
                )
                continue
            old = current[lang].get(key, "")
            if old != new:
                changes.append((key, lang, old, new))

    for key in sorted(known - seen):
        problems.append(f"{key} is missing from the sheet — refusing to drop it")

    if problems:
        print(f"{len(problems)} problem(s), nothing written:")
        for p in problems:
            print("  -", p)
        return 1

    if not changes:
        print("no changes")
        return 0

    print(f"{len(changes)} change(s):")
    for key, lang, old, new in changes:
        print(f"\n  {key} [{lang}]\n    - {old}\n    + {new}")

    if not write:
        print("\ndry run — re-run with --write to apply")
        return 0

    for key, lang, _old, new in changes:
        current[lang][key] = new
    with STRINGS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"\nwrote {STRINGS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
