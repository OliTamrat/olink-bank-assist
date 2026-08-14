# Viber

**Status: built, and blocked on a commercial account — not on us.**
Adapter: `bankassist/viber.py`. Route: `/webhooks/viber/{slug}`. Shipped in
PR #112.

> **This page said "self-serve — connect in minutes" until 2026-08-14.** That
> was true when it was written and stopped being true on **5 February 2024**,
> when Rakuten Viber moved chatbots to an application-and-commercial-terms
> model. Nothing in the code changed and no test could have caught it: a vendor
> rewriting its onboarding is invisible from inside this repo. It surfaced when
> the founder logged in to `partners.viber.com` expecting a "Create Bot
> Account" button and found Pricing and Company details instead.
>
> The general lesson, which applies to every page in this directory: a `needs`
> list is a claim about **somebody else's product**, and it decays without
> warning. Re-check it against the vendor before quoting it to a bank.

## Connect

1. Apply for a chatbot account — to Rakuten Viber directly, or through one of
   their verified partners, which is the faster route. Creating one yourself
   is no longer possible.
2. Agree Viber's commercial terms: a monthly maintenance fee per bot plus a
   per-message charge for bot-initiated messages. Figures vary by market —
   read them off the **Pricing** page of the Viber partner account rather than
   from any number written down here, including this sentence.
3. Once the bot exists, its authentication token is on the bot's *edit info*
   screen in the Viber Admin Panel.
4. Paste it into **Channels → Viber** in the admin panel, or
   `POST /admin/api/{slug}/viber/connect` with `{"auth_token": "..."}`.

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
