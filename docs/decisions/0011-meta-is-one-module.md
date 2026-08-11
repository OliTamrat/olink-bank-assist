# ADR-0011 — The Meta products are one module

**Status:** accepted · **Date:** 2026-08-11 (PR #112)

## Context

WhatsApp, Messenger and Instagram Direct are three products of one Meta app:
one callback URL, one app secret, one `X-Hub-Signature-256` scheme, one
webhook envelope. Only the innermost payload and the send call differ.

## Decision

One module (`meta.py`), one route pair, shared `meta_app_secret` +
`meta_verify_token` columns; only send-side credentials are per-product. The
envelope's `object` field routes each delivery.

## Consequences

- One place to fix when Meta bumps versions (pinned `API_VERSION`) — three
  copies would mean two forgotten.
- An app-secret-per-product schema would hold three identical values and
  break mysteriously when only one was set.
- A product with no send credential does not run the agent: a reply that
  cannot be delivered must not be generated.

## References

`meta.py`, migration 0025, `integrations/meta.md`.
