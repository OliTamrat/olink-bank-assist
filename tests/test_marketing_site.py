"""The public page, and the claims it is allowed to make.

A marketing page fails differently from a product surface. It does not crash;
it says something that is not true, and nobody notices until a prospect does.
The three failures this guards are all ones this repo is specifically exposed
to:

1. **A prospect bank's name on a public page.** CBE, Dashen and Awash are
   unauthorized internal prototypes built from public information (ADR-0009).
   Internally that is a demo with a disclaimer. Publicly it implies a
   relationship that does not exist — a trademark problem, and the fastest way
   to lose those three as customers. The page demos on the fictional tenant.

2. **A number nobody can stand behind.** There are no production deployments,
   so any "% deflected", "N banks", "M conversations" is invented. The rule
   the assistant follows — never state a figure you cannot source — applies to
   our own copy too.

3. **A price.** The decision is to publish the pricing *model* and not a
   number, because a figure with no delivery-cost data behind it is one we get
   negotiated down from. A `$` on this page means somebody reversed that.

Plus the ordinary ones: the page must serve, the demo must point at the real
widget, and it must reach no third-party origin — a bank's staff sit behind
proxies that block them, and the whole font/vendor doctrine exists for this.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parent.parent / "bankassist" / "static"
SITE = (STATIC / "site.html").read_text(encoding="utf-8")


def test_the_page_is_served_at_the_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "no-store" in r.headers["cache-control"]
    assert "Olink Bank Assist" in r.text


@pytest.mark.parametrize("bank", ["CBE", "Commercial Bank of Ethiopia", "Dashen", "Awash"])
def test_no_prospect_bank_appears_on_the_public_page(bank: str) -> None:
    """The landmine.

    These three exist in the repo as prototypes built from public information,
    each carrying a mandatory in-product disclaimer. A public page naming them
    is a different act entirely from an internal demo, and not one anybody
    authorised.
    """
    assert bank.lower() not in SITE.lower(), (
        f"{bank} is named on the public marketing page — see ADR-0009"
    )


def test_the_demo_is_the_real_widget_on_the_fictional_tenant() -> None:
    """Not a video, not a screenshot, and not a real bank's slug."""
    frames = re.findall(r'<iframe[^>]*src="([^"]+)"', SITE)
    assert frames, "the page has no live demo"
    assert any(f.startswith("/widget?bank=demo") for f in frames), f"demo src is {frames}"
    for src in frames:
        assert src.startswith("/"), f"the demo frame is off-origin: {src}"


def test_no_invented_metrics() -> None:
    """There are no production deployments, so there are no production numbers.

    Written as a pattern rather than a word list because the tempting forms
    are all numeric: "94% deflected", "12 banks", "40,000 conversations".
    """
    body = re.sub(r"<!--.*?-->", "", SITE, flags=re.S)
    forbidden = [
        r"\d+\s*%\s*(of\s+)?(deflect|resolv|contain|automat)",
        r"\b\d+\s*(banks|institutions|customers|clients)\b",
        r"\b\d[\d,]*\s*(conversations|messages|users)\s+(handled|served|answered)",
        r"\btrusted by\b",
        r"\bjoin \d+",
    ]
    for pattern in forbidden:
        hit = re.search(pattern, body, re.I)
        assert not hit, f"unsupportable claim on the public page: {hit.group(0)!r}"


def test_no_price_is_published() -> None:
    """The decision is the model, not a number (this session, with the founder).

    A currency figure here means somebody quietly reversed that — most likely
    while "just filling in the pricing table".
    """
    body = re.sub(r"<!--.*?-->", "", SITE, flags=re.S)
    money = re.search(r"(?:\$|USD|ETB|Br\.?)\s?\d", body)
    assert not money, f"a price appeared on the public page: {money.group(0)!r}"
    # …and the model itself is still stated, so "no numbers" cannot quietly
    # become "no pricing section at all".
    assert "per seat" in body.lower(), "the per-institution pricing model is gone"
    assert re.search(r"conversation volume", body, re.I), "the volume tier basis is gone"


