# ADR-0015 — "Ask OKM" pulls the portal's content; it is never pushed to

**Status:** accepted · **Date:** 2026-08-11

## Context

OKM Phase 3 ("Ask OKM") is an internal tenant (`okm`, `bankassist/seed_okm.py`)
whose knowledge base is the `olink-knowledge` portal's aggregated product
docs — 236 pages across all seven repos as of this ADR. Every other seed
script in this repo (`seed.py`, `seed_cbe.py`, `seed_dashen.py`,
`seed_awash.py`) runs on **every deploy** (`deploy.yml`), because each seeds
fixed, hand-authored content that changes only when a commit to this repo
changes it — deploying the new commit is the only trigger content needs.

`okm`'s content is different in kind: it lives in a different repo, changes
on that repo's own schedule (daily, via `olink-knowledge`'s `build.yml`), and
reaching it means cloning up to eight repositories, not reading files already
checked out. Wiring that into `deploy.yml` would mean every future
`bankassist` deploy depends on `olink-knowledge` and, transitively, on all
seven product repos being reachable and clean — a live, revenue-facing
production deploy would now be able to fail because of an unrelated repo's
broken build. That coupling is backwards: `okm` should depend on the fleet
existing, not the other way around.

## Decision

**`seed_okm.py` is a pull, run by hand or by a manual `workflow_dispatch`
job — never part of the automatic deploy.** The loop:

1. In a checkout of `olink-knowledge`: `python scripts/sync_docs.py` (see
   that repo's README) — materialises `content/`.
2. Here: `python -m bankassist.seed_okm --source <path-to-that-content>`
   against `BANKASSIST_DATABASE_URL`.

This is the same shape already established for `scripts/faq_export.py` and
`scripts/prune_merged_branches.py`: a tool that needs access an automated
deploy doesn't have runs wherever that access exists, documented as a
runbook rather than folded into CI. `docs/runbooks/ask-okm-refresh.md` has
the exact commands, including the manual GitHub Actions job.

**Why not add the manual job in this session:** it needs a new fine-grained
PAT (something like `olink-knowledge`'s own `OKM_SYNC_TOKEN`, scoped to read
all seven product repos plus `olink-knowledge` itself) stored as a
`bankassist` repo secret. That is a credential only a human can mint in the
GitHub UI — the same boundary this repo's `CLAUDE.md` already documents for
every other production secret. The runbook has the exact workflow YAML,
ready to add the moment that PAT exists.

## Consequences

- `okm` staying stale between manual refreshes is an accepted tradeoff, not
  an oversight — it is an internal staff tool, not a customer-facing surface
  with an uptime expectation. `source_url` on each `Document` records which
  file it came from, so "is this current" is one glance at the row, not a
  mystery.
- `seed_okm.py` re-running always **replaces** an existing document's content
  by title (`ingest_commit`'s own update rule in `api.py`) rather than the
  create-only behavior of `seed_common.seed_prospect_bank` — the prospect
  demo tenants are hand-curated once and meant to stay exactly as written;
  `okm` exists specifically to keep tracking a moving target.
- The `okm` tenant's knowledge base is entirely in English, matching its
  source (every product repo's `docs/` tree is English-only engineering
  documentation). The "whatever ships in English ships in all five
  languages" rule in `CLAUDE.md` governs UI chrome and customer-facing
  content **this repo authors** — the existing widget and admin panel `okm`
  reuses are already fully translated; the ingested *content* of an internal
  staff tool reading another repo's engineering docs is out of that rule's
  scope, the same way the Dashen curated answers' English-only gap is
  tracked as a content decision rather than a plumbing one.
- `allow_general_knowledge=False` on the `okm` tenant: the general-knowledge
  fallback in `llm.answer_from_general_knowledge()` is scoped to universal
  banking mechanics (what a PIN is, how an ATM works) and would simply never
  fire for engineering questions — off is the conservative, correct default
  regardless.
