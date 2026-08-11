# ADR-0005 — Dependency-free BM25 retrieval

**Status:** accepted · **Date:** 2026-08 (inception)

## Context

Retrieval over per-tenant knowledge bases of tens-to-hundreds of documents,
in five languages, deployable in-country (Art. 22) where a vector-DB
dependency is one more thing to certify and host.

## Decision

Hand-written BM25 (`retrieval.py`) over a per-tenant inverted index
(`index.py`, version-stamped, LRU-bounded), five-language stopword lists, no
embedding service, no vector store.

## Consequences

- Zero external retrieval dependencies; runs identically in dev, CI, and an
  air-gapped in-country deployment. Fully explainable ranking (a compliance
  audience can be shown *why* a passage matched).
- Cost: no semantic matching — a paraphrase BM25 misses is a curated-FAQ or
  content-gap problem by design. **The corpus is the ceiling**; embeddings
  would not change that while corpora are this small. Revisit at real-bank
  corpus scale, as its own ADR.

## References

`retrieval.py`, `index.py`, CLAUDE.md "the corpus is the ceiling".
