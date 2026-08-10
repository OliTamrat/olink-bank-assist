"""The admin panel's own labels, in the languages the staff using it speak.

The rule this serves says whatever ships in English ships in all five, and the
admin was the last surface still entirely English. It is lower stakes than the
widget — bank staff rather than customers — but the person who lives in this
screen all day is the teller, and a teller in Bahir Dar reading "Off duty /
Take / End session" in English is being asked to work in a second language for
no reason.

Scoped on purpose to the teller console and the shell around it: the Live
queue, the call room, navigation and the shared buttons. Dashboard, Settings
and Team are still English and tracked. That is a scope decision, not a rule
exemption — and the test below fails if the strings that ARE covered drift out
of any language.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bankassist.i18n import SUPPORTED_LANGUAGES, admin_strings, all_admin_strings

ADMIN_JSON = Path("bankassist/admin_strings.json")
ADMIN_HTML = Path("bankassist/static/admin.html")


def test_every_admin_string_exists_in_every_language() -> None:
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))
    assert set(table) == set(SUPPORTED_LANGUAGES)
    english = set(table["en"])
    assert english
    for lang in SUPPORTED_LANGUAGES:
        assert set(table[lang]) == english, f"{lang} does not match the English keys"


def test_no_language_is_secretly_english() -> None:
    """A table copied from English and never translated passes every
    structural check while shipping nothing at all."""
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))
    for lang in ("am", "om", "ti", "so"):
        identical = [k for k in table["en"] if table[lang][k] == table["en"][k]]
        assert not identical, f"{lang} still English for: {identical[:5]}"


def test_an_unknown_language_falls_back_key_by_key() -> None:
    """Key by key rather than table by table, so a language covering most of
    the console still shows the rest in English instead of dropping back
    wholesale the moment one string is missing."""
    assert admin_strings("zz")["on_duty"] == "On duty"
    assert set(all_admin_strings()) == set(SUPPORTED_LANGUAGES)


def test_identity_carries_the_labels(client: TestClient, demo_bank: Any) -> None:
    """Sent with the identity the panel already fetches on boot, so switching
    language mid-shift costs nothing."""
    body = client.get("/banks/demo/public").json()
    assert "ui" in body  # widget strings, unchanged
    # The admin table rides on /me, which needs a signed-in user; the loader
    # itself is what this pins.
    assert all_admin_strings()["am"]["nav_live_queue"] != "Live queue"


def test_the_nav_reads_from_the_table() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "function A(key, fallback)" in html
    assert "A(p.key, p.label)" in html
    # Every nav entry carries a key, or its label can never be translated.
    assert html.count('key: "nav_') >= 11


def test_the_duty_toggle_is_translated() -> None:
    """The control a teller touches most, and the one that was hardest to
    justify leaving in English."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert 'A("on_duty")' in html
    assert 'A("off_duty")' in html
    assert '"On duty" : "Off duty"' not in html


def test_the_picker_is_wired_once_not_per_session() -> None:
    """The node lives in the page shell and outlives any sign-in, so binding
    per session would stack handlers."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "wireAdminLanguage" in html
    assert html.count('getElementById("adminLang")') == 1


def test_changing_language_repaints_the_chrome() -> None:
    """Otherwise the picker changes the next page load and leaves every label
    already on screen in the old language — which is what the widget's picker
    did before it was fixed."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "paintAdminChrome" in html
    block = html.split("function setAdminLanguage")[1].split("var PAGES")[0]
    assert "renderNav()" in block
    assert "paintAdminChrome()" in block


# ------------------------------------------------ what the browser caught
#
# Both of these passed every structural test above and broke the moment the
# page was actually opened. They are the argument for driving a UI change in a
# browser rather than trusting that the strings file is well formed.


def test_the_labels_need_no_sign_in(client: TestClient) -> None:
    """Interface strings contain nothing about a tenant, a customer or a
    person. They were originally hung off the signed-in identity, and the
    break-glass token path has no user — so the sidebar rendered raw key
    names. A label table that only works once you are signed in fails on the
    screen most likely to be reached in a hurry."""
    resp = client.get("/admin/strings")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == set(SUPPORTED_LANGUAGES)
    assert body["am"]["nav_live_queue"] != "Live queue"


def test_a_missing_label_falls_back_to_english_not_the_key_name() -> None:
    """The first browser run put "nav_dashboard" in the sidebar. The key name
    is the last resort, not the second — a nav reading in key names is more
    broken than a nav reading in English."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "function A(key, fallback)" in html
    assert "fallback || key" in html


def test_the_language_switch_calls_the_function_that_exists() -> None:
    """The first run threw "showPage is not defined" — the page-open function
    is go(). A reference error there silently stops the repaint half way,
    which is exactly what a string-table test cannot see."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    block = html.split("function setAdminLanguage")[1].split("var PAGES")[0]
    assert "go(state.page)" in block
    assert "showPage(" not in block
