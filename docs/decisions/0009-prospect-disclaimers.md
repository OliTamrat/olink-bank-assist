# ADR-0009 — Prospect tenants carry mandatory disclaimers

**Status:** accepted · **Date:** 2026-08

## Context

`cbe`, `dashen`, `awash` are pitch-demo prototypes built from public
information, with no relationship with those banks. A publicly-branded bot
under a real bank's name is trademark/impersonation and financial-regulatory
risk with a real, non-consenting company.

## Decision

Every prospect tenant carries a mandatory `Bank.disclaimer` rendered in the
widget and sent as the first message of every new off-web conversation
(bots are publicly discoverable and have no banner surface). "Make X live"
means a signed deal and their real content — never flipping the switch on
the prototype.

## Consequences

- The disclaimer-first ordering is enforced in the shared channel core and
  tested per channel.
- Deliberately excluded content (e.g. CBE fraud-loss figures) stays
  excluded: a sales demo does not surface damaging news about the prospect
  it pitches.

## References

`seed_common.py: prospect_disclaimer()`, disclaimer tests per channel,
CLAUDE.md "Current state".
