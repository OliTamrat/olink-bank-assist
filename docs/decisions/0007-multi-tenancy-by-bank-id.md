# ADR-0007 — Multi-tenancy by bank_id filter, asserted in tests

**Status:** accepted · **Date:** 2026-08 (inception)

## Context

One deployment serves many banks. A cross-tenant leak in banking is a
disclosure incident, not a bug.

## Decision

Every table hangs off `bank_id`; every query filters by it; dedicated tests
assert isolation for documents, conversations, chats and admin tokens.
Off-web channels key conversations by `(bank, channel, external_user_id)` so
two customers of two banks on one platform can never share a thread.

## Consequences

- Isolation is a tested property, not a convention — the test fails before
  the leak ships.
- Cost: no cross-tenant analytics without deliberate, reviewed aggregation.

## References

tenancy tests, `models.py`.
