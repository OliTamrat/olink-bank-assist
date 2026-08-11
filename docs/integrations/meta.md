# Meta — WhatsApp, Facebook Messenger, Instagram Direct

**Status: built and tested; gated on the bank's Meta business account.**
Adapter: `bankassist/meta.py` — one module for all three, because they are
three products of **one Meta app**: one callback URL, one app secret, one
signature scheme, one envelope (ADR-0011). Routes: `GET|POST
/webhooks/meta/{slug}`. Shipped in PR #112.

## What the bank must obtain (none of it is code)

- A Meta Business account, verified against the bank's registration.
- **WhatsApp:** a WhatsApp Business Account and a dedicated number not
  already registered on WhatsApp; Meta's review of the use case; approved
  templates for any message sent first rather than in reply (this product
  only ever replies, so `messaging_type: RESPONSE` keeps sends in the
  standard window).
- **Messenger:** a Facebook Page and a Meta app with Page messaging
  permissions.
- **Instagram:** a professional account linked to that Page.

## Connect

`POST /admin/api/{slug}/meta/connect` with the app secret and whichever
send-side credentials the review cleared. It returns the **callback URL and a
generated verify token** — pasted into Meta's dashboard, because Meta
registers its own callback (the opposite of Telegram/Viber). The verify token
is minted, never typed, so it cannot be guessable.

## The credential model

`meta_app_secret` + `meta_verify_token` are per-tenant and shared across the
three products; only send-side credentials differ per product
(`whatsapp_access_token` + `whatsapp_phone_number_id`, `messenger_page_token`,
`instagram_access_token`). A product with no send credential does not run the
agent at all — answering would burn a model call and drop the reply.

## What fails silently

- **The echo loop — the only bug here that bills money while it runs.**
  Messenger/Instagram deliver a copy of every message the Page sends,
  including our own replies, flagged `is_echo`. Treat one as inbound and the
  assistant answers itself indefinitely, one model call per lap. Guarded and
  mutation-tested.
- The signature key is the **app secret**, not the access token — both are
  long opaque strings adjacent in the dashboard. Header is
  `X-Hub-Signature-256: sha256=<hex>` over the raw body; the prefix is part
  of the comparison.
- The GET handshake must echo `hub.challenge` as **bare text** — a
  JSON-quoted challenge fails byte comparison and the callback can never be
  registered.
- WhatsApp statuses (sent/delivered/read) arrive in the same envelope under
  `statuses`; media messages carry no text. Neither is a question.
- One delivery can batch several messages and may repeat them on retry; each
  is answered in its own conversation lookup, recipient bound per message
  (`_bind()` — a closure over the loop variable would send every reply to
  whoever came last).
- Graph API version is **pinned** (`API_VERSION` in `meta.py`) — an unpinned
  "latest" turns Meta's deprecation calendar into our outage.
