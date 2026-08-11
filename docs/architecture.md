# Architecture

For module-by-module detail the README's directory map is the index; this
page explains how the pieces relate and why the seams are where they are.

## The shape

FastAPI, Python 3.12, SQLAlchemy 2.x — **sync, psycopg2** (ADR-0003).
SQLite in dev, Supabase Postgres in prod, Alembic migrations (the deploy
workflow runs `alembic upgrade head` before starting uvicorn, so a merged
migration is an applied migration). Every outbound service is called over
plain REST with httpx — **no vendor SDKs** (ADR-0004).

## How a message flows

```
channel webhook ──► _channel_reply()          (api.py — the shared four steps)
                      │ find-or-open Conversation (bank_id, channel, external_user_id)
                      │ disclaimer if the conversation is new
                      ▼
                    handle_message()          (agent.py — orchestration)
                      │ classify: language, intent      (classifier.py)
                      │ guardrails: account-specific? complaint? human request?
                      │ tier 1: curated match            (faq.py)
                      │ tier 2: BM25 retrieve            (retrieval.py, index.py)
                      │         + optional Gemini phrasing (llm.py)
                      │ tier 3: handoff + department     (departments.py)
                      ▼
                    reply ──► channel adapter's send()
```

The agent core takes text and a conversation and knows nothing about
transport (ADR-0010). A channel adapter is an inbound webhook that
authenticates + extracts `(sender, text)`, and an outbound send — Telegram's
is 41 lines. `_channel_reply()` owns the four steps every channel shares, so
the disclaimer cannot be silently dropped on the newest adapter.

## The channel surface

Seven channels; `bankassist/channels.py` is the catalogue the Settings page
serves, and `_connected_channels()` in `api.py` is the single definition of
"connected" (everything needed to **send** — an inbound-only credential is
not live to a customer waiting for a reply).

The three Meta products are one module, `meta.py` — one app, one callback,
one app secret, one envelope; `object` routes the delivery (ADR-0011). SMS,
`sms.py`, is a documented aggregator contract rather than a vendor
integration (ADR-0014).

Per-vendor failure modes that shaped the code live in `integrations/` — each
page names what that vendor gets wrong silently.

## Data model (the rows that matter)

- **Bank** — the tenant. Branding, language default, disclaimers, and every
  channel credential. Every other table hangs off `bank_id`, and every query
  filters by it; cross-tenant isolation is asserted in tests (ADR-0007).
- **Document / Chunk** — the knowledge base, per-tenant, BM25-indexed
  (`index.py`, version-stamped and LRU-bounded).
- **Faq** — curated answers, served verbatim. `source_faq_id` links a
  translation to its original.
- **Conversation / Message** — keyed by `(bank, channel, external_user_id)`
  off-web; the widget uses per-conversation ids.
- **Handoff** — every miss and every escalation, with department and
  priority. The content-gaps view is built from these.
- **User / Role / RolePermission** — people and roles are database rows;
  permissions are code constants (ADR-0002).
- **TellerSession** — the live-call lifecycle; scopes never include money.
- **AuditLog** — every admin mutation and handoff. `entity_id` is TEXT.

## Guarantees, and where they are enforced

| Guarantee | Enforced by |
|---|---|
| No transaction capability | module-level assert in `teller.py` + absence from every scope list |
| Cross-tenant isolation | `bank_id` filters + dedicated tests |
| Webhooks fail closed | per-channel signature/secret checks, `hmac.compare_digest`, empty-credential refusal |
| No invented figures | strict context-only prompt + golden-question evals in CI |
| Five-language parity | string-table parity tests; untranslated keys cannot ship |
| Docs match code | `tests/test_docs_truth.py` |
