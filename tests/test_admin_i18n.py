"""The admin panel's own labels, in the languages the staff using it speak.

The rule this serves says whatever ships in English ships in all five, and the
admin was the last surface still entirely English. It is lower stakes than the
widget — bank staff rather than customers — but the person who lives in this
screen all day is the teller, and a teller in Bahir Dar reading "Off duty /
Take / End session" in English is being asked to work in a second language for
no reason.

Originally scoped to the teller console and the shell around it. Dashboard,
Settings and Team followed, so every page of the panel now reads in all five.

What is deliberately NOT translated, so the gap is a decision on the record
rather than an oversight: role names and role descriptions (they come from the
database per tenant, and translating them is a server-side job), permission
identifiers like `documents.write` (they are identifiers, not prose), channel
names, and anything a customer actually typed.
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
    for lang in ("am", "om", "ti", "so", "sw"):
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
    assert "function A(key, fallback" in html
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
    assert "function A(key, fallback" in html
    assert "fallback || key" in html


def test_the_language_switch_calls_the_function_that_exists() -> None:
    """The first run threw "showPage is not defined" — the page-open function
    is go(). A reference error there silently stops the repaint half way,
    which is exactly what a string-table test cannot see."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    block = html.split("function setAdminLanguage")[1].split("var PAGES")[0]
    assert "go(state.page)" in block
    assert "showPage(" not in block


# ------------------------------------------------- the rest of the panel
#
# Dashboard, Settings and Team were the last English-only pages. The work
# turned up two structural problems that a string table cannot express, and
# both are pinned below: sentences assembled from fragments, and a heading
# that never followed the language because only the nav had been wired.


def test_the_dashboard_pages_are_translated_too() -> None:
    """A spot check per page. Not exhaustive — the browser drive is what
    proves coverage — but enough that deleting the wiring fails here."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for key in (
        "questions_asked", "resolved_without_person", "conversations_per_day",
        "most_asked", "recent_activity", "live_preview",       # dashboard
        "branding", "escalation_webhook", "change_password",    # settings
        "add_person", "what_each_role_can_do", "temp_password_help",  # team
    ):
        assert f'A("{key}"' in html, f"{key} is in the table but nothing renders it"


def test_no_sentence_is_assembled_from_fragments() -> None:
    """The bug this class of change hides.

    `"All " + n + " " + unit + " " + verb + " " + label` reads correctly only
    in a language that happens to use the English order, and three of the five
    here do not. Both one-line summaries take a whole template with {n} and
    {label} in it, so a translator can put the verb where their language puts
    it. The old `verb:` option is gone; if it comes back, so has the bug.
    """
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "verb:" not in html, "a sentence is being built from a verb fragment again"
    for key in ("donut_all_in", "channel_all_from"):
        template = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))["en"][key]
        assert "{n}" in template and "{label}" in template


def test_placeholders_survive_every_translation() -> None:
    """A dropped {n} does not fail loudly — it renders the literal text
    "{n} escalations waiting" to a bank."""
    import re

    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))
    for key, english in table["en"].items():
        want = set(re.findall(r"\{(\w+)\}", english))
        for lang in SUPPORTED_LANGUAGES:
            got = set(re.findall(r"\{(\w+)\}", table[lang][key]))
            assert got == want, f"{key} [{lang}]: placeholders {got} != {want}"


def test_the_page_heading_follows_the_language() -> None:
    """Found by driving the panel, not by reading it. The sidebar entry was
    translated and the heading beside it was not, so an Amharic panel read
    "ዳሽቦርድ" in the rail and "Dashboard" in the topbar."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert "A(page.key, page.label)" in html
    assert 'textContent = chan ? chan.name : page.label' not in html


def test_a_placeholder_interpolates() -> None:
    """A() grew a third argument for this; without it every sentence with a
    number in it goes back to being three fragments."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    block = html.split("function A(key, fallback")[1].split("function setAdminLanguage")[0]
    assert 'split("{" + name + "}")' in block


def test_every_key_the_panel_asks_for_actually_exists() -> None:
    """A typo in an A() key does not fail — it renders the key name into the
    interface. That shipped once as "nav_dashboard" in the sidebar, and a
    stale table did it again with "donut_all_in_one" mid-sentence.

    Only literal single-argument keys are checkable here; the handful built by
    concatenation (`"outcome_" + r.outcome`) are covered by their own label
    tests, which assert the map and the agent agree.
    """
    import re

    html = ADMIN_HTML.read_text(encoding="utf-8")
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))["en"]
    asked = set(re.findall(r'\bA\(\s*"([a-z0-9_]+)"\s*[,)]', html))
    missing = sorted(asked - set(table))
    assert not missing, f"admin.html asks for keys the table does not have: {missing}"


def test_no_key_is_translated_and_then_never_used() -> None:
    """The direction nothing was checking.

    `test_every_key_the_panel_asks_for_actually_exists` covers asked → exists,
    and caught a typo. Nothing covered exists → asked, and that is how the
    teller console ended up with twenty-seven strings translated into five
    languages and wired to nothing: the table was complete, the review sheet
    showed full coverage, and the console still said "Connecting…" and
    "Session taken" in English mid-call.

    A key nobody reads is worse than a missing one. It costs a reviewer real
    time, and it makes the coverage number a lie.
    """
    import re

    html = ADMIN_HTML.read_text(encoding="utf-8")
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))["en"]
    # Any quoted appearance counts — keys reach A() indirectly too, through
    # `A(p.key)`, a ternary, or a lookup table.
    quoted = set(re.findall(r'"([a-z0-9_]+)"', html))
    prefixes = set(re.findall(r'\bA\(\s*"([a-z0-9_]+_)"\s*\+', html))
    orphans = sorted(
        k for k in table
        if k not in quoted and not any(k.startswith(p) for p in prefixes)
    )
    assert not orphans, (
        f"translated into five languages and never rendered: {orphans}. "
        "Either wire them up or delete them."
    )


def test_the_fayda_name_is_never_translated() -> None:
    """Fayda is the name of Ethiopia's digital ID, not a word.

    A product name does not get translated — the same rule that leaves
    Telegram and WhatsApp alone. In Latin-script languages it stays "Fayda"
    literally; in Amharic and Tigrinya it is written ፋይዳ, which is the same
    name in the script the reader uses and the form the National ID Program
    itself publishes. Only the words AROUND it — number, ID, matches — are
    translated.

    Pinned because the failure is silent and embarrassing: a teller told to
    check a document whose name they will not find printed on it.
    """
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))
    names = ("Fayda", "ፋይዳ")
    carriers = [k for k, v in table["en"].items() if "Fayda" in v]
    assert carriers, "no string mentions Fayda — did the identity panel move?"
    for key in carriers:
        for lang in SUPPORTED_LANGUAGES:
            value = table[lang][key]
            assert any(n in value for n in names), (
                f"{key} [{lang}] lost the Fayda name: {value!r}"
            )
