"""Write every assistant string to a TSV a native speaker can correct.

    python scripts/i18n_export.py            # -> review/strings.tsv

One row per string, one column per language, plus the context a translator
needs to get it right rather than merely accurate. Generated from
strings.json every time, so the sheet cannot drift from what is deployed.

TSV rather than CSV because Ge'ez text is full of commas in ordinary use and
quoting rules are the commonest way a review sheet arrives corrupted. Tabs
never appear inside these strings; a check below fails the export if one ever
does rather than writing a file that silently loses a column.

Opens in Excel, Google Sheets and LibreOffice. The BOM is what makes Excel
read it as UTF-8 instead of mojibake — without it Amharic arrives as garbage
and the reviewer's first impression is that the tool is broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bankassist.i18n import (  # noqa: E402
    _NOTES,
    _STRINGS,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
)

OUT = Path(__file__).resolve().parent.parent / "review" / "strings.tsv"


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

    for row in rows:
        for cell in row:
            if "\t" in cell or "\n" in cell:
                print(f"refusing to write: a cell contains a tab or newline: {cell!r}")
                return 1

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="\n") as fh:
        for row in rows:
            fh.write("\t".join(row) + "\n")

    print(f"wrote {OUT} — {len(rows) - 1} strings x {len(SUPPORTED_LANGUAGES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
