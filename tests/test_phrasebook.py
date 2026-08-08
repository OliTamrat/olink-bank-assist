"""review/phrasebook.tsv is an executable specification, not a document.

Every language defect found in the live demos was a phrase the assistant
failed to *understand* — a request for a manager read as a knowledge gap, a
forgotten PIN in Afaan Oromo, a spouse transfer refused as social engineering.
None of them would have been caught by reviewing translated output strings,
which is the thing a translation sheet is usually for.

So the phrasebook is the other half of the review: a native speaker writes
sentences and what should happen to them, and this turns their answer into a
permanent regression test the moment it lands. Nobody is asked to review a
regex — asking for phrasings has produced better results than asking about
patterns, every time it has been tried.

Rows marked FILL IN are skipped rather than failed. They are the sheet's own
record of what no speaker has supplied yet, and a language with nothing in it
must read as untested rather than as passing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bankassist import classifier

PHRASEBOOK = Path(__file__).resolve().parent.parent / "review" / "phrasebook.tsv"
TODO = "FILL IN"


def _rows() -> list[tuple[str, str, str, str]]:
    with PHRASEBOOK.open(encoding="utf-8-sig") as fh:
        lines = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    out = []
    for line in lines[1:]:
        lang, phrase, expect, why = (line + ["", "", "", ""])[:4]
        if not phrase.strip().startswith(TODO):
            out.append((lang.strip(), phrase.strip(), expect.strip(), why.strip()))
    return out


@pytest.mark.parametrize("lang,phrase,expect,why", _rows())
def test_phrasebook(lang: str, phrase: str, expect: str, why: str) -> None:
    got = classifier.classify_intent(phrase)
    assert got == expect, f"[{lang}] {phrase!r} -> {got}, expected {expect} ({why})"


def test_the_phrasebook_covers_both_directions() -> None:
    """A sheet of only-must-refuse cases would be satisfied by refusing
    everything. Over-refusal is the failure a reviewer cannot see from inside
    the product, so the negative cases have to outnumber nothing."""
    expects = [row[2] for row in _rows()]
    assert expects.count("question") >= 5, "not enough must-NOT-trigger cases"
    assert len(set(expects)) >= 4, "the phrasebook should exercise several outcomes"


def test_untranslated_languages_are_visible() -> None:
    """The sheet must keep naming what is missing. If someone deletes the
    FILL IN rows instead of answering them, Tigrinya silently becomes
    'covered' when nothing about it has been checked."""
    text = PHRASEBOOK.read_text(encoding="utf-8-sig")
    covered = {row[0] for row in _rows()}
    for lang in ("ti", "so"):
        supplied = sum(1 for row in _rows() if row[0] == lang)
        outstanding = text.count(f"\n{lang}\t{TODO}")
        assert supplied or outstanding, f"{lang} vanished from the phrasebook entirely"
    assert covered, "phrasebook is empty"
