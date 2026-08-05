"""Tenancy isolation, admin auth, document lifecycle, Telegram webhook."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["llm"] == "extractive-fallback"


def test_admin_requires_valid_token(client: TestClient, demo_bank: Any) -> None:
    assert client.get("/admin/api/demo/documents").status_code == 401
    assert (
        client.get("/admin/api/demo/documents", headers={"X-Admin-Token": "wrong"}).status_code
        == 401
    )
    ok = client.get(
        "/admin/api/demo/documents", headers={"X-Admin-Token": demo_bank.admin_token}
    )
    assert ok.status_code == 200
    assert len(ok.json()) >= 10


def test_tenant_cannot_use_other_tenants_token(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    resp = client.get(
        "/admin/api/demo/documents", headers={"X-Admin-Token": second_bank.admin_token}
    )
    assert resp.status_code == 401


def test_chat_never_leaks_other_tenants_knowledge(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    resp = client.post(
        "/chat/demo", json={"message": "Tell me about the Secret Gold Account concierge"}
    )
    data = resp.json()
    assert "golden concierge" not in data["reply"].lower()
    assert "1,000,000" not in data["reply"]

    resp2 = client.post(
        "/chat/other", json={"message": "Tell me about the Secret Gold Account concierge"}
    )
    assert "concierge" in resp2.json()["reply"].lower()


def test_conversation_ids_are_tenant_scoped(
    client: TestClient, demo_bank: Any, second_bank: Any
) -> None:
    convo = client.post("/chat/demo", json={"message": "hello"}).json()["conversation_id"]
    resp = client.post("/chat/other", json={"message": "hello", "conversation_id": convo})
    assert resp.status_code == 404


def test_document_create_update_delete_reindexes(client: TestClient, demo_bank: Any) -> None:
    headers = {"X-Admin-Token": demo_bank.admin_token}
    created = client.post(
        "/admin/api/demo/documents",
        headers=headers,
        json={
            "title": "Zeta Premium Account",
            "content": "The Zeta Premium Account has a 42 birr fee.",
        },
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    answer = client.post("/chat/demo", json={"message": "What is the Zeta Premium fee?"}).json()
    assert "42 birr" in answer["reply"]

    updated = client.put(
        f"/admin/api/demo/documents/{doc_id}",
        headers=headers,
        json={
            "title": "Zeta Premium Account",
            "content": "The Zeta Premium Account now has a 99 birr fee.",
        },
    )
    assert updated.status_code == 200
    answer = client.post("/chat/demo", json={"message": "What is the Zeta Premium fee?"}).json()
    assert "99 birr" in answer["reply"]

    assert client.delete(f"/admin/api/demo/documents/{doc_id}", headers=headers).status_code == 204
    answer = client.post("/chat/demo", json={"message": "What is the Zeta Premium fee?"}).json()
    assert "99 birr" not in answer["reply"]


def test_bulk_document_import_creates_and_reindexes_all(
    client: TestClient, demo_bank: Any
) -> None:
    headers = {"X-Admin-Token": demo_bank.admin_token}
    resp = client.post(
        "/admin/api/demo/documents/bulk",
        headers=headers,
        json={
            "documents": [
                {
                    "title": "Kappa Business Loan",
                    "content": "The Kappa Business Loan carries a 7 birr processing fee.",
                    "category": "products",
                },
                {
                    "title": "Omega Diaspora Account",
                    "content": "The Omega Diaspora Account requires a passport copy.",
                    "language": "am",
                },
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["created"] == 2
    assert len(data["ids"]) == 2

    answer = client.post("/chat/demo", json={"message": "What is the Kappa loan fee?"}).json()
    assert "7 birr" in answer["reply"]


def test_bulk_document_import_rejects_whole_batch_on_bad_language(
    client: TestClient, demo_bank: Any
) -> None:
    headers = {"X-Admin-Token": demo_bank.admin_token}
    before = client.get("/admin/api/demo/documents", headers=headers).json()

    resp = client.post(
        "/admin/api/demo/documents/bulk",
        headers=headers,
        json={
            "documents": [
                {"title": "Valid Doc", "content": "Fine content."},
                {"title": "Bad Doc", "content": "Bad content.", "language": "fr"},
            ]
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["invalid_documents"][0]["title"] == "Bad Doc"

    after = client.get("/admin/api/demo/documents", headers=headers).json()
    assert len(after) == len(before)  # nothing partially imported


def test_bulk_document_import_requires_admin_token(client: TestClient, demo_bank: Any) -> None:
    resp = client.post(
        "/admin/api/demo/documents/bulk",
        json={"documents": [{"title": "X", "content": "Y"}]},
    )
    assert resp.status_code == 401


def test_telegram_webhook_rejects_bad_secret(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    from bankassist.models import Bank

    bank = db_session.get(Bank, demo_bank.id)
    bank.telegram_webhook_secret = "s3cret"
    db_session.commit()

    update = {"message": {"text": "hi", "chat": {"id": 42}}}
    assert client.post("/webhooks/telegram/demo", json=update).status_code == 403
    assert (
        client.post(
            "/webhooks/telegram/demo",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
        ).status_code
        == 403
    )


def test_telegram_webhook_replies_via_bot(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bankassist import api as api_module
    from bankassist.models import Bank

    bank = db_session.get(Bank, demo_bank.id)
    bank.telegram_webhook_secret = "s3cret"
    bank.telegram_bot_token = "123:abc"
    db_session.commit()

    sent: list[tuple[str, int | str, str]] = []
    monkeypatch.setattr(
        api_module.telegram,
        "send_message",
        lambda token, chat_id, text: sent.append((token, chat_id, text)) or True,
    )

    resp = client.post(
        "/webhooks/telegram/demo",
        json={"message": {"text": "What are the fixed deposit rates?", "chat": {"id": 42}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert resp.status_code == 200
    assert len(sent) == 1
    assert sent[0][1] == 42
    assert "10,000 birr" in sent[0][2]

    # Non-text updates (stickers, joins) are acknowledged and ignored.
    resp = client.post(
        "/webhooks/telegram/demo",
        json={"message": {"chat": {"id": 42}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert resp.status_code == 200
    assert len(sent) == 1


def test_seed_is_idempotent(client: TestClient, demo_bank: Any) -> None:
    from bankassist.seed import seed

    bank, created = seed()
    assert created is False
    assert bank.id == demo_bank.id