def test_it_reaches_no_third_party_origin() -> None:
    """Same doctrine as the vendored fonts and the LiveKit SDK.

    A marketing page is where a CDN link normally creeps in — an icon set, a
    font, an analytics tag. On a page a bank's staff open from inside their
    own network, every extra origin is one more thing their proxy can block
    and their security review can object to.
    """
    for url in re.findall(r'(?:src|href)="(https?://[^"]+)"', SITE):
        raise AssertionError(f"the public page loads from an external origin: {url}")


def test_the_launch_placeholders_are_findable_and_empty() -> None:
    """Two values set this page live, and shipping a guessed one is worse.

    An invented contact address silently drops enquiries; a canonical URL
    invented before the domain is chosen is a wrong URL that has to be hunted
    down. Both are empty on purpose, and the buttons admit it rather than
    opening a blank mail window addressed to nobody.
    """
    block = re.search(r"var SITE = \{(.*?)\};", SITE, re.S)
    assert block, "the launch-config block is gone"
    for key in ("contactEmail", "domain"):
        assert key in block.group(1), f"{key} is no longer configurable"
    # No stray address hard-coded elsewhere on the page.
    without_config = re.sub(r"var SITE = \{.*?\};", "", SITE, flags=re.S)
    stray = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", without_config)
    assert not stray, f"a contact address is hard-coded outside the config: {stray}"


def test_the_language_claim_states_what_is_reviewed() -> None:
    """The page says six languages. Two of them have been reviewed by a native
    speaker and three have not, and saying so is the difference between a
    claim and a claim somebody can catch us on."""
    body = SITE.lower()
    assert "tigrinya" in body and "somali" in body and "swahili" in body
    assert re.search(r"review", body), "the review status is not mentioned at all"
    assert re.search(r"first-pass|first pass|under (professional )?review", body), (
        "the page claims six reviewed languages without qualifying which"
    )


def test_geez_never_gets_set_in_the_display_serif() -> None:
    """Two defects at once on this page, and the second is new.

    The first is the familiar one: display tracking and leading tuned for
    Latin, crowding a script whose characters are whole syllables.

    The second only exists here. The page's voice is a **serif** at display
    size, and Playfair has no Ethiopic at all — so a Ge'ez headline in the
    serif falls through to a system face while keeping the serif's tracking
    and leading. It has to switch families, not just relax the spacing.
    """
    rule = re.search(r"\.display:lang\(am\)[^{]*\{([^}]*)\}", SITE, re.S)
    assert rule, "no Ge'ez rule on the display face"
    body = rule.group(1)
    assert "var(--sans)" in body, "Ge'ez is still being set in the display serif"
    assert "letter-spacing: normal" in body, "Ge'ez is tracked like Latin"
    assert re.search(r"line-height: 1\.[23]", body), "Ge'ez leading is Latin's"


def test_the_serif_reaches_the_selling_surfaces_and_stops() -> None:
    """It goes as far as the sign-in screen, and no further.

    The gate is the first thing anybody sees and the only part of the admin
    panel doing a selling job, so it shares the public page's voice. The
    dashboard behind it does not — a serif on a table of conversation counts
    is costume.

    **The widget must never load it.** That runs on customers' phones on
    Ethiopian mobile connections, where 38 KB is a real cost and a display
    serif has no job at all. This is the line that matters, and it is the one
    a future "make it all consistent" pass would cross.
    """
    assert "playfair" in SITE.lower(), "the display serif is gone from the public page"

    admin = (STATIC / "admin.html").read_text(encoding="utf-8")
    assert "playfair" in admin.lower(), "the sign-in screen lost the display serif"
    # …and only the gate uses it. If the dashboard's own type started asking
    # for the serif, this catches it.
    assert "stage-line" in admin, "the gate headline rule is gone"

    widget = (STATIC / "widget.html").read_text(encoding="utf-8")
    assert "playfair" not in widget.lower(), (
        "the widget now loads the marketing serif — 38 KB onto a customer's "
        "phone for type that surface never sets"
    )


def test_every_nav_target_exists() -> None:
    """A nav that scrolls to nothing is the cheapest possible way to look
    unfinished on the one page whose job is not looking unfinished."""
    ids = set(re.findall(r'id="([^"]+)"', SITE))
    for href in re.findall(r'href="#([^"]+)"', SITE):
        assert href in ids, f"nav links to #{href}, which does not exist"
