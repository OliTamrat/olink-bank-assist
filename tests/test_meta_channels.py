"""WhatsApp, Messenger and Instagram — one app, one callback, three products.

Two things here are worth more than the rest of the file.

The first is the **echo loop**. Messenger and Instagram deliver a copy of every
message the Page sends, including the replies this service just sent, flagged
`is_echo`. Treat one as inbound and the assistant answers its own answer,
forever, at the price of a model call each time round. It is the only bug in
this codebase that costs money while it runs.

The second is that `object` routes the delivery. One callback serves three
products, so a mistake there does not fail — it answers the right customer on
the wrong channel, or drives a delivery into a product the bank never
connected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bankassist import meta

SECRET = "meta-app-secret-xyz"


def _signed(body: dict[str, Any], secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        "X-Hub-Signature-256": f"sha256={digest}",
        "Content-Type": "application/json",
    }


@pytest.fixture()
def wired(
    client: TestClient, cbe_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[tuple[str, str]]]:
    """A CBE tenant with all three Meta products connected, sends captured."""
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.meta_app_secret = SECRET
    bank.meta_verify_token = "verify-me"
    bank.whatsapp_access_token = "wa-token"
    bank.whatsapp_phone_number_id = "1234567890"
    bank.messenger_page_token = "page-token"
    bank.instagram_access_token = "ig-token"
    db_session.commit()

    sent: dict[str, list[tuple[str, str]]] = {"whatsapp": [], "messaging": []}
    monkeypatch.setattr(
        api_module.meta, "send_whatsapp",
        lambda token, number, to, text: sent["whatsapp"].append((to, text)) or True,
    )
    monkeypatch.setattr(
        api_module.meta, "send_messaging",
        lambda token, to, text, *, channel: sent["messaging"].append((to, text)) or True,
    )
    return sent


def _post(client: TestClient, body: dict[str, Any]) -> Any:
    raw, headers = _signed(body)
    return client.post("/webhooks/meta/cbe", content=raw, headers=headers)


def _whatsapp(text: str, sender: str = "251911000000") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [
            {"from": sender, "type": "text", "text": {"body": text}}
        ]}}]}],
    }


def _messenger(text: str, sender: str = "psid-1", obj: str = "page") -> dict[str, Any]:
    return {
        "object": obj,
        "entry": [{"messaging": [
            {"sender": {"id": sender}, "message": {"text": text}}
        ]}],
    }


# ------------------------------------------------------------- the echo loop


def test_the_pages_own_message_is_not_answered(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """The expensive one. Meta echoes every message the Page sends — including
    the reply this service just sent. Answering it means answering ourselves,
    round and round, one model call per lap."""
    resp = _post(client, {
        "object": "page",
        "entry": [{"messaging": [
            {"sender": {"id": "page-1"},
             "message": {"text": "Our savings rate is 7%.", "is_echo": True}}
        ]}],
    })
    assert resp.status_code == 200
    assert wired["messaging"] == []


def test_our_own_reply_does_not_come_back_as_a_question(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """The loop as it would actually happen: a customer asks, we answer, and
    Meta hands our answer straight back."""
    _post(client, _messenger("What are your savings rates?"))
    answered = len(wired["messaging"])
    assert answered, "the customer got no reply at all"

    our_reply = wired["messaging"][-1][1]
    _post(client, {
        "object": "page",
        "entry": [{"messaging": [
            {"sender": {"id": "page-1"},
             "message": {"text": our_reply, "is_echo": True}}
        ]}],
    })
    assert len(wired["messaging"]) == answered, "the assistant replied to itself"


# --------------------------------------------------------------- signature


def test_an_unsigned_delivery_is_refused(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    resp = client.post(
        "/webhooks/meta/cbe",
        content=json.dumps(_whatsapp("hello")).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 403
    assert wired["whatsapp"] == []


def test_a_signature_from_the_wrong_secret_is_refused(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    raw, headers = _signed(_whatsapp("hello"), secret="not-the-app-secret")
    resp = client.post("/webhooks/meta/cbe", content=raw, headers=headers)
    assert resp.status_code == 403


def test_the_sha256_prefix_is_part_of_the_comparison(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """Meta sends `sha256=<hex>`. A bare digest must not authenticate — that
    is the shape of a hand-rolled client, or of someone probing."""
    raw = json.dumps(_whatsapp("hello")).encode()
    bare = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhooks/meta/cbe",
        content=raw,
        headers={"X-Hub-Signature-256": bare, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_a_bank_with_no_app_secret_accepts_nothing(
    client: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """Fails closed. HMAC with an empty key is still valid, so without the
    explicit check an unconfigured tenant would accept anything signed with
    the empty string."""
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.meta_app_secret = None
    db_session.commit()

    raw, headers = _signed(_whatsapp("hello"), secret="")
    resp = client.post("/webhooks/meta/cbe", content=raw, headers=headers)
    assert resp.status_code == 403


def test_a_body_signed_as_sent_verifies_even_when_it_is_not_canonical_json(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """Verify the bytes Meta sent, not a re-serialisation of them. The same
    mutation that survived on the Viber route would survive here."""
    body = (
        b'{ "object" : "page" ,\n "entry" : [ {"messaging": ['
        b'{"sender": {"id": "psid-9"}, "message": {"text": "hello"}}]} ] }'
    )
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhooks/meta/cbe",
        content=body,
        headers={"X-Hub-Signature-256": f"sha256={digest}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert wired["messaging"], "a validly signed non-canonical body was ignored"


# --------------------------------------------------------------- handshake


def test_the_verification_handshake_echoes_the_challenge_as_bare_text(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """Meta compares the body byte-for-byte, so a JSON-quoted challenge fails
    and the callback can never be registered."""
    resp = client.get(
        "/webhooks/meta/cbe",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                "hub.challenge": "1158201444"},
    )
    assert resp.status_code == 200
    assert resp.text == "1158201444"


def test_the_handshake_refuses_a_wrong_token(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    resp = client.get(
        "/webhooks/meta/cbe",
        params={"hub.mode": "subscribe", "hub.verify_token": "guessed",
                "hub.challenge": "123"},
    )
    assert resp.status_code == 403


def test_the_handshake_fails_closed_when_unconfigured(
    client: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """An unconfigured tenant's callback must not be claimable by whoever
    guesses the slug and sends an empty token."""
    from bankassist.models import Bank

    bank = db_session.get(Bank, cbe_bank.id)
    bank.meta_verify_token = None
    db_session.commit()
    resp = client.get(
        "/webhooks/meta/cbe",
        params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"},
    )
    assert resp.status_code == 403


# ------------------------------------------------------------------ routing


def test_whatsapp_and_messenger_reach_different_senders(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """`object` is what says which product a delivery belongs to."""
    _post(client, _whatsapp("Hello", sender="251911000000"))
    _post(client, _messenger("Hello", sender="psid-1"))
    assert wired["whatsapp"] and wired["messaging"]
    assert wired["whatsapp"][0][0] == "251911000000"
    assert wired["messaging"][0][0] == "psid-1"


def test_instagram_is_its_own_channel_not_messenger(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]], db_session: Any
) -> None:
    """Instagram shares Messenger's payload shape and send endpoint, which is
    exactly why the channel could silently be recorded as the wrong one."""
    from sqlalchemy import select

    from bankassist.models import Conversation

    _post(client, _messenger("Hello", sender="ig-9", obj="instagram"))
    row = db_session.execute(
        select(Conversation).where(Conversation.external_user_id == "ig-9")
    ).scalar_one()
    assert row.channel == "instagram"


def test_an_object_we_do_not_serve_is_ignored(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """An app subscribed to extra products must not drive traffic into a
    channel by accident."""
    resp = _post(client, {"object": "permissions", "entry": [{"changes": []}]})
    assert resp.status_code == 200
    assert wired["whatsapp"] == [] and wired["messaging"] == []


def test_a_batch_answers_each_person_separately(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """Meta batches several messages into one delivery. A closure over the
    loop variable sends everyone's answer to whoever came last."""
    _post(client, {
        "object": "page",
        "entry": [{"messaging": [
            {"sender": {"id": "alice"}, "message": {"text": "Hello"}},
            {"sender": {"id": "bob"}, "message": {"text": "Hello"}},
        ]}],
    })
    recipients = {to for to, _ in wired["messaging"]}
    assert recipients == {"alice", "bob"}


