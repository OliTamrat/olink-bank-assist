"""The panel can hand a translator the sheet, without a database URL.

`scripts/faq_export.py` writes this file and needs the production database.
The person who has the answers is signed into the admin panel, not holding a
connection string — so requiring the script is how a translation does not get
done. The Curated Answers page writes the same sheet from data it already has
on screen.

Same shape as the script's output on purpose: `scripts/faq_import.py` reads
either one back. These tests pin the places the two ends could silently drift
apart, because the failure mode is a reviewer's afternoon of work refusing to
load — or worse, loading into the wrong columns.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "bankassist" / "static" / "admin.html"


def _block() -> str:
    html = ADMIN.read_text(encoding="utf-8")
    return html.split("function downloadFaqSheet")[1].split("\nfunction loadFaq")[0]


def test_the_panel_can_download_the_sheet() -> None:
    html = ADMIN.read_text(encoding="utf-8")
    assert "function downloadFaqSheet" in html
    assert 'id="faq-dl"' in html
    assert 'A("download_for_translation")' in html


def test_the_button_and_the_script_agree_on_the_newline_marker() -> None:
    """A cell's line breaks are written as a visible marker so a spreadsheet
    cannot eat a column. If the two ends disagree the importer puts back a
    literal ⏎ — or nothing — and a bulleted eligibility list becomes one
    run-on sentence, which is a different answer from the approved one."""
    export = (ROOT / "scripts" / "faq_export.py").read_text(encoding="utf-8")
    assert 'var FAQ_NEWLINE = "⏎"' in ADMIN.read_text(encoding="utf-8")
    assert 'NEWLINE = "⏎"' in export


def test_the_button_writes_the_columns_the_importer_reads() -> None:
    """The importer keys off the `field` column and off each header cell
    starting with a language code."""
    block = _block()
    assert '"question (en)", "status", "field"' in block
    assert '"question", "answer"' in block
    # The code opens each header cell, which is what the importer matches on
    # — not the position, so a reordered sheet still loads.
    assert 'l + " (" + (LANG_NAME[l] || l)' in block
    # And the BOM, or Excel renders Ge'ez as mojibake and the reviewer's
    # first impression is that the tool is broken.
    assert "\\ufeff" in block


def test_the_download_groups_by_source_not_by_wording() -> None:
    """A translation is a different string from its original, so grouping on
    the question text puts every language on its own row — five unrelated
    lines for a reviewer to correct instead of one."""
    assert "f.source_faq_id || f.id" in _block()


def test_the_api_sends_the_grouping_key() -> None:
    """Which it did not until this change: the panel had no way to pair a
    translation with its original."""
    api = (ROOT / "bankassist" / "api.py").read_text(encoding="utf-8")
    row = api.split("def _faq_row")[1].split("\n@app")[0]
    assert '"source_faq_id": row.source_faq_id' in row


def test_an_empty_list_says_so_rather_than_downloading_nothing() -> None:
    """A zero-byte file that opens blank reads as a broken export."""
    block = _block()
    assert 'A("nothing_to_download")' in block
