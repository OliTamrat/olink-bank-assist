# Viber

**Status: self-serve — a bank can connect this in minutes.**
Adapter: `bankassist/viber.py`. Route: `/webhooks/viber/{slug}`. Shipped in
PR #112.

## Connect

1. Create a bot account at `partners.viber.com` — it issues the auth token
   immediately, no review.
2. `POST /admin/api/{slug}/viber/connect` with `{"auth_token": "..."}`.

## The credential model

**One credential, deliberately.** Viber signs the raw request body with the
auth token itself (HMAC-SHA256, `X-Viber-Content-Signature`) — there is no
separate webhook secret, and a `viber_webhook_secret` column would be a
permanently-null field inviting someone to "fix" it (migration 0024).

## The connect ordering is load-bearing

The token is **committed before** `set_webhook` is called. Viber validates a
registration by immediately POSTing a `webhook` event to the URL — a separate
HTTP request on its own DB connection, to which an uncommitted flush is
invisible. Reverse the order and Viber's own validation ping fails the
signature check and registration can never succeed. On failure the previous
token is restored.

## What fails silently

- **Errors arrive as HTTP 200.** Success lives in the JSON `status` field
  (0 = OK). `raise_for_status()` alone reports a rejected token as a
  delivered message. `_ok()` checks the body.
- Signature verification must use the **raw bytes**, not re-serialised JSON —
  Viber does not send canonical JSON, so `json.dumps(json.loads(raw))` breaks
  the honest path while every naive test stays green. A mutation test
  survived exactly this; `tests/test_viber_channel.py` now signs a
  deliberately non-canonical body.
- Text over 7,000 chars is rejected (as a 200). Replies are truncated —
  visibly clipped beats silently vanished.
- `conversation_started` fires only on a *fresh* chat; returning customers
  skip it. The disclaimer is therefore tied to the conversation row being
  new, not to the event.
