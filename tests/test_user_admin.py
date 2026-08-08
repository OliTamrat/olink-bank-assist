"""Managing colleagues: listing, disabling, restoring, and the role table."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankassist import permissions
from bankassist.models import AdminSession, User

_FIXTURE = "pytest-fixture-value"
PW = f"{_FIXTURE}-original"


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _make_user(
    client: TestClient, bank: Any, email: str, role: str = "operator"
) -> dict[str, Any]:
    resp = client.post(
        "/admin/api/demo/users",
        headers=_headers(bank),
        json={"email": email, "password": PW, "role": role},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _signed_in(client: TestClient, bank: Any, email: str, role: str) -> TestClient:
    _make_user(client, bank, email, role)
    c = TestClient(client.app)
    assert c.post(
        "/admin/api/demo/login", json={"email": email, "password": PW}
    ).status_code == 200
    return c


def test_the_list_includes_disabled_people(
    client: TestClient, demo_bank: Any
) -> None:
    """"Who can get in here" is the question this screen answers.

    An answer that silently omits removed accounts is the wrong answer: an
    access review needs to see that someone was removed, not find no trace.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    gone = _make_user(client, demo_bank, "leaver@bank.et")
    admin.post(f"/admin/api/demo/users/{gone['id']}/active", json={"is_active": False})

    rows = admin.get("/admin/api/demo/users").json()
    by_email = {r["email"]: r for r in rows}
    assert "leaver@bank.et" in by_email
    assert by_email["leaver@bank.et"]["is_active"] is False
    assert by_email["boss@bank.et"]["is_active"] is True


def test_the_list_marks_which_row_is_you(
    client: TestClient, demo_bank: Any
) -> None:
    """So the UI can grey out an action that would always be refused."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    _make_user(client, demo_bank, "someone@bank.et")
    rows = {r["email"]: r for r in admin.get("/admin/api/demo/users").json()}
    assert rows["boss@bank.et"]["is_you"] is True
    assert rows["someone@bank.et"]["is_you"] is False


def test_disabling_someone_ends_their_sessions_immediately(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Removing someone is the whole feature. A delay would be theatre."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    victim = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert victim.get("/admin/api/demo/handoffs").status_code == 200

    target = db_session.execute(
        select(User).where(User.email == "ops@bank.et")
    ).scalar_one()
    resp = admin.post(
        f"/admin/api/demo/users/{target.id}/active", json={"is_active": False}
    )
    assert resp.status_code == 200
    assert resp.json()["sessions_revoked"] == 1

    assert victim.get("/admin/api/demo/handoffs").status_code == 401
    live = db_session.execute(
        select(AdminSession).where(
            AdminSession.user_id == target.id, AdminSession.revoked_at.is_(None)
        )
    ).scalars().all()
    assert live == []


def test_restoring_someone_lets_them_sign_in_again(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Disabled is not deleted — the row survives so audit entries resolve."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    back = _make_user(client, demo_bank, "returner@bank.et")
    admin.post(f"/admin/api/demo/users/{back['id']}/active", json={"is_active": False})

    fresh = TestClient(client.app)
    assert fresh.post(
        "/admin/api/demo/login", json={"email": "returner@bank.et", "password": PW}
    ).status_code == 401

    admin.post(f"/admin/api/demo/users/{back['id']}/active", json={"is_active": True})
    assert fresh.post(
        "/admin/api/demo/login", json={"email": "returner@bank.et", "password": PW}
    ).status_code == 200


def test_you_cannot_disable_yourself(client: TestClient, demo_bank: Any) -> None:
    """The realistic mistake is the only admin locking themselves out mid-task."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    me = admin.get("/admin/api/demo/users").json()
    mine = next(r for r in me if r["is_you"])
    resp = admin.post(
        f"/admin/api/demo/users/{mine['id']}/active", json={"is_active": False}
    )
    assert resp.status_code == 409
    assert admin.get("/admin/api/demo/handoffs").status_code == 200


