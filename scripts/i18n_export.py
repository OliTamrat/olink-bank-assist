"""Write every assistant string to a TSV a native speaker can correct.

    python scripts/i18n_export.py            # -> review/strings.tsv

One row per string, one column per language, plus the context a translator
needs to get it right rather than merely accurate. Generated from
strings.json every time, so the sheet cannot drift from what is deployed.

TSV rather than CSV because Ge'ez text is full of commas in ordinary use and
quoting rules are the commonest way a review sheet arrives corrupted.

A tab or a newline inside a cell would end the column or the row early, so
both are escaped to a literal `\\t` and `\\n`, and a backslash to `\\\\` so the
escaping is reversible. `i18n_import.py` reverses it on the way back.

This is not hypothetical tidiness. The original version refused to write at
all if it met either, on the stated assumption that neither ever appears — and
`greeting` and `greeting_named` carry a blank line and the language-picker row
in **all six languages**, so the script had never once produced a file. The
loop CLAUDE.md names in rule 2b for reviewing what the assistant says was
unrunnable, and went unnoticed because `build_review_workbook.py` covers the
same strings and works.

Opens in Excel, Google Sheets and LibreOffice. The BOM is what makes Excel
read it as UTF-8 instead of mojibake — without it Amharic arrives as garbage
and the reviewer's first impression is that the tool is broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bankassist.i18n import (  # noqa: E402
    _ADMIN_STRINGS,
    _NOTES,
    _STRINGS,
    _UI_STRINGS,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
)

OUT = Path(__file__).resolve().parent.parent / "review" / "strings.tsv"


def escape(cell: str) -> str:
    """Make a cell safe to sit between two tabs and a newline.

    Backslash first, or escaping the others would corrupt a value that already
    contained one — there are none today, and a round trip that only works
    while that stays true is not a round trip.
    """
    return cell.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def main() -> int:
    header = ["key", "what it is for / what to preserve"]
    header += [f"{lang} ({LANGUAGE_NAMES[lang]})" for lang in SUPPORTED_LANGUAGES]
    header.append("reviewer notes")

    rows = [header]
    for key in _STRINGS["en"]:
        row = [key, _NOTES.get(key, "")]
        for lang in SUPPORTED_LANGUAGES:
            row.append(_STRINGS[lang].get(key, ""))
        row.append("")
        rows.append(row)

    # The interface's own labels, in the same sheet rather than a third one.
    # They are a different job from the assistant's voice — length and
    # convention rather than tone — but a reviewer opening two files corrects
    # one and forgets the other, and the rule is that a feature ships in five
    # languages or it has not shipped.
    rows.append([""] * len(header))
    rows.append(["— interface labels below —"] + [""] * (len(header) - 1))
    for key in _UI_STRINGS["en"]:
        row = [f"ui.{key}", "Button, label or placeholder. Keep it short —"
                            " it has to fit the same space as the English."]
        for lang in SUPPORTED_LANGUAGES:
            row.append(_UI_STRINGS[lang].get(key, ""))
        row.append("")
        rows.append(row)

    # The admin panel, which had grown to a hundred and ninety-eight strings
    # without ever reaching this sheet. A reviewer could correct every word a
    # customer reads and not one word the staff read.
    rows.append([""] * len(header))
    rows.append(["— admin panel labels below —"] + [""] * (len(header) - 1))
    for key in _ADMIN_STRINGS["en"]:
        row = [f"admin.{key}",
               "Bank staff, not customers. Keep it short — it has to fit the"
               " same space as the English. Leave any {placeholder} exactly"
               " as it is; it is replaced with a number or a name."]
        for lang in SUPPORTED_LANGUAGES:
            row.append(_ADMIN_STRINGS[lang].get(key, ""))
        row.append("")
        rows.append(row)

    rows = [[escape(cell) for cell in row] for row in rows]

    # Belt and braces: after escaping nothing raw can remain, so this fires
    # only if `escape` itself is ever broken — which is worth catching loudly
    # rather than writing a sheet that silently loses a column.
    for row in rows:
        for cell in row:
            if "\t" in cell or "\n" in cell:
                print(f"escaping failed to clear a cell: {cell!r}")
                return 1

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="\n") as fh:
        for row in rows:
            fh.write("\t".join(row) + "\n")

    print(f"wrote {OUT} — {len(rows) - 1} strings x {len(SUPPORTED_LANGUAGES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
