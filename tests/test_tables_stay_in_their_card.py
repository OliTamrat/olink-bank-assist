"""A table must not drag the page sideways.

Reported from an iPhone as pages "blending/bleeding outside the card", with
screenshots of Audit log and Knowledge Base. It is one defect with two visible
halves, and the second half is the one that makes it look broken rather than
merely cut off:

1. `<table>` sat as a direct child of `.panel`, which has padding and a
   `border-radius` but no `overflow`. Five columns of real content need about
   450px; a phone gives the panel 325px. The surplus painted straight through
   the rounded border.
2. Because nothing contained it, the surplus widened the **document**. The
   page then scrolled sideways, so "Add article", "Export CSV" and the filter
   select were clipped off the *left* edge — which is why the screenshots look
   like the whole layout has slipped rather than like one wide table.

Measured in Chromium at 390px before the fix, on a seeded `cbe` tenant:

    Knowledge Base  table 447px in a 325px panel — page 375px → 546px
    Team            table 505px in a 325px panel
    Audit log       table 436px in a 325px panel — page 375px → 477px
    Conversations   table 437px in a 325px panel

After: every page reports a 375px document at a 390px viewport, each
`.tablewrap` scrolls by 144–212px, and its box stays inside its panel's box.

These assertions are structural, like `test_shell_on_a_phone.py`: CSS cannot
be asserted about usefully from Python, so what is pinned here is that the
mechanism exists and that every table is inside it. The rendering was driven
in a real browser — see the PR.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = (ROOT / "bankassist" / "static" / "admin.html").read_text(encoding="utf-8")


def test_the_scroll_container_exists() -> None:
    assert re.search(r"\.tablewrap\s*\{[^}]*overflow-x:\s*auto", ADMIN_HTML), (
        "the surplus width has to go somewhere; without a scroll container it "
        "goes into the document and the whole page moves"
    )


def test_every_table_is_inside_one() -> None:
    """The check that would have caught the fifth table.

    Four tables were wrapped by hand. A fifth added later has no reason to
    remember, and the failure is invisible on a desktop — which is where it
    will be written.
    """
    opens = re.findall(r"<table\b", ADMIN_HTML)
    wrapped = re.findall(r"class=[\"']tablewrap[\"']><table\b", ADMIN_HTML)
    assert len(opens) == len(wrapped), (
        f"{len(opens)} table(s), {len(wrapped)} wrapped — a bare <table> in a "
        f".panel widens the document on a phone"
    )


def test_every_wrapper_is_closed() -> None:
    """An unbalanced wrapper is worse than none: it swallows the rest of the
    panel into a scroll box. Counted rather than parsed, because the markup is
    assembled from string fragments across four functions."""
    assert len(re.findall(r"class=[\"']tablewrap[\"']>", ADMIN_HTML)) == len(
        re.findall(r"</tbody></table></div>", ADMIN_HTML)
    )


def test_the_container_is_not_the_panel_itself() -> None:
    """`overflow-x` on a box forces the other axis to compute to `auto` too.

    Putting it on `.panel` would have been one line instead of four wrappers,
    and would have made every panel in the product a vertical clipper for the
    sake of the four that hold a table.
    """
    panel = re.search(r"^\.panel \{[^}]*\}", ADMIN_HTML, re.M)
    assert panel is not None
    assert "overflow" not in panel.group(0)


def test_the_page_still_says_tables_are_full_width() -> None:
    """Inside a scroll container a table narrower than the panel must still
    fill it, or a two-column table renders bunched against the left edge with
    dead space beside it."""
    assert re.search(r"^table \{[^}]*width:\s*100%", ADMIN_HTML, re.M)