def test_a_delivery_status_is_not_a_message(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """WhatsApp sends sent/delivered/read in the same envelope, under
    `statuses` rather than `messages`."""
    resp = _post(client, {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.x", "status": "delivered"}
        ]}}]}],
    })
    assert resp.status_code == 200
    assert wired["whatsapp"] == []


def test_a_photo_with_no_caption_gets_no_reply(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    resp = _post(client, {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"messages": [
            {"from": "251911000000", "type": "image", "image": {"id": "abc"}}
        ]}}]}],
    })
    assert resp.status_code == 200
    assert wired["whatsapp"] == []


def test_a_connected_app_with_no_send_credential_does_not_run_the_agent(
    client: TestClient, cbe_bank: Any, db_session: Any, wired: dict[str, list[Any]]
) -> None:
    """Signature valid, product subscribed, no way to reply. Answering would
    burn a model call and drop the reply on the floor — the customer waits and
    nothing anywhere says why."""
    from sqlalchemy import select

    from bankassist.models import Bank, Conversation

    bank = db_session.get(Bank, cbe_bank.id)
    bank.whatsapp_access_token = None
    db_session.commit()

    resp = _post(client, _whatsapp("Hello", sender="251911999999"))
    assert resp.status_code == 200
    assert wired["whatsapp"] == []
    assert db_session.execute(
        select(Conversation).where(Conversation.external_user_id == "251911999999")
    ).scalar_one_or_none() is None


