"""The return leg of the curated-answer loop.

`faq_export.py` has referred to `faq_import.py` since the day it was written
and the file did not exist. So a bank's answers could be exported and
translated, and there was no way to get them back in — the loop had no return
leg, which is a strange thing to discover about a workflow the product's one
remaining language gap depends on.

Everything here is about what it REFUSES. A curated answer is served verbatim
with no retrieval and no model call: it is the single path in this product
with no gate after it, so a bad row is not a bad label, it is a bank telling a
customer something untrue in a language nobody on the team reads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import faq as faqlib
from bankassist.models import Faq

ROOT = Path(__file__).resolve().parent.parent


def _sheet(tmp_path: Path, rows: list[list[str]]) -> Path:
    header = ["question (en)", "status", "field", "en (English)", "am (አማርኛ)",
              "om (Afaan Oromoo)", "ti (ትግርኛ)", "so (Soomaali)", "reviewer notes"]
    out = ROOT / "review" / "faq-demo.tsv"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        "﻿" + "\n".join("\t".join(r) for r in [header] + rows) + "\n",
        encoding="utf-8",
    )
    return out


def _run(slug: str, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/faq_import.py", slug, *flags],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )


def test_it_exists_at_all() -> None:
    """The export's docstring promised this file for weeks."""
    assert (ROOT / "scripts" / "faq_import.py").exists()
    export = (ROOT / "scripts" / "faq_export.py").read_text(encoding="utf-8")
    assert "faq_import.py" in export


def test_a_missing_sheet_is_an_error_not_a_no_op() -> None:
    result = _run("demo-with-no-sheet-at-all")
    assert result.returncode != 0


def test_it_refuses_an_unknown_bank(
    db_session: Session, demo_bank: Any, tmp_path: Path, capsys: Any
) -> None:
    """In-process rather than through a subprocess: this one needs the test
    engine, and a slug that does not exist has to be named as such rather
    than fall through to an empty import."""
    import importlib

    sheet = ROOT / "review" / "faq-no-such-bank-anywhere.tsv"
    _sheet(tmp_path, [])
    sheet.write_text(
        (ROOT / "review" / "faq-demo.tsv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    module = importlib.import_module("scripts.faq_import")
    try:
        code = module.main(["faq_import.py", "no-such-bank-anywhere"])
    finally:
        sheet.unlink()
    assert code == 1
    assert "no such bank" in capsys.readouterr().out


def test_half_a_pair_is_skipped(
    db_session: Session, demo_bank: Any, tmp_path: Path
) -> None:
    """A question with no answer is not publishable and neither is the
    reverse. Mid-review sheets are full of these."""
    db_session.add(Faq(
        bank_id=demo_bank.id, language="en", question="What are your hours?",
        answer="Nine to five.", status="published",
        lookup=faqlib.key("What are your hours?", "en"),
    ))
    db_session.commit()
    _sheet(tmp_path, [
        ["What are your hours?", "published", "question",
         "What are your hours?", "የስራ ሰዓታችሁ መቼ ነው?", "", "", "", ""],
        ["", "published", "answer", "Nine to five.", "", "", "", "", ""],
    ])
    result = _run("demo")
    assert result.returncode == 0
    assert "half a pair" in result.stdout


def test_nothing_is_written_without_the_flag(
    db_session: Session, demo_bank: Any, tmp_path: Path
) -> None:
    """Dry run by default. This writes the words a customer reads with
    nothing downstream to catch a mistake."""
    db_session.add(Faq(
        bank_id=demo_bank.id, language="en", question="Where are you?",
        answer="Addis Ababa.", status="published",
        lookup=faqlib.key("Where are you?", "en"),
    ))
    db_session.commit()
    _sheet(tmp_path, [
        ["Where are you?", "published", "question",
         "Where are you?", "የት ነው ያላችሁት?", "", "", "", ""],
        ["", "published", "answer", "Addis Ababa.", "አዲስ አበባ።", "", "", "", ""],
    ])
    result = _run("demo")
    assert result.returncode == 0
    assert "pass --write" in result.stdout
    rows = db_session.execute(
        select(Faq).where(Faq.bank_id == demo_bank.id, Faq.language == "am")
    ).scalars().all()
    assert not rows, "a dry run wrote to the database"


def test_a_translation_lands_as_a_draft(
    db_session: Session, demo_bank: Any, tmp_path: Path
) -> None:
    """The rule that matters most. A translation must never arrive straight
    into the live path — approving is a separate, deliberate act, and it is
    the whole reason the review step exists."""
    db_session.add(Faq(
        bank_id=demo_bank.id, language="en", question="Do you offer loans?",
        answer="Yes, several kinds.", status="published",
        lookup=faqlib.key("Do you offer loans?", "en"),
    ))
    db_session.commit()
    _sheet(tmp_path, [
        ["Do you offer loans?", "published", "question",
         "Do you offer loans?", "ብድር ትሰጣላችሁ?", "", "", "", ""],
        ["", "published", "answer", "Yes, several kinds.", "አዎ፣ የተለያዩ ዓይነቶች።",
         "", "", "", ""],
    ])
    assert _run("demo", "--write").returncode == 0
    db_session.expire_all()
    am = db_session.execute(
        select(Faq).where(Faq.bank_id == demo_bank.id, Faq.language == "am")
    ).scalars().all()
    assert len(am) == 1
    assert am[0].question == "ብድር ትሰጣላችሁ?"
    assert am[0].status == "draft", "a translation went live without review"


def test_a_newline_marker_becomes_a_real_line_break(
    db_session: Session, demo_bank: Any, tmp_path: Path
) -> None:
    """Answers are bulleted often enough — eligibility lists, prize tiers —
    that flattening one changes what the customer reads."""
    db_session.add(Faq(
        bank_id=demo_bank.id, language="en", question="What do I need?",
        answer="A\nB", status="published",
        lookup=faqlib.key("What do I need?", "en"),
    ))
    db_session.commit()
    _sheet(tmp_path, [
        ["What do I need?", "published", "question",
         "What do I need?", "ምን ያስፈልጋል?", "", "", "", ""],
        ["", "published", "answer", "A⏎B", "ሀ⏎ለ", "", "", "", ""],
    ])
    assert _run("demo", "--write").returncode == 0
    db_session.expire_all()
    am = db_session.execute(
        select(Faq).where(Faq.bank_id == demo_bank.id, Faq.language == "am")
    ).scalars().one()
    assert am.answer == "ሀ\nለ"


def test_a_row_matching_nothing_is_reported_not_invented(
    db_session: Session, demo_bank: Any, tmp_path: Path
) -> None:
    """A pasted-in row that matches no existing answer is a corrupted sheet.
    Creating a curated answer out of it would be the worst possible read of
    the situation."""
    _sheet(tmp_path, [
        ["A question nobody ever asked", "draft", "question",
         "A question nobody ever asked", "ጥያቄ", "", "", "", ""],
        ["", "draft", "answer", "An answer", "መልስ", "", "", "", ""],
    ])
    result = _run("demo", "--write")
    assert result.returncode == 0
    assert "matched no existing answer" in result.stdout
    db_session.expire_all()
    assert not db_session.execute(
        select(Faq).where(Faq.bank_id == demo_bank.id, Faq.language == "am")
    ).scalars().all()


@pytest.fixture(autouse=True)
def _clean_sheet() -> Any:
    yield
    sheet = ROOT / "review" / "faq-demo.tsv"
    if sheet.exists():
        sheet.unlink()
