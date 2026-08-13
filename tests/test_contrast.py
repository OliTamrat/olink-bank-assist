"""Every text colour clears WCAG AA against the surface it sits on.

This exists because the founder caught something the whole team had looked
straight past: *"the light grey font on darker background has a visibility
issue."* Measuring rather than eyeballing found two real failures —

- the public page's `--faint` at **3.80:1**, carrying the micro-labels, plan
  subtitles, chart axis and footer;
- the widget's dark-mode `--text-3` at **4.32:1**, on the surface a bank's
  *customers* read.

Both are below the 4.5:1 floor for normal text. Low-contrast grey on
near-black is the default look of this entire design genre, which is exactly
why it slips through review: it looks deliberate. It is still unreadable on a
dim laptop in a bright office, which is where a bank's staff will open it.

The test parses the palettes out of the stylesheets, so it covers whatever
tokens exist rather than a list somebody has to remember to extend. It is
also the only defence against the obvious "polish" of nudging a grey down a
shade to make a page look more refined.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "bankassist" / "static"

#: WCAG 2.1 AA for normal-size text. Large text (≥24px, or ≥18.66px bold) is
#: allowed 3:1, but nothing here relies on that — every token below is used
#: for body copy or smaller somewhere, so the strict floor is the right one.
AA_NORMAL = 4.5

#: Tokens that carry text. Brand/accent colours, borders and surfaces are not
#: in scope: a border does not have to be readable.
TEXT_TOKENS = (
    "--ink", "--body", "--muted", "--faint",
    "--text", "--text-2", "--text-3",
)


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _palette(page: str) -> tuple[dict[str, str], str]:
    """The dark palette and its background, read out of the stylesheet."""
    text = (STATIC / page).read_text(encoding="utf-8")
    block = re.search(r':root\[data-theme="dark"\]\s*\{(.*?)\n\s*\}', text, re.S)
    if block is None:
        block = re.search(r":root \{(.*?)\n\}", text, re.S)
    assert block, f"{page} has no palette block"
    tokens = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", block.group(1)))
    background = tokens.get("--bg") or tokens.get("--surface")
    assert background, f"{page} declares no literal background colour"
    return tokens, background


def test_the_proof_that_this_test_works() -> None:
    """The two values that failed, so the arithmetic is anchored to something
    real rather than trusted."""
    assert round(contrast("#626c7d", "#060709"), 2) == 3.80  # old site --faint
    assert round(contrast("#6f7787", "#0c0d10"), 2) == 4.32  # old widget --text-3
    assert round(contrast("#ffffff", "#000000"), 0) == 21


@pytest.mark.parametrize("page", ["site.html", "admin.html", "widget.html"])
def test_every_text_token_clears_aa(page: str) -> None:
    tokens, background = _palette(page)
    checked = 0
    for name in TEXT_TOKENS:
        if name not in tokens:
            continue
        checked += 1
        ratio = contrast(tokens[name], background)
        assert ratio >= AA_NORMAL, (
            f"{page} {name} ({tokens[name]}) is {ratio:.2f}:1 on {background} — "
            f"below the {AA_NORMAL}:1 floor for normal text"
        )
    assert checked >= 3, f"{page}: only found {checked} text tokens — did the names change?"


def test_the_public_page_holds_a_higher_bar_for_body_copy() -> None:
    """AA is a floor, not a target.

    The page is long-form reading on a near-black canvas, and `--muted`
    carries most of it. 7:1 is the AAA threshold and it is what stops the
    page looking washed out rather than merely passing.
    """
    tokens, background = _palette("site.html")
    ratio = contrast(tokens["--muted"], background)
    assert ratio >= 7.0, f"--muted is {ratio:.2f}:1 — body copy on this page should clear AAA"


def test_body_copy_does_not_sit_on_an_unmeasured_surface() -> None:
    """Cards are lighter than the page, which LOWERS contrast for light text.

    Checking only against `--bg` would pass a colour that fails on every card
    it is actually printed on.
    """
    tokens, background = _palette("site.html")
    card_over_bg = "#0b0c0e"  # --card (white at 2.6%) composited over --bg
    for name in ("--body", "--muted", "--faint"):
        ratio = contrast(tokens[name], card_over_bg)
        assert ratio >= AA_NORMAL, (
            f"{name} is {ratio:.2f}:1 on a card surface — passes on the page "
            "background and fails where it is actually used"
        )
