# ADR-0002 — Permissions in code, roles in the database

**Status:** accepted · **Date:** 2026-08 (PR #76 era, per-person logins)

## Context

Banks need their own role shapes (a compliance officer who reads audit logs
and nothing else; a teller who is not an operator). But letting tenants
define *capabilities* means a misconfigured row can grant something the code
never intended to be grantable.

## Decision

Capabilities are code constants (`permissions.py`) — routes name a
capability, never a role. Roles and their permission grants are per-bank
database rows (`roles.py`). Banks compose; only code creates capability.

## Consequences

- A new capability is a PR with review and tests; a new role shape is data a
  bank admin can build safely.
- `teller.serve` deliberately outside the operator bundle; `audit.read`
  outside read-everything — separations that survive because they are code.
- Cost: adding a capability is slower than adding a row. Intended.

## References

`permissions.py`, `roles.py`, `docs/per-person-logins.md`.
