# ADR-0001 — The assistant never moves money and never sees an account

**Status:** accepted · **Date:** 2026-08 (founder decision, stated at product
inception)

## Context

An AI in front of banking customers can fail by hallucination, injection, or
plain bug. Every failure mode is survivable except one: an unauthorized
transaction. Founder constraint, verbatim intent: *"we do not allow users to
deposit or withdraw/transfer for a security reason"* — core banking access
belongs to the teller, who has their own pre-approved access on their own
screen.

## Decision

No code path moves money or reads an account. `MONEY` is absent from every
scope grant list in `teller.py` rather than gated behind a flag, and a
module-level `assert` refuses to import if it ever appears. Escalation
connects the customer to a human teller (with chat history); the teller's
core-banking access is never proxied through this product.

## Consequences

- The product is a banking *channel*, not a banking *agent* — Phase 3
  (authenticated read-only servicing) will need its own ADR and INSA-grade
  review before relaxing anything.
- Compliance conversations start from "it cannot", not "it is prompted not
  to" — the strongest sales position available.
- Cost: some customer requests that a competitor's bot "handles" get a human
  here. That cost is the product.

## References

`teller.py` (the assert), README "Safety doctrine", teller PRs #70–#98.