# ---------------------------------------------------------------- disclaimer


def test_the_disclaimer_leads_on_a_meta_channel_too(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    """Same rule as every other channel, retested per channel because a shared
    helper is exactly where a convention stops being followed silently."""
    _post(client, _whatsapp("What are your savings rates?"))
    assert wired["whatsapp"][0][1] == cbe_bank.disclaimer


def test_the_disclaimer_is_not_repeated(
    client: TestClient, cbe_bank: Any, wired: dict[str, list[Any]]
) -> None:
    _post(client, _whatsapp("What are your savings rates?"))
    _post(client, _whatsapp("And current accounts?"))
    assert [t for _, t in wired["whatsapp"]].count(cbe_bank.disclaimer) == 1


# ------------------------------------------------------------------ adapter


def test_a_long_whatsapp_reply_is_truncated_to_the_documented_limit() -> None:
    """Over 4,096 characters WhatsApp rejects the send outright."""
    import httpx

    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "post", fake_post)
        assert meta.send_whatsapp("t", "123", "251911000000", "x" * 9000) is True
    assert len(captured["text"]["body"]) == meta.MAX_TEXT[meta.WHATSAPP]


def test_replies_are_declared_as_responses_not_unsolicited_sends() -> None:
    """`messaging_type: RESPONSE` is what keeps a reply inside the standard
    window without a paid template. This product only ever replies."""
    import httpx

    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(kwargs["json"])
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "post", fake_post)
        meta.send_messaging("t", "psid-1", "hello", channel=meta.MESSENGER)
    assert captured["messaging_type"] == "RESPONSE"


# ---------------------------------------------------- connecting the products
#
# One Meta app serves three products, and a bank connects them as its review
# clears them — WhatsApp in March, Messenger in June. That makes the *second*
# connect the interesting one: it is a partial update to credentials that are
# already working, submitted from a form that cannot read any of them back.


