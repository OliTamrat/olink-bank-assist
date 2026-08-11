"""The linguist workbook is a tracked binary, so it has to be reproducible.

A reviewer receives `review/Olink_Bank_Assist_language_review.xlsx` and sends
back corrections. The only way to trust that file is to be able to rebuild it
from the JSON and get the same bytes — otherwise "the workbook changed" says
nothing about whether a translation changed.

The script pinned `docProps/core.xml` for exactly this reason, but the zip
entry mtimes were left on the wall clock, so the property never actually held.
Nothing tested it, which is why it went unnoticed for three pull requests.
"""

from __future__ import annotations

import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_review_workbook.py"
WORKBOOK = ROOT / "review" / "Olink_Bank_Assist_language_review.xlsx"

# Deliberately no `importorskip` for openpyxl. It is a declared dev dependency,
# and the point of this module is that a check nobody runs is not a check — so
# a missing dependency should fail here rather than quietly skip.


def _build() -> None:
    """Run the builder in-process.

    CI runs bare `pytest`, so the repository root is not on `sys.path` and
    `import scripts.build_review_workbook` fails there while passing locally
    under `python -m pytest`. Loading by path sidesteps that difference.
    """
    spec = importlib.util.spec_from_file_location("_build_review_workbook", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


@pytest.fixture
def rebuilt(tmp_path: Path) -> bytes:
    """Rebuild the workbook in place, restoring the committed file after."""
    backup = tmp_path / "committed.xlsx"
    shutil.copyfile(WORKBOOK, backup)
    try:
        _build()
        return WORKBOOK.read_bytes()
    finally:
        shutil.copyfile(backup, WORKBOOK)


def test_the_committed_workbook_matches_what_the_script_builds(rebuilt: bytes) -> None:
    committed = WORKBOOK.read_bytes()
    assert rebuilt == committed, (
        "review/Olink_Bank_Assist_language_review.xlsx is out of step with the "
        "strings it is built from — run scripts/build_review_workbook.py and "
        "commit the result."
    )


def test_rebuilding_twice_gives_the_same_bytes(rebuilt: bytes) -> None:
    """Building the same input twice has to produce identical bytes.

    This states the property but is a weak detector on its own: two builds a
    fraction of a second apart land in the same two-second DOS timestamp
    granularity, so it passed even against the unpinned script. The mtime
    assertion below is what actually catches the clock leaking in.
    """
    _build()
    again = WORKBOOK.read_bytes()
    assert again == rebuilt


def test_no_zip_entry_carries_a_build_time(rebuilt: bytes) -> None:
    """Pin the mechanism, not just the symptom.

    Byte equality would also hold if two builds happened inside the same
    two-second DOS timestamp granularity, so assert the dates directly.
    """
    with zipfile.ZipFile(WORKBOOK) as archive:
        stamps = {info.date_time for info in archive.infolist()}
    assert stamps == {(2020, 1, 1, 0, 0, 0)}, (
        f"zip entries carry a wall-clock mtime: {sorted(stamps)}"
    )
