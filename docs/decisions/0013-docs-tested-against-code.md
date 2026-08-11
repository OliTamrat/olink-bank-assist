# ADR-0013 — Docs are tested against code

**Status:** accepted · **Date:** 2026-08-11 (PR #111 set the pattern; this
PR generalises it)

## Context

Documentation drift is not hypothetical here: the docs named the wrong
tenant for the curated FAQs (CBE for Dashen) with runnable commands that
would silently export an empty sheet, and hard-coded test counts went stale
within days. Drift centimetres from the code, written the same day, by the
same author.

## Decision

Where prose states a checkable fact, a test checks it.
`tests/test_faq_sheet_import.py` compares the export/import usage examples
to each other; `tests/test_docs_truth.py` holds the schema-head claim, the
channel count and the integration-page coverage. Facts that cannot be
checked are not hard-coded (exact test counts are gone — the CI run is the
count). This is OKM's founding principle: knowledge you can rely on is
knowledge something checks.

## Consequences

- Changing the schema head or adding a channel fails a doc test that names
  the prose to update — drift becomes a red build instead of a wrong pitch.
- Cost: doc tests to maintain. They are the cheapest tests in the suite.

## References

PR #111, `docs/README.md`, `tests/test_docs_truth.py`.
