# ADR-0004 — No vendor SDKs: every external service over plain REST

**Status:** accepted · **Date:** 2026-08 (inception; extended each integration)

## Context

Gemini, Telegram, Viber, Meta, LiveKit, and later Stripe-class services all
offer SDKs. SDKs pin transitive dependencies, hide the wire protocol, and
turn vendor deprecations into dependency upgrades entangled with everything
else.

## Decision

httpx + the documented REST API, everywhere. Auth is the primitive standard
for each service (ADC metadata for Vertex, HMAC for webhooks, hand-rolled
HS256 for LiveKit room tokens). API versions are pinned where the vendor
versions them (`meta.py: API_VERSION`).

## Consequences

- The wire truth is in our code — when Viber hides errors inside HTTP 200,
  we see it and test it, instead of trusting an SDK's exception model.
- Dependency surface stays small enough to audit (`pyproject.toml` comments
  justify each entry).
- Cost: we own retries/edge cases an SDK would own. Accepted; those are
  exactly the behaviours this product must control (webhook retry storms,
  send-failures-never-raise).

## References

`llm.py`, `telegram.py`, `viber.py`, `meta.py`, `livekit.py`.
