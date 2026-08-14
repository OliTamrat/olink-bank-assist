"""SMS — the channel with no single vendor, and the only one that costs money.

Both facts drive the tests. No single vendor means the inbound parser has to
be generous about field names and strict about authentication. Costing money
per reply means a long answer must not quietly become a dozen billed segments.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import sms

SECRET = "sms-inbound-secret"
HEADERS = {"X-SMS-Secret": SECRET}


@pytest.fixture()
def wired(
    client: TestClient, cbe_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str]]:
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.sms_inbound_secret = SECRET
    bank.sms_send_url = "https://gateway.example/send"
    bank.sms_auth_header = "Bearer gw-token"
    bank.sms_sender_id = "CBE"
    db_session.commit()

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        api_module.sms, "send_message",
        lambda **kw: sent.append((kw["to"], kw["text"])) or True,
    )
    return sent


# ----------------------------------------------------------- authentication


def test_a_request_with_no_secret_is_refused(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """An SMS webhook that anyone can post to means anyone can make the bank's
    assistant send billed messages to any number they name."""
    resp = client.post("/webhooks/sms/cbe", data={"from": "251911", "text": "hi"})
    assert resp.status_code == 403
    assert wired == []


def test_a_wrong_secret_is_refused(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    resp = client.post(
        "/webhooks/sms/cbe",
        data={"from": "251911", "text": "hi"},
        headers={"X-SMS-Secret": "nope"},
    )
    assert resp.status_code == 403


def test_an_unconfigured_bank_accepts_nothing(
    client: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """Fails closed: no secret set must mean no traffic, not no check."""
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.sms_inbound_secret = None
    db_session.commit()
    resp = client.post(
        "/webhooks/sms/cbe", data={"from": "251911", "text": "hi"},
        headers={"X-SMS-Secret": ""},
    )
    assert resp.status_code == 403


# ------------------------------------------------------------------ inbound


def test_a_form_post_is_answered(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    resp = client.post(
        "/webhooks/sms/cbe",
        data={"from": "251911000000", "text": "What are your savings rates?"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert wired, "a valid inbound SMS produced no reply"
    assert wired[-1][0] == "251911000000"


def test_a_json_post_is_answered_too(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    """Aggregators split roughly evenly between form posts and JSON, and which
    one a vendor uses is not something we get to choose."""
    resp = client.post(
        "/webhooks/sms/cbe",
        json={"msisdn": "251911000000", "message": "Hello"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert wired


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"from": "2519", "text": "hi"}, ("2519", "hi")),
        ({"msisdn": "2519", "message": "hi"}, ("2519", "hi")),
        ({"sender": "2519", "body": "hi"}, ("2519", "hi")),
        ({"originator": "2519", "content": "hi"}, ("2519", "hi")),
        ({"nothing": "useful"}, (None, None)),
    ],
)
def test_vendor_field_names_are_accepted_generously(
    payload: dict[str, Any], expected: tuple[str | None, str | None]
) -> None:
    """Being strict here would mean a channel that works for one contract."""
    assert sms.parse_inbound(payload) == expected


def test_a_delivery_report_with_no_text_is_not_a_question(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    resp = client.post(
        "/webhooks/sms/cbe",
        data={"from": "251911000000", "status": "delivered"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert wired == []


# -------------------------------------------------------- billing behaviour


def test_a_short_reply_is_one_unnumbered_part() -> None:
    """Most replies fit. "(1/1)" on all of them would look broken."""
    assert sms.segments("Our savings rate is 7%.") == ["Our savings rate is 7%."]


def test_a_long_reply_is_split_and_numbered() -> None:
    """Parts can arrive out of order, and an unlabelled second half of an
    answer about a fee is worse than no answer."""
    parts = sms.segments("x" * 400)
    assert len(parts) > 1
    assert parts[0].endswith(f"(1/{len(parts)})")
    assert all(len(p) <= sms.PART_CHARS for p in parts)


def test_a_runaway_answer_is_capped_and_says_so() -> None:
    """The money test. Without a ceiling, one long retrieval answer bills the
    bank for a dozen segments to a single customer — and it would be billed
    quietly, because nothing in a successful send reports its own cost."""
    parts = sms.segments("x" * 10_000)
    assert len(parts) == sms.MAX_PARTS
    assert parts[-1].startswith("x")
    assert "…" in parts[-1], "a truncated answer must not read as a complete one"


def test_a_failed_segment_stops_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    """If part one did not arrive, parts two and three are noise the bank pays
    for."""
    import httpx

    calls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(kwargs["json"]["text"])
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr(httpx, "post", fake_post)
    ok = sms.send_message(
        send_url="https://gateway.example/send", auth_header="Bearer x",
        to="251911", text="x" * 600, sender_id="CBE",
    )
    assert ok is False
    assert len(calls) == 1, "kept sending after the first segment failed"


def test_no_gateway_configured_is_a_logged_failure_not_a_crash() -> None:
    assert sms.send_message(
        send_url="", auth_header="", to="251911", text="hi", sender_id="CBE"
    ) is False


# ---------------------------------------------------------------- disclaimer


def test_the_disclaimer_leads_on_sms_as_well(
    client: TestClient, cbe_bank: Any, wired: list[Any]
) -> None:
    client.post(
        "/webhooks/sms/cbe",
        data={"from": "251911000000", "text": "What are your savings rates?"},
        headers=HEADERS,
    )
    assert wired[0][1] == cbe_bank.disclaimer


# ------------------------------------------------------------- connecting it
#
# The gateway's API key is the one field on this form that cannot be read back
# — `/integrations` returns whether one exists, never what it is. So a blank
# box means "I did not touch this", and reading it as "clear it" would let
# somebody drop the key by renaming the sender ID. That failure does not show
# up on save; it shows up on the next customer's message.


_PW = "pytest-fixture-value-7"


@pytest.fixture()
def boss(client: TestClient, cbe_bank: Any) -> TestClient:
    from conftest import create_user

    create_user(client, cbe_bank, "boss@cbe.test", password=_PW, role="admin",
                slug=cbe_bank.slug)
    signed_in = client.post(f"/admin/api/{cbe_bank.slug}/login",
                            json={"email": "boss@cbe.test", "password": _PW})
    assert signed_in.status_code == 200, signed_in.text
    return client


def _reload(db: Any, bank_id: str) -> Any:
    from bankassist.models import Bank

    db.expire_all()
    return db.get(Bank, bank_id)


def _sms_connect(client: TestClient, **body: Any) -> Any:
    return client.post("/admin/api/cbe/sms/connect", json=body)


def test_an_omitted_auth_header_keeps_the_stored_one(
    boss: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    _sms_connect(boss, send_url="https://gw.example/send",
                 auth_header="Bearer secret-key", sender_id="CBE")
    _sms_connect(boss, send_url="https://gw.example/send", sender_id="CBE BANK")

    bank = _reload(db_session, cbe_bank.id)
    assert bank.sms_auth_header == "Bearer secret-key"
    assert bank.sms_sender_id == "CBE BANK"


def test_an_explicit_empty_auth_header_clears_it(
    boss: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """Omitted and empty have to mean different things, or there is no way
    back for a gateway that stops needing authentication."""
    _sms_connect(boss, send_url="https://gw.example/send", auth_header="Bearer k")
    _sms_connect(boss, send_url="https://gw.example/send", auth_header="")

    assert _reload(db_session, cbe_bank.id).sms_auth_header is None


def test_the_inbound_secret_is_returned_once_and_never_read_back(
    boss: TestClient, cbe_bank: Any
) -> None:
    """The connect response is the only place it appears. `/integrations` says
    a secret exists so the panel can be honest, and nothing more — the screen
    that could re-display it is the screen it leaks from."""
    first = _sms_connect(boss, send_url="https://gw.example/send").json()
    assert first["inbound_secret"]

    cfg = boss.get("/admin/api/cbe/integrations").json()["sms"]
    assert cfg["has_secret"] is True
    assert first["inbound_secret"] not in json.dumps(cfg)


def test_reconnecting_keeps_the_same_inbound_secret(
    boss: TestClient, cbe_bank: Any
) -> None:
    """It lives in the aggregator's dashboard. Minting a new one because
    somebody corrected the send URL would silently refuse every inbound SMS."""
    first = _sms_connect(boss, send_url="https://gw.example/send").json()
    again = _sms_connect(boss, send_url="https://gw.example/v2/send").json()
    assert first["inbound_secret"] == again["inbound_secret"]


def test_the_panel_can_say_whether_an_auth_header_is_set(
    boss: TestClient, cbe_bank: Any
) -> None:
    """So "leave blank to keep it" appears only where it is true, rather than
    as boilerplate under a field that was never filled in."""
    before = boss.get("/admin/api/cbe/integrations").json()["sms"]
    assert before["has_auth_header"] is False

    _sms_connect(boss, send_url="https://gw.example/send", auth_header="Bearer k")
    after = boss.get("/admin/api/cbe/integrations").json()["sms"]
    assert after["has_auth_header"] is True
    assert "Bearer k" not in json.dumps(after)
