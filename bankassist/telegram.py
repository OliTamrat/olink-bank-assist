"""Telegram Bot API integration (plain REST via httpx)."""

from __future__ import annotations

import logging

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org"


def send_message(bot_token: str, chat_id: int | str, text: str) -> bool:
    """Send a reply. Failures are logged, never raised — a Telegram outage
    must not 500 the webhook (Telegram would retry the whole update)."""
    try:
        resp = httpx.post(
            f"{_API}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=get_settings().request_timeout,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram sendMessage failed: %s", exc)
        return False


def set_webhook(bot_token: str, url: str, secret: str) -> dict[str, object]:
    """Register this service as the bot's webhook (used by the admin API)."""
    resp = httpx.post(
        f"{_API}/bot{bot_token}/setWebhook",
        json={"url": url, "secret_token": secret, "allowed_updates": ["message"]},
        timeout=get_settings().request_timeout,
    )
    resp.raise_for_status()
    data: dict[str, object] = resp.json()
    return data
