# ADR-0003 — Sync SQLAlchemy with psycopg2, not asyncpg

**Status:** accepted · **Date:** 2026-08 (inception)

## Context

The sibling product (olink-dispatch) runs asyncpg and paid for it repeatedly:
pgBouncer statement-cache workarounds, UUID-vs-TEXT type-inference DataErrors,
SAVEPOINT unreliability in transaction mode — all documented in its gotchas.

## Decision

Synchronous SQLAlchemy 2.x on psycopg2. FastAPI runs sync endpoints in its
threadpool; this workload is short queries, not long-held connections.

## Consequences

- The entire class of async-driver/pooler interaction bugs is absent, and
  the test suite runs against SQLite without an event-loop bridge.
- Cost: no async DB concurrency. At current scale (chat turnaround dominated
  by model latency, not DB), irrelevant; revisit only with measured evidence.

## References

olink-dispatch CLAUDE.md gotchas (the paid-for lessons), `db.py`.
