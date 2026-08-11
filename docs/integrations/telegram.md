# Telegram

**Status: self-serve — a bank can connect this in minutes.**
Adapter: `bankassist/telegram.py`. Route: `/webhooks/telegram/{slug}`.

## Connect

1. Create a bot with @BotFather, copy the token.
2. `POST /admin/api/{slug}/telegram/connect` with `{"bot_token": "..."}`.
   This stores the token, mints a per-bank webhook secret, and registers
   `{APP_BASE_URL}/webhooks/telegram/{slug}` with Telegram.

## The credential model

Two credentials, unlike Viber's one: the bot token (to send) and a webhook
secret **we choose**, which Telegram echoes back in
`X-Telegram-Bot-Api-Secret-Token`. Compared constant-time, fail-closed.

## What fails silently / quirks

- A send failure is logged, never raised — a Telegram outage must not 500 the
  webhook, because Telegram retries the whole update on non-2xx.
- `/start` is Telegram's "open the bot" command, not a customer question. It
  gets the greeting, not the agent — and it may carry a deep-link payload
  (`/start ref123`), so match on the first token.
- The disclaimer is sent as the first message of a new conversation: a bot is
  publicly discoverable by username and has no pinned-banner surface, so an
  unlabelled first reply on a prospect tenant is the worst available failure
  (see ADR-0009).