def test_a_user_from_another_bank_is_not_found_here(
    client: TestClient, demo_bank: Any, second_bank: Any, db_session: Session
) -> None:
    """A raw id must not be a way around the tenant boundary."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    stranger = User(bank_id=second_bank.id, email="x@other.et", role_id="irrelevant")
    # Inserted directly: the API cannot create a user for a bank you are not in,
    # which is the point — this checks the lookup, not the creation path.
    db_session.add(stranger)
    db_session.flush()
    resp = admin.post(
        f"/admin/api/demo/users/{stranger.id}/active", json={"is_active": False}
    )
    assert resp.status_code == 404


def test_an_operator_cannot_see_or_change_the_team(
    client: TestClient, demo_bank: Any
) -> None:
    ops = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert ops.get("/admin/api/demo/users").status_code == 403
    assert ops.get("/admin/api/demo/roles").status_code == 403


def test_the_role_table_is_generated_from_what_is_enforced(
    client: TestClient, demo_bank: Any
) -> None:
    """Not a hand-written help page.

    It reads the same rows `require()` checks, so it cannot describe a policy
    the system is not actually applying — which is the failure mode of every
    permissions matrix kept in a document.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    rows = {r["name"]: r for r in admin.get("/admin/api/demo/roles").json()}
    assert set(rows) == {"operator", "admin"}
    assert set(rows["admin"]["permissions"]) == set(permissions.ALL)
    assert permissions.Perm.DOCUMENTS_WRITE not in rows["operator"]["permissions"]
    assert rows["operator"]["is_builtin"] is True


def test_integration_settings_show_state_but_never_secrets(
    client: TestClient, demo_bank: Any
) -> None:
    """The screen must show what is wired up, and nothing that could forge it.

    The settings page shipped with empty fields whether or not anything was
    connected. That is worse than unhelpful on this particular page: the one
    control on it decides where customers' names and phone numbers are
    delivered, and someone who cannot see the current value can disconnect it
    by saving a field they believed was already blank.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")

    before = admin.get("/admin/api/demo/integrations").json()
    assert before["handoff_webhook"]["connected"] is False
    assert before["handoff_webhook"]["url"] is None

    created = admin.post(
        "/admin/api/demo/handoff-webhook",
        json={"url": "https://contact-centre.example/hooks/olink"},
    ).json()
    secret = created["secret"]

    after = admin.get("/admin/api/demo/integrations")
    body = after.json()
    assert body["handoff_webhook"]["connected"] is True
    assert body["handoff_webhook"]["url"] == "https://contact-centre.example/hooks/olink"
    assert body["handoff_webhook"]["has_secret"] is True
    # The signing secret is issued once and never readable again — a value the
    # API will re-display is a value that ends up in a screenshot.
    assert secret not in after.text


def test_an_operator_cannot_read_the_integration_settings(
    client: TestClient, demo_bank: Any
) -> None:
    """It names where customer contact details are sent."""
    ops = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert ops.get("/admin/api/demo/integrations").status_code == 403


def test_every_supported_language_is_listed_even_at_zero(
    client: TestClient, demo_bank: Any
) -> None:
    """A language missing from the panel reads as unsupported, not unused.

    CBE's live dashboard showed English and Afaan Oromo only, and the obvious
    reading of that is that the assistant does not do Amharic — which is the
    opposite of true. Zero here is a real count, not a rate with no
    denominator, so stating it is a fact rather than an implied failure.
    """
    from bankassist.i18n import SUPPORTED_LANGUAGES

    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    a = admin.get("/admin/api/demo/analytics?days=30").json()
    listed = {row["language"] for row in a["languages"]}
    assert set(SUPPORTED_LANGUAGES) <= listed
    for row in a["languages"]:
        assert row["name"], f"{row['language']} has no display name"


def test_conversations_can_be_narrowed_by_language_and_channel(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """So a figure on the dashboard can be opened rather than taken on trust."""
    from bankassist.models import Conversation

    db_session.add_all([
        Conversation(bank_id=demo_bank.id, channel="widget", language="am"),
        Conversation(bank_id=demo_bank.id, channel="telegram", language="en"),
    ])
    db_session.commit()

    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    am = admin.get("/admin/api/demo/conversations?language=am").json()
    assert am and all(c["language"] == "am" for c in am)
    tg = admin.get("/admin/api/demo/conversations?channel=telegram").json()
    assert tg and all(c["channel"] == "telegram" for c in tg)


def test_branding_rejects_anything_that_is_not_a_colour(
    client: TestClient, demo_bank: Any
) -> None:
    """The value is interpolated into a CSS custom property in the widget.

    An unchecked string there is stylesheet injection on the bank's own site,
    which is why this is validated rather than trusted to a colour picker that
    only exists in our own admin page.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    bad = admin.put(
        "/admin/api/demo/branding",
        json={"primary_color": "red; background:url(//evil)", "logo_url": None},
    )
    assert bad.status_code == 422

    http_logo = admin.put(
        "/admin/api/demo/branding",
        json={"primary_color": "#722282", "logo_url": "http://insecure.example/l.png"},
    )
    assert http_logo.status_code == 422

    ok = admin.put(
        "/admin/api/demo/branding",
        json={"primary_color": "#722282", "logo_url": "https://cbe.example/logo.png"},
    )
    assert ok.status_code == 200
    assert ok.json()["primary_color"] == "#722282"
    # And it reaches the public endpoint the widget reads.
    pub = client.get("/banks/demo/public").json()
    assert pub["primary_color"] == "#722282"


