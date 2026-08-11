# The knowledge base — OKM Phase 1

This tree is the durable knowledge for Olink Bank Assist, structured so it
can be trusted, found, and eventually served. It is Phase 1 of **OKM (Olink
Knowledge Management)**: the same taxonomy will be stamped across every Olink
product repo, a portal will aggregate the trees into one searchable site
(Phase 2), and an internal Bank Assist tenant will answer questions over it
(Phase 3) — the product dogfooding itself.

## Why this is not a wiki

Documentation dies of distrust, not of missing features, and drift is what
kills the trust. This repo has already paid for that lesson twice: the docs
named the wrong tenant for the curated FAQs (caught by a person, fixed in
PR #111, now held by a test), and hard-coded test counts went stale within
days. The design principle that follows:

**Knowledge you can rely on is knowledge something checks.**

Three rules keep this tree true:

1. **One source per fact.** A page never repeats a price, a slug, a limit or
   a command that lives in code — it links to the file that owns it. Where a
   page must state a checkable fact (the schema head, the channel count),
   `tests/test_docs_truth.py` asserts the prose against the code in CI.
2. **Decisions are append-only.** `decisions/` holds ADRs — dated, numbered,
   never edited after the fact. A reversed decision gets a new ADR that
   supersedes the old one, so the record shows *what we believed and when*,
   which is the part a wiki loses.
3. **The agent briefing points here.** `CLAUDE.md` remains the operational
   briefing agents load automatically — current phase, gotchas, doctrine.
   Anything durable graduates into this tree; CLAUDE.md links rather than
   duplicates.

## Map

| Where | What |
|---|---|
| `overview.md` | What the product is, who it serves, the three-tier answer model |
| `architecture.md` | Stack, modules, data model, how a message flows |
| `runbooks/` | How to do operational things: deploy, connect channels, run the translation loops |
| `integrations/` | One page per external service: what it needs, what it signs, what fails silently |
| `decisions/` | ADRs — the *why* behind every load-bearing choice, with PR references |
| `video-teller.md`, `per-person-logins.md` | Pre-OKM deep dives, kept in place |

## Writing rules

- Name the failure mode, not just the rule. "Compare constant-time" is a
  rule; "Viber reports errors inside HTTP 200, so `raise_for_status()` reads
  a rejected token as a delivered message" is knowledge.
- Date what will age. Anything phrased as "currently" gets a date so a reader
  can judge staleness instead of guessing.
- Prefer linking to a test over restating a guarantee. The test is the
  guarantee; prose is its table of contents.
