# ADR-0017 — Global search reuses existing list views; no new detail screen

**Status:** accepted · **Date:** 2026-08-12

## Context

The admin panel had four separate places to look for something — Conversations,
Escalations, Knowledge Base, Curated Answers — each with its own client-side
text filter over an already-loaded, capped list (`h-q`, `c-q`). None of them
search each other, and none of them can find a record outside its own load
(Conversations loads the most recent 100, Escalations the most urgent-then-
oldest 200). "Did anyone ever ask about X" had no single answer.

Two designs were open: build a fifth, search-specific detail view that
renders its own copy of a conversation transcript / escalation card / document
/ curated answer, or make search a way *into* the four pages that already
render that content.

## Decision

**One endpoint, `GET /admin/api/{slug}/search?q=`, and no new detail view.**

- Gated on `documents.read` as the floor (every builtin role holds it), with
  `conversations.read` and `handoffs.read` re-checked independently per
  category — a custom role holding the floor without one of those still gets
  the categories it can actually see, rather than a 403 for the whole box.
- Five results per category, case-insensitive substring match
  (`func.lower(col).contains(...)`, portable across the SQLite dev / Postgres
  prod split this repo already commits to — ADR-0003).
- Conversation snippets run through `classifier.redact_contact()` before
  they're returned, same as both aggregate reports (see `CLAUDE.md`, "The two
  reports") — a customer can volunteer a phone number mid-question, and that
  must not surface unredacted in a search result any more than in a
  dashboard signature.
- **`pin=` on `list_conversations` and `list_handoffs`**: force-includes one
  record by id, fetched and prepended outside the normal cap/filter, never
  counted against it. A search hit for a conversation from three weeks ago —
  well outside the recent-100 window — opens by asking the existing endpoint
  for exactly that row, then the existing expand-in-place transcript UI
  (`loadMsgs`) renders it. Escalations the same way, through
  `toggleHandoffDetail`, bypassing whatever status tab happens to be selected.
- Knowledge Base and Curated Answers needed no equivalent: both endpoints
  already return every row for the tenant, uncapped, so a search hit just
  opens the same "Edit" flow (`docForm`) or the same expand-in-place answer
  editor (`faqForm`) their own pages use for a row already on screen.

## Consequences

- A second detail view was the more obvious build and would have been
  strictly more flexible — the search result could show exactly what search
  wants, not what the host page happens to render. What's actually saved is a
  second place for the "what does a teller see when they open a conversation"
  question to drift out of sync with the first. That tradeoff is deliberately
  taken.
- `pin` is a narrow door, not a general query parameter: it force-includes
  **at most one** row, verified against the caller's `bank_id` and (for
  handoffs) `needs_person`, so it cannot be used to page through a tenant's
  full history a row at a time or to pull a general-knowledge row into the
  Escalations queue it was deliberately kept out of.
- Merging the two conversation-match queries (direct field match, and a
  `Message.text` join) happens in **Python** via `dict.fromkeys()`, not a SQL
  `DISTINCT ... ORDER BY` — Postgres rejects that construction when the
  `ORDER BY` column isn't in the `SELECT` list, and this repo's session
  history already has one query-portability trap from assuming SQLite's
  laxer rules would hold in production.
- Search itself has no cross-tenant or permission test surface beyond what
  `documents.read`/`conversations.read`/`handoffs.read` already enforce
  everywhere else — `tests/test_global_search.py` asserts isolation and
  scoping directly against the endpoint rather than trusting that reusing
  existing dependencies was enough on its own.

## References

- `bankassist/api.py` — `global_search`, and the `pin` parameter on
  `list_conversations` / `list_handoffs`.
- `tests/test_global_search.py`
- ADR-0003 (sync SQLAlchemy, the SQLite/Postgres split this endpoint's
  matching has to stay portable across)
- ADR-0007 (multi-tenancy by `bank_id` filter)