def test_an_operator_cannot_restyle_the_banks_widget(
    client: TestClient, demo_bank: Any
) -> None:
    ops = _signed_in(client, demo_bank, "ops@bank.et", "operator")
    assert ops.put(
        "/admin/api/demo/branding", json={"primary_color": "#000000"}
    ).status_code == 403


def test_the_brand_name_is_shown_and_the_registered_name_is_kept(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """Both names, used in different places, because both are needed.

    A straight rename would have been wrong in both directions: the registered
    name does not fit a chat header and is not what anybody calls the bank,
    while the short name on a printed report or inside the model's prompt
    throws away precision exactly where it is wanted.
    """
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    resp = admin.put(
        "/admin/api/demo/branding",
        json={"primary_color": "#722282", "short_name": "CBE"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "CBE"

    # The widget and the panel read this, and both want the brand.
    pub = client.get("/banks/demo/public").json()
    assert pub["name"] == "CBE"
    assert pub["legal_name"] == demo_bank.name

    # The printed report leads with the brand and keeps the registered name.
    a = admin.get("/admin/api/demo/analytics?days=30").json()
    assert a["bank_name"] == "CBE"
    assert a["bank_legal_name"] == demo_bank.name


def test_clearing_the_brand_name_falls_back_to_the_registered_one(
    client: TestClient, demo_bank: Any
) -> None:
    """A bank whose full name is what people say needs nothing set."""
    admin = _signed_in(client, demo_bank, "boss@bank.et", "admin")
    admin.put("/admin/api/demo/branding",
              json={"primary_color": "#722282", "short_name": "CBE"})
    admin.put("/admin/api/demo/branding",
              json={"primary_color": "#722282", "short_name": "   "})
    assert client.get("/banks/demo/public").json()["name"] == demo_bank.name


def test_the_assistant_recognises_both_names_as_this_bank(
    client: TestClient, demo_bank: Any, db_session: Session
) -> None:
    """A customer types "CBE"; a comparison question spells it out in full.

    Recognising only one of them means the other reads as a rival bank being
    asked about, which routes the turn down the comparison path.
    """
    from bankassist.agent import _bank_aliases

    demo_bank.short_name = "CBE"
    db_session.commit()
    aliases = _bank_aliases(demo_bank)
    assert "CBE" in aliases
    assert demo_bank.name in aliases
    assert demo_bank.slug in aliases
