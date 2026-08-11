# ADR-0012 — Security controls are mutation-tested

**Status:** accepted · **Date:** 2026-08 (practice throughout; named here)

## Context

A green suite proves the tests pass, not that they test anything. For
security controls the difference is the whole game: PR #112's Viber
signature check survived a mutation (verify re-serialised JSON instead of
raw bytes) because the test helper built bodies the same way — a bug that
would have broken production with CI green.

## Decision

Every security control gets broken deliberately before its PR merges:
remove the check, invert the comparison, weaken the key — and a *named* test
must fail for each mutation. Survivors are treated as missing tests, fixed
before merge, and named in the PR body.

## Consequences

- Fail-open bugs (empty-credential HMAC, dropped signature prefixes) are
  caught at build time.
- Cost: real minutes per control. Cheaper than the alternative once.

## References

PR #110 (workbook claims), PR #112 (mutation table in the body),
`tests/test_viber_channel.py`, `tests/test_meta_channels.py`.
