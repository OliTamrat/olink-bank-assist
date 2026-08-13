"""The typefaces are served from our own origin, and only the typefaces are.

Two separate things are being defended here.

The first is a **security** property. `/fonts/{name}` takes a name off the
wire, and the obvious implementation — join it onto a directory — is a path
traversal route. The allowlist in `api.py` is what makes that impossible, and
a test is the only thing that stops somebody "simplifying" it back into a join
during a tidy-up.

The second is a **product** property that no other test in this suite can see.
Every page in this panel declares its font stack in CSS and loads the files by
path. Nothing in Python imports them, so if a file is renamed or dropped from
the image the app still starts, every test still passes, and the only symptom
is that a bank's dashboard quietly renders in Times New Roman. These tests fail
instead.

The stack order is asserted for the same reason it was wrong for a year:
`"Noto Sans Ethiopic"` led both files, so every Latin character in the
product — labels, numbers, English answers — was drawn with a Ge'ez face's
Latin glyphs. Per-character fallback means Inter can lead without costing
Amharic anything, because Inter declares no Ge'ez range. Putting Ethiopic back
in front would look like a harmless reordering.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bankassist.api import _FONTS

STATIC = Path(__file__).resolve().parent.parent / "bankassist" / "static"
PAGES = ("admin.html", "widget.html")


@pytest.mark.parametrize("name", sorted(_FONTS))
def test_every_allowlisted_font_actually_ships(name: str) -> None:
    """The allowlist and the directory agree.

    A name in the allowlist with no file behind it is a 500 in production for
    a route the browser calls on the first paint.
    """
    path = STATIC / "fonts" / name
    assert path.is_file(), f"{name} is allowlisted but not in static/fonts"
    assert path.stat().st_size > 1024, f"{name} looks truncated"
    # woff2 magic number, so an LFS pointer or a saved HTML error page cannot
    # pass as a font.
    assert path.read_bytes()[:4] == b"wOF2", f"{name} is not a woff2 file"


@pytest.mark.parametrize("name", sorted(_FONTS))
def test_the_route_serves_them(client: TestClient, name: str) -> None:
    r = client.get(f"/fonts/{name}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "font/woff2"
    # Public and immutable, unlike the pages, which are no-store. Nothing here
    # is tenant data, and re-fetching a font on every dashboard load is a cost
    # paid on exactly the connections least able to pay it.
    assert "immutable" in r.headers["cache-control"]
    assert "no-store" not in r.headers.get("cache-control", "")


@pytest.mark.parametrize(
    "name",
    [
        "../api.py",
        "../../.env",
        "....//....//etc/passwd",
        "inter-latin.woff2.bak",
        "",
    ],
)
def test_nothing_else_is_reachable(client: TestClient, name: str) -> None:
    """The allowlist, stated as an attack rather than as a config value."""
    r = client.get(f"/fonts/{name}")
    assert r.status_code in (404, 405), f"/fonts/{name} returned {r.status_code}"


@pytest.mark.parametrize("page", PAGES)
def test_the_files_the_pages_ask_for_are_the_files_that_exist(page: str) -> None:
    """Catches the rename that leaves a stack pointing at nothing."""
    html = (STATIC / page).read_text(encoding="utf-8")
    asked = set(re.findall(r'url\("/fonts/([^"]+)"\)', html))
    assert asked, f"{page} loads no fonts at all"
    assert asked <= _FONTS, f"{page} asks for fonts that are not served: {asked - _FONTS}"


@pytest.mark.parametrize("page", PAGES)
def test_latin_leads_the_stack_and_geez_is_still_in_it(page: str) -> None:
    """The stack says two different things for the two scripts.

    **Inter first**, so Latin stops being drawn with a Ge'ez face's Latin
    glyphs — which is what it was for years, and why the panel read flat.

    **Our Ge'ez copy LAST.** This is the deliberate reversal, on the
    founder's call: the stack that shipped originally named
    `"Noto Sans Ethiopic"` with no `@font-face`, so it fell through to
    whatever the operating system supplies — Nyala on Windows, where most
    Ethiopian desktop users are. Self-hosting replaced that everywhere with a
    monolinear sans, and his verdict was that the original was better. Local
    faces now win; ours is reached only by a machine with no Ethiopic font at
    all, which would otherwise render tofu.

    Promoting our copy back up the list is the regression this guards, and it
    would look like a tidy-up: it costs every Ethiopian reader the face their
    own system chose, and costs them 198 KB to do it.
    """
    html = (STATIC / page).read_text(encoding="utf-8")
    # Both pages carry more than one rule whose selector mentions `body`
    # (widget.html has `html, body { height: 100% }`), so pick the one that
    # actually sets the stack rather than the first one that matches.
    blocks = [
        m.group(1)
        for m in re.finditer(r"(?:^|[\s,])body\s*\{(.*?)\}", html, re.S)
        if "font-family" in m.group(1)
    ]
    assert len(blocks) == 1, f"{page} sets a body font-family in {len(blocks)} rules"
    stack = re.search(r"font-family:([^;]+);", blocks[0], re.S)
    assert stack, f"body in {page} declares no font-family"
    # The stack is commented inline, one script per group — strip those out
    # before splitting, or the first "family" is a comment.
    declared = re.sub(r"/\*.*?\*/", "", stack.group(1), flags=re.S)
    families = [f.strip().strip('"').strip("'") for f in declared.split(",") if f.strip()]

    assert families[0] == "Inter Variable", f"{page} body stack starts with {families[0]}"

    ours = "Noto Sans Ethiopic Variable"
    assert ours in families, f"{page} lost its Ge'ez last resort"
    assert families.index("Inter Variable") < families.index(ours)

    # At least one Ge'ez face the reader's own machine might supply, ahead of
    # ours. Without this the "restore the original" decision is undone.
    system_geez = ["Nyala", "Abyssinica SIL", "Noto Sans Ethiopic", "Ebrima"]
    present = [f for f in system_geez if f in families]
    assert present, f"{page} no longer prefers a system Ge'ez face"
    for face in present:
        assert families.index(face) < families.index(ours), (
            f"{page} puts our bundled Ge'ez ahead of {face} — that is the "
            "self-hosting the founder asked to be reverted"
        )
    assert families[-1] not in system_geez, f"{page} has no generic tail"


@pytest.mark.parametrize("page", PAGES)
def test_each_face_is_range_gated(page: str) -> None:
    """`unicode-range` is the whole reason self-hosting Ge'ez is affordable.

    Without it every session downloads all 331 KB. With it an English session
    downloads 48 KB and an Amharic one downloads what it is about to draw.
    """
    html = (STATIC / page).read_text(encoding="utf-8")
    faces = re.findall(r"@font-face \{(.*?)\}", html, re.S)
    assert len(faces) == len(_FONTS), f"{page} declares {len(faces)} faces"
    for face in faces:
        assert "unicode-range" in face, f"an @font-face in {page} is not range-gated"
        # Fallback text has to be readable while the file is in flight; a
        # blocking font on an Ethiopian mobile connection is a blank panel.
        assert "font-display: swap" in face, f"an @font-face in {page} blocks paint"


def test_inter_ships_its_optical_size_axis() -> None:
    """The regression that made the founder say "not even the same font".

    Inter 4 carries `opsz` 14–32, and `font-optical-sizing: auto` — the CSS
    default — moves a 46px headline onto the DISPLAY cut: tighter, more
    compact, higher contrast. The first build of these fonts shipped
    fontsource's weight-only file, which has no `opsz`, so the hero rendered
    in Inter's TEXT cut scaled up to 46px. Looser, softer, and not the Inter
    anybody recognises from a site that loads it from Google Fonts — which
    does serve the axis.

    Nothing outside the font says which file this is. The filename is ours,
    the CSS is identical either way, and the byte count is a coincidence
    waiting to be optimised away by somebody trimming 23 KB. The `fvar`
    table is the only witness.
    """
    from fontTools.ttLib import TTFont

    for name in ("inter-latin.woff2", "inter-latin-ext.woff2"):
        font = TTFont(STATIC / "fonts" / name)
        axes = {a.axisTag: (a.minValue, a.maxValue) for a in font["fvar"].axes}
        assert "opsz" in axes, (
            f"{name} has no optical-size axis — this is the weight-only build, "
            "and the sign-in headline will render in Inter's text cut"
        )
        assert axes["opsz"][1] >= 32, f"{name} opsz does not reach the display size"
        # Still one file for every weight the panel uses.
        assert axes.get("wght") == (100.0, 900.0), f"{name} lost its weight range"


def test_nothing_disables_optical_sizing() -> None:
    """`font-optical-sizing: none` would waste the axis silently.

    It is the kind of line that gets added to "stop the font looking
    different at different sizes" — which is the feature, not a bug.
    """
    for page in PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")
        assert "font-optical-sizing: none" not in html, f"{page} disables optical sizing"


def test_geez_is_not_set_like_latin() -> None:
    """The other half of the same complaint.

    The hero's `-.025em` tracking, `1.1` leading and `700` weight are tuned
    for Inter at display size, and all three are wrong for Ethiopic: a Ge'ez
    character is a whole syllable whose sidebearings are already minimal, so
    negative tracking crowds it into a grey block, 1.1 leading nearly touches
    on two lines, and 700 fills the counters in.

    Keyed on `:lang()` rather than the panel's language, because the mock
    card cycles languages independently of the interface — which is also why
    both set `lang` from JS.
    """
    html = (STATIC / "admin.html").read_text(encoding="utf-8")
    rule = re.search(
        r"\.stage-line:lang\(am\)[^{]*\{([^}]*)\}", html, re.S
    )
    assert rule, "the Ge'ez headline rule is gone"
    body = rule.group(1)
    assert "letter-spacing: normal" in body, "Ge'ez is being tracked negatively again"
    assert re.search(r"line-height: 1\.[23]", body), "Ge'ez leading is back to Latin's"

    for node in ("stage-line", "mock-thread"):
        assert re.search(rf'\$\("{node}"\)\.lang\s*=', html), (
            f"{node} no longer declares its language, so :lang() cannot match"
        )


def test_the_licences_travel_with_the_fonts() -> None:
    """Both are SIL OFL 1.1, which requires the licence to ship alongside.

    Vendoring a font and leaving its licence behind is the kind of thing a
    customer's legal review finds rather than we do.
    """
    licences = list((STATIC / "fonts").glob("*LICENSE*"))
    assert len(licences) >= 2, "a vendored font is missing its licence"
    for path in licences:
        assert "SIL Open Font License" in path.read_text(encoding="utf-8")


def test_no_page_reaches_out_to_a_font_cdn() -> None:
    """The reason any of this is vendored.

    This runs on a bank's admin panel and inside an iframe on a bank's own
    website. A `fonts.googleapis.com` tag there is an origin their security
    review has to justify, a CSP entry they have to widen, and a round trip to
    a European edge before an Addis dispatcher sees text.
    """
    for page in (*PAGES, "embed.js"):
        text = (STATIC / page).read_text(encoding="utf-8")
        for host in ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit"):
            assert host not in text, f"{page} loads fonts from {host}"