_PW = "pytest-fixture-value-9"


@pytest.fixture()
def boss(client: TestClient, cbe_bank: Any) -> TestClient:
    """A signed-in administrator on the CBE tenant.

    Not the break-glass token: it stops authenticating the moment a tenant has
    a user, and connecting a channel is exactly the kind of thing it must no
    longer be able to do (ADR-0031).
    """
    from conftest import create_user

    create_user(client, cbe_bank, "boss@cbe.test", password=_PW, role="admin",
                slug=cbe_bank.slug)
    signed_in = client.post(f"/admin/api/{cbe_bank.slug}/login",
                            json={"email": "boss@cbe.test", "password": _PW})
    assert signed_in.status_code == 200, signed_in.text
    return client


def _reload(db: Any, bank_id: str) -> Any:
    """The connect route commits on its own connection, so the fixture object
    this test holds is stale by the time it is asserted against."""
    from bankassist.models import Bank

    db.expire_all()
    return db.get(Bank, bank_id)


def _connect(client: TestClient, slug: str, **body: Any) -> Any:
    return client.post(f"/admin/api/{slug}/meta/connect", json=body)


def test_the_first_connect_requires_an_app_secret(
    boss: TestClient, cbe_bank: Any
) -> None:
    """Without it every inbound delivery fails signature verification, so a
    channel connected this way would read as live and answer nobody."""
    assert _connect(boss, cbe_bank.slug, messenger_page_token="page-tok").status_code == 422


def test_adding_a_second_product_does_not_re_ask_for_the_app_secret(
    boss: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """The secret is not readable from the screen, so requiring it again would
    mean fetching it out of Meta's dashboard to retype a value we already
    hold — or giving up and pasting something wrong over a working channel."""

    first = _connect(boss, cbe_bank.slug, app_secret=SECRET,
                     whatsapp_phone_number_id="123", whatsapp_access_token="wa-tok")
    assert first.status_code == 200

    second = _connect(boss, cbe_bank.slug, messenger_page_token="page-tok")
    assert second.status_code == 200

    bank = _reload(db_session, cbe_bank.id)
    assert bank.meta_app_secret == SECRET
    assert bank.messenger_page_token == "page-tok"
    # And the March credential is still there in June.
    assert bank.whatsapp_access_token == "wa-tok"
    assert bank.whatsapp_phone_number_id == "123"


def test_the_verify_token_survives_a_second_connect(
    boss: TestClient, cbe_bank: Any, db_session: Any
) -> None:
    """It is pasted into Meta's dashboard by hand. Minting a new one on every
    save would break the callback of every product already connected, silently,
    at the moment somebody added another."""

    first = _connect(boss, cbe_bank.slug, app_secret=SECRET).json()
    second = _connect(boss, cbe_bank.slug, instagram_access_token="ig-tok").json()
    assert first["verify_token"] == second["verify_token"]


def test_the_panel_is_told_which_tokens_exist_but_never_what_they_are(
    boss: TestClient, cbe_bank: Any
) -> None:
    """The form says "leave blank to keep it" only where that is true, and a
    value the API will re-display is a value that ends up in a screenshot."""
    _connect(boss, cbe_bank.slug, app_secret=SECRET,
             whatsapp_phone_number_id="123", whatsapp_access_token="wa-tok")

    meta_cfg = boss.get(f"/admin/api/{cbe_bank.slug}/integrations").json()["meta"]
    assert meta_cfg["has_whatsapp_token"] is True
    assert meta_cfg["has_messenger_token"] is False
    # The phone number id is an identifier Meta prints on its own dashboard.
    assert meta_cfg["whatsapp_phone_number_id"] == "123"
    assert SECRET not in json.dumps(meta_cfg)
    assert "wa-tok" not in json.dumps(meta_cfg)
