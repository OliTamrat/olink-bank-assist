"""The linguist loop has to survive a lap.

`CLAUDE.md` rule 2b names `scripts/i18n_export.py` as how a reviewer gets the
assistant's own words to correct. It had never produced a file. Three separate
faults, each invisible because the workbook builder covers the same content
and works:

1. **The export refused to write.** It bailed on any cell containing a tab or
   a newline, on the stated assumption that neither ever appears — while
   `greeting` and `greeting_named` carry a blank line and the language-picker
   row in all six languages. Nothing was ever written.
2. **The import rejected 528 of 551 rows.** The sheet carries three tables
   distinguished by a key prefix and the importer knew about one, so every
   `ui.` and `admin.` correction came back as "unknown key". A reviewer could
   fix every word the staff read and have none of it land.
3. **The import ate meaningful whitespace.** It `.strip()`ped each value, and
   `couldnt_connect` ends in a space in all six languages because the panel
   writes `A("couldnt_connect") + err.message`. A round trip silently turned
   six error messages into "Couldn't connect:Network error".

The third is the one worth remembering: the first two fail loudly, and the
third would have shipped.

Loading by file path rather than module name is deliberate — see the CLAUDE.md
gotcha about `pytest` vs `python -m pytest` disagreeing on `sys.path`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "review" / "strings.tsv"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPORT = _load("i18n_export")
IMPORT = _load("i18n_import")


# ------------------------------------------------------------- the escaping


def test_escaping_survives_the_values_that_broke_it() -> None:
    for original in (
        "Hello!\n\n🌐 English · አማርኛ",
        "a\tb",
        "trailing space: ",
        "  leading",
        "back\\slash",
        r"literal \n that is not a newline",
        "plain",
    ):
        assert IMPORT.unescape(EXPORT.escape(original)) == original, original


def test_an_escaped_cell_can_never_break_the_grid() -> None:
    """The whole reason to escape: a raw tab ends the column, a raw newline
    ends the row, and either one silently shifts every value after it."""
    for original in ("a\tb", "a\nb", "a\r\nb"):
        cell = EXPORT.escape(original)
        assert "\t" not in cell
        assert "\n" not in cell


def test_backslash_is_escaped_first() -> None:
    r"""`\n` — a real backslash then an n — must not come back as a newline.

    Chained `.replace()` calls get this wrong in both orders, which is why
    `unescape` scans instead.
    """
    assert IMPORT.unescape(EXPORT.escape(r"\n")) == r"\n"
    assert "\n" not in IMPORT.unescape(EXPORT.escape(r"\n"))


# ----------------------------------------------------------- the whole lap


def test_the_sheet_exists_and_carries_every_table() -> None:
    """It never did before. 551 rows across three tables."""
    assert SHEET.exists(), "run scripts/i18n_export.py"
    keys = [
        line.split("\t")[0]
        for line in SHEET.read_text(encoding="utf-8-sig").splitlines()[1:]
        if line.strip()
    ]
    assert any(k.startswith("admin.") for k in keys), "no admin strings in the sheet"
    assert any(k.startswith("ui.") for k in keys), "no widget strings in the sheet"
    assert any(
        k and not k.startswith(("admin.", "ui.", "—")) for k in keys
    ), "no assistant strings in the sheet"


def test_a_lap_changes_nothing(capsys: Any) -> None:
    """Export then import must be identity.

    The dry run reports every difference it would write, so "no changes" is
    the assertion: anything else means a value did not survive the trip.
    """
    assert EXPORT.main() == 0
    assert IMPORT.main() == 0
    assert "no changes" in capsys.readouterr().out


def test_the_lap_preserves_a_load_bearing_trailing_space() -> None:
    """The bug that would have shipped, pinned to the string that revealed it.

    Asserted on the data rather than through the scripts, so it fails whether
    the importer starts stripping again or somebody "tidies" the space out of
    the table.
    """
    table = json.loads(
        (ROOT / "bankassist" / "admin_strings.json").read_text(encoding="utf-8")
    )
    for lang, strings in table.items():
        assert strings["couldnt_connect"].endswith(" "), (
            f"couldnt_connect [{lang}] lost its trailing space — the panel "
            f'writes A("couldnt_connect") + err.message'
        )


def test_the_importer_knows_every_table_the_exporter_writes() -> None:
    """The mismatch that rejected 528 rows.

    Compared as sets so adding a fourth table to one script and not the other
    fails here rather than in a reviewer's inbox.
    """
    exported = {"", "ui.", "admin."}
    assert {prefix for prefix, _ in IMPORT.TABLES} == exported


def test_the_importer_still_refuses_an_unknown_key() -> None:
    """The escaping and the extra tables must not have widened what it
    accepts: a typed-in row is a typo far more often than a new string."""
    known = {prefix for prefix, _ in IMPORT.TABLES}
    assert "nonsense." not in known
