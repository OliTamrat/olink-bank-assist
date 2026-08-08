"""Run every sentence in review/phrasebook.tsv through the live classifier.

    python scripts/check_phrasebook.py           # all languages
    python scripts/check_phrasebook.py ti so     # just these

This is the half of the review that matters most, and the half a strings
spreadsheet cannot touch. Every language defect found in the live demos so far
was a phrase the assistant failed to *understand*, not a reply worded badly:
a request for a manager read as a knowledge gap, a forgotten PIN in Afaan
Oromo, a spouse transfer refused as if it were social engineering.

A reviewer writes sentences. That is the skill they have. Nobody should be
asked to review a regex, and asking them to has produced worse results than
asking them for phrasings, twice.

Rows marked FILL IN are counted separately and never as failures — they are
the sheet's own record of what has not been covered yet, so an untranslated
language reads as "0 of 7 supplied" rather than quietly passing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bankassist.classifier import classify_intent  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "review" / "phrasebook.tsv"
TODO = "FILL IN"


def rows() -> list[dict[str, str]]:
    with SRC.open(encoding="utf-8-sig") as fh:
        lines = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    header = lines[0]
    # strict=False on purpose: spreadsheets routinely drop trailing empty
    # cells on export, so a row whose last column was left blank arrives
    # short. Refusing to read the sheet because a reviewer skipped an
    # optional note would be an absurd way to lose their work.
    return [dict(zip(header, line, strict=False)) for line in lines[1:]]


def main() -> int:
    wanted = {a.lower() for a in sys.argv[1:]}
    failures: list[tuple[str, str, str, str, str]] = []
    todo: dict[str, int] = {}
    checked = 0

    for row in rows():
        lang = row["language"].strip()
        if wanted and lang not in wanted:
            continue
        phrase = row["phrase"].strip()
        if phrase.startswith(TODO):
            todo[lang] = todo.get(lang, 0) + 1
            continue
        checked += 1
        expect = row["expect"].strip()
        got = classify_intent(phrase)
        if got != expect:
            failures.append((lang, phrase, expect, got, row.get("why it matters", "")))

    for lang, phrase, expect, got, why in failures:
        print(f"FAIL [{lang}] {phrase}\n       expected {expect}, got {got}   ({why})")

    print(f"\n{checked - len(failures)}/{checked} passed")
    if todo:
        missing = ", ".join(f"{lang}: {n}" for lang, n in sorted(todo.items()))
        print(f"still to be supplied by a native speaker — {missing}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
