# ADR-0006 — Three-tier answering, in cost order

**Status:** accepted · **Date:** 2026-08

## Context

Three ways to answer (curated verbatim / retrieved+phrased / human), three
cost profiles (zero / one model call / a human minute), and a safety rule
that some questions must never be answered by a machine.

## Decision

Resolve every message through the tiers in order: curated match first,
retrieval second, handoff third — with guardrails able to force tier 3
regardless (account-specific, complaints, human requests). The order is the
product.

## Consequences

- The Gemini bill does not scale with traffic on the questions everybody
  asks — promoting a hot question to curated is a cost *and* quality lever.
- Curated answers are bank-approved copy served verbatim: the one path with
  no model and no gate, which is why the FAQ translation loop writes drafts
  only (importer cannot publish).
- Every miss files a Handoff row → Content Gaps: unanswered questions become
  visible content work instead of silence.

## References

`agent.py`, `faq.py`, README "The three tiers of an answer".
