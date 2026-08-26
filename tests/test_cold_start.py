"""The first five minutes of a tenant's life.

A fresh tenant's dashboard was honest and useless. Every number nulled or
zeroed, every card saying "nothing yet", and nowhere on the screen the one
fact that decided whether the product worked at all: **this bank has no
knowledge base, so the assistant can answer nothing.** The Live Preview sat
underneath offering "How do I open an account?" — the exact question it could
not answer.

None of that is visible from an API test, which is why it survived: every
endpoint was correct, and the screen built from them still told a bank
nothing. It was found by signing in to an empty tenant in a browser.

The rules these tests hold:

- the card is keyed on **data**, not on a date, and not on the dashboard's
  7/30/90-day window — an established tenant with a quiet month must never get
  its onboarding back;
- it **retires itself** on the first real customer conversation, so there is
  no dismissal state to persist and nothing to forget to clear;
- **preview traffic cannot retire it** (ADR-0036), which is the whole reason
  `live` can be trusted: a staff member testing the widget is not a bank going
  live.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import create_user
from fastapi.testclient import TestClient

from bankassist.models import Bank

ADMIN_HTML = Path(__file__).resolve().parents[1] / "bankassist" / "static" / "admin.html"
ADMIN_JSON = Path(__file__).resolve().parents[1] / "bankassist" / "admin_strings.json"

PW = "Passw0rd!2345"

# Every step the card can show. Keeping the list here rather than importing it
# means a step renamed in one place and not the other fails loudly.
STEPS = ("knowledge", "brand", "channels", "team")


def _admin(client: TestClient, demo_bank: Any) -> TestClient:
    create_user(client, demo_bank, "boss@demo.et", password=PW, role="admin")
    r = client.post(
        "/admin/api/demo/login", json={"email": "boss@demo.et", "password": PW}
    )
    assert r.status_code == 200, r.text
    return client


def _setup(client: TestClient) -> dict[str, Any]:
    r = client.get("/admin/api/demo/setup")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_the_setup_report_names_every_step(client: TestClient, demo_bank: Any) -> None:
    _admin(client, demo_bank)
    keys = [step["key"] for step in _setup(client)["steps"]]
    assert keys == list(STEPS), "the steps changed shape; the card renders these by key"


def test_an_empty_tenant_is_not_live(client: TestClient, bare_bank: Any) -> None:
    """The card's entire gate. A tenant nobody has written to is not live."""
    create_user(client, bare_bank, "boss@bare.et", password=PW, role="admin", slug="bare")
    client.post("/admin/api/bare/login", json={"email": "boss@bare.et", "password": PW})
    r = client.get("/admin/api/bare/setup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is False
    assert body["complete"] is False
    knowledge = [s for s in body["steps"] if s["key"] == "knowledge"][0]
    assert knowledge["done"] is False
    assert knowledge["count"] == 0


def test_a_real_customer_retires_the_card(client: TestClient, demo_bank: Any) -> None:
    """One conversation from an actual customer and onboarding is over."""
    _admin(client, demo_bank)
    assert _setup(client)["live"] is False

    r = client.post("/chat/demo", json={"message": "How do I open an account?"})
    assert r.status_code == 200, r.text

    assert _setup(client)["live"] is True


def test_preview_traffic_does_not_retire_the_card(
    client: TestClient, demo_bank: Any
) -> None:
    """The reason `live` is worth trusting.

    A staff member trying the Live Preview is the most likely first traffic a
    tenant ever sees. If that counted, the card would vanish for exactly the
    person it was written for, on their first click.
    """
    _admin(client, demo_bank)
    cid = client.post("/admin/api/demo/preview/conversation").json()["conversation_id"]
    r = client.post("/chat/demo", json={"message": "test", "conversation_id": cid})
    assert r.status_code == 200, r.text

    assert _setup(client)["live"] is False, (
        "the preview retired the setup card — a staff member testing the "
        "widget is not a bank going live"
    )


def test_documents_complete_the_knowledge_step(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    _admin(client, demo_bank)
    knowledge = [s for s in _setup(client)["steps"] if s["key"] == "knowledge"][0]
    assert knowledge["done"] is True, "the demo tenant is seeded; this should be done"
    assert knowledge["count"] > 0


def test_branding_is_measured_against_the_column_default(
    client: TestClient, bare_bank: Any, db_session: Any
) -> None:
    """Not against a literal copied into the endpoint.

    A hard-coded "#0f766e" here and a changed default in models.py would agree
    with nothing, and the step would read done for every tenant that had never
    touched its colour.
    """
    create_user(client, bare_bank, "boss@bare.et", password=PW, role="admin", slug="bare")
    client.post("/admin/api/bare/login", json={"email": "boss@bare.et", "password": PW})

    brand = [
        s for s in client.get("/admin/api/bare/setup").json()["steps"]
        if s["key"] == "brand"
    ][0]
    assert brand["done"] is False

    bank = db_session.query(Bank).filter_by(slug="bare").one()
    bank.primary_color = "#1a5c3a"
    db_session.commit()

    brand = [
        s for s in client.get("/admin/api/bare/setup").json()["steps"]
        if s["key"] == "brand"
    ][0]
    assert brand["done"] is True


def test_the_window_never_moves_the_gate(client: TestClient, demo_bank: Any) -> None:
    """`live` is all-time on purpose.

    Read from the dashboard's own 7/30/90-day window, a tenant that had been
    running for a year and had a quiet fortnight would be handed its
    onboarding checklist back.
    """
    _admin(client, demo_bank)
    client.post("/chat/demo", json={"message": "How do I open an account?"})
    # The setup route takes no window parameter at all, and one handed to it
    # must not change the answer.
    assert client.get("/admin/api/demo/setup?days=1").json()["live"] is True


def test_setup_needs_a_signed_in_person(client: TestClient) -> None:
    assert client.get("/admin/api/demo/setup").status_code in (401, 403)


# ----------------------------------------------------------------- the card


def test_the_card_is_gated_on_being_able_to_act_on_it() -> None:
    """A checklist of things you cannot do is worse than no checklist."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert 'can("documents.write")' in html
    body = html.split("function setupCard(")[1].split("\nfunction ")[0]
    assert "setup.live" in body, "the card must retire itself when the tenant is live"
    assert 'can("documents.write")' in body, "the card must not render for a bystander"


def test_every_step_has_a_destination_and_a_string() -> None:
    """A row that names a task and offers nowhere to do it is a dead end."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))["en"]
    registry = html.split("var SETUP_STEPS = [")[1].split("];")[0]
    for key in STEPS:
        assert f'key: "{key}"' in registry, f"{key} has no destination in SETUP_STEPS"
        assert f"setup_{key}" in table, f"setup_{key} is missing from the string table"
        assert f"setup_{key}_help" in table, f"setup_{key}_help is missing"


def test_the_card_is_translated_everywhere() -> None:
    """The multilingual golden rule: six languages in the same change."""
    from bankassist.i18n import SUPPORTED_LANGUAGES

    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))
    keys = ["setup_title", "setup_sub", "setup_progress", "setup_open", "setup_step_done"]
    keys += [f"setup_{k}" for k in STEPS] + [f"setup_{k}_help" for k in STEPS]
    for lang in SUPPORTED_LANGUAGES:
        for key in keys:
            assert key in table[lang], f"{key} missing for {lang}"
            assert table[lang][key].strip(), f"{key} is blank for {lang}"


def test_the_progress_line_is_a_template_not_a_sum_of_fragments() -> None:
    """`n + " of " + total` only reads correctly in English word order."""
    table = json.loads(ADMIN_JSON.read_text(encoding="utf-8"))["en"]
    assert "{done}" in table["setup_progress"]
    assert "{total}" in table["setup_progress"]


# ------------------------------------------------------------- the day chart


def test_an_all_zero_series_reads_as_empty() -> None:
    """The chart was the only card that rendered a void instead of a sentence.

    The backend fills the window so every day has a bar, so a fresh tenant got
    thirty zero-count days — a non-empty array — and the old `!daily.length`
    guard let it through to draw ~500px of nothing under a date axis.
    """
    import re

    html = ADMIN_HTML.read_text(encoding="utf-8")
    body = html.split("function dayBars(")[1].split("\nfunction ")[0]
    # Comments explain the old check by name, so compare against code only.
    code = re.sub(r"//.*", "", body)
    assert "if (!max)" in code, (
        "dayBars must decide emptiness from the values, not from the length "
        "of a series the backend always fills"
    )
    assert "!daily.length" not in code, "the length check is the bug, not the guard"
