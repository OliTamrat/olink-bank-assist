"""The admin shell on a small screen, and in a browser tab.

Both findings came from the same first-run audit, and neither is visible from
an API test.

**The drawer.** Below 980px the sidebar kept its markup and lost its column:
`position: static` dropped it into normal flow, so twenty-one nav items and an
expanded Channels submenu stacked *above* the page and a phone scrolled
roughly 450px before reaching the dashboard. The existing collapse control
could not help — `data-rail="mini"` narrows a column that is no longer there.

**The favicon.** Every surface 404'd on `/favicon.ico` and showed a blank tab,
on the panel a bank's staff leave open all day.

These tests are structural rather than visual: they assert the mechanism is
present and wired, because CSS cannot be asserted about usefully from Python.
The rendering was checked in a real browser at 390px — see the PR.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
ADMIN_HTML = (ROOT / "bankassist" / "static" / "admin.html").read_text(encoding="utf-8")
WIDGET_HTML = (ROOT / "bankassist" / "static" / "widget.html").read_text(encoding="utf-8")
SITE_HTML = (ROOT / "bankassist" / "static" / "site.html").read_text(encoding="utf-8")

# Everything inside the small-screen block, which is where the drawer lives.
MOBILE_BLOCK = ADMIN_HTML.split("@media (max-width: 980px) {", 1)[1].split("\n}", 1)[0]


def test_the_sidebar_no_longer_unsticks_into_the_page() -> None:
    """The bug itself, pinned.

    `position: static` on `.side` is what put the navigation above the
    content. If it comes back, so does 450px of scrolling before a phone
    reaches the dashboard.
    """
    assert not re.search(r"\.side\s*\{[^}]*position:\s*static", ADMIN_HTML), (
        "the sidebar is being dropped into normal flow again"
    )


def test_the_drawer_is_off_canvas_and_slides() -> None:
    assert "transform: translateX(-100%)" in MOBILE_BLOCK, (
        "the drawer must start off-canvas"
    )
    assert "body.nav-open .side" in MOBILE_BLOCK, "nothing brings the drawer back"
    assert "position: fixed" in MOBILE_BLOCK, "a drawer sits over the page, not in it"


def test_a_transform_not_a_reflow() -> None:
    """Composited, because this runs on cheap Android phones.

    Animating `left` relayouts the whole shell every frame; `transform` does
    not touch layout at all.
    """
    assert "transition: transform" in MOBILE_BLOCK
    assert not re.search(r"transition:[^;]*\bleft\b", MOBILE_BLOCK)


def test_the_drawer_has_exactly_one_opener() -> None:
    """One function knowing what "open" means, so the class, the scrim and the
    button cannot disagree about it."""
    assert 'id="nav-toggle"' in ADMIN_HTML
    assert "function setNav(" in ADMIN_HTML
    body = ADMIN_HTML.split("function setNav(", 1)[1].split("\nfunction ", 1)[0]
    for part in ("nav-open", "nav-scrim", "aria-expanded"):
        assert part in body, f"setNav does not manage {part}"


def test_navigating_closes_the_drawer() -> None:
    """The omission that is easiest to make and worst to live with: tapping a
    nav item otherwise leaves the menu covering the page it just opened."""
    go = ADMIN_HTML.split("function go(id) {", 1)[1].split("\nfunction ", 1)[0]
    assert "closeNav()" in go


def test_escape_and_the_scrim_both_close_it() -> None:
    assert 'id="nav-scrim"' in ADMIN_HTML
    assert "$(\"nav-scrim\").onclick = closeNav" in ADMIN_HTML
    assert '"Escape"' in ADMIN_HTML


def test_resizing_back_to_desktop_releases_the_scroll_lock() -> None:
    """`body.nav-open` locks scrolling. Left set after a resize past the
    breakpoint, the page would be unscrollable with nothing on screen to
    explain why."""
    assert "window.innerWidth > 980" in ADMIN_HTML


def test_the_toggle_is_only_for_small_screens() -> None:
    """Above the breakpoint the rail is always visible, so a menu button would
    be a control that does nothing."""
    assert re.search(r"\.navtoggle\s*\{\s*display:\s*none", ADMIN_HTML), (
        "the menu button must be hidden on desktop"
    )
    assert ".navtoggle { display: inline-flex" in MOBILE_BLOCK


def test_the_menu_button_speaks_every_language() -> None:
    """The multilingual rule covers chrome, and an aria-label is chrome a
    screen reader reads aloud."""
    import json

    from bankassist.i18n import SUPPORTED_LANGUAGES

    table = json.loads(
        (ROOT / "bankassist" / "admin_strings.json").read_text(encoding="utf-8")
    )
    for lang in SUPPORTED_LANGUAGES:
        assert table[lang]["nav_menu"].strip(), f"nav_menu is blank for {lang}"
    assert '"nav-toggle": "nav_menu"' in ADMIN_HTML, "the label is not wired to the table"


def test_the_desktop_icon_rail_is_neutralised_in_the_drawer() -> None:
    """A 62px drawer is neither a rail nor a menu.

    `data-rail="mini"` is remembered per browser, so somebody who collapsed
    the rail on a laptop and later opened the panel on their phone would
    otherwise get an icon-only drawer.
    """
    assert '[data-rail="mini"] .side' in MOBILE_BLOCK
    assert "display: revert" in MOBILE_BLOCK, "the collapsed labels must come back"


# ------------------------------------------------------------------ favicon


def test_the_favicon_is_served_at_both_paths(client: TestClient) -> None:
    """Browsers ask for `/favicon.ico` by convention whether or not it is
    linked, and render SVG when they get it."""
    for path in ("/favicon.ico", "/favicon.svg"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("image/svg+xml"), path


def test_every_surface_shows_a_mark(client: TestClient) -> None:
    assert 'rel="icon"' in ADMIN_HTML
    assert 'rel="icon"' in WIDGET_HTML
    assert 'rel="icon"' in SITE_HTML


def test_the_served_mark_is_the_one_the_public_page_already_shows() -> None:
    """Not a new design.

    A second mark competing with the public page's would be a branding
    decision wearing a 404 fix. The served file carries the same path data
    that `site.html` has always had inline.
    """
    from urllib.parse import unquote

    served = (ROOT / "bankassist" / "static" / "favicon.svg").read_text(encoding="utf-8")
    inline = unquote(re.search(r'<link rel="icon" href="([^"]+)"', SITE_HTML).group(1))
    assert re.search(r"d='([^']+)'", inline).group(1) == re.search(
        r'd="([^"]+)"', served
    ).group(1), "the served mark has drifted from the public page's"


def test_the_favicon_is_vendored_not_fetched(client: TestClient) -> None:
    """Same argument as the fonts and the LiveKit SDK: these pages run on a
    bank's own production site and show customer conversations, so a
    third-party asset origin is a CSP entry in exchange for nothing."""
    for html in (ADMIN_HTML, WIDGET_HTML):
        icon = re.search(r'<link rel="icon" href="([^"]+)"', html).group(1)
        assert icon.startswith("/"), f"the icon is loaded from off-origin: {icon}"
