# ADR-0021 — AI insights: rules are the floor, the model writes prose on top, and no customer text reaches it

**Status:** accepted · **Date:** 2026-08-12

## Context

The founder asked for AI-powered analytics: a layer above the Performance
page's numbers that tells a manager what to *do*. The obvious build — hand
the analytics to a model and render whatever comes back — fails this
product's own doctrine three ways: it makes a model a hard dependency of a
page that must stay demoable without one (extractive-mode rule), it puts
unexplainable claims in front of a bank (the same reason `departments.py`
is rules, not a model call), and it creates a new path by which customer
text could reach a model from an analytics screen gated only by
`analytics.read`.

## Decision

**Two layers, in a fixed order (`insights.py`):**

1. **Deterministic findings are the feature's floor.** Every finding is a
   named threshold over the aggregates Overview and Performance already
   compute — testable, explainable to a supervisor, translated through the
   admin string table like any other label (the client renders
   `insight_<key>` templates, so the findings are fully six-language with
   no model involved), and available with no model configured. Every rule
   carries a denominator floor, because a rate over three events is noise
   and findings built on noise teach a manager to ignore the panel.
2. **The model writes prose over a digest of those same aggregates —
   opt-in per request, never on page load.** The narrative is a button, not
   a poll: findings are free, a model call is not. `LLMUnavailable`
   degrades to the findings, which are not an error state.

**No customer text reaches the model from this feature, structurally.** The
digest is built from the aggregate payloads with `top_topics` — the one
field carrying (already-redacted) customer wording — excluded entirely.
The prompt's "use only the numbers given" instruction is the second fence;
what the model is *given* is the first. This is what lets the endpoint sit
behind the same `analytics.read` gate as the reports it reads.

**The narrative is labelled and hedged in the UI** ("written from the
aggregate numbers on this page — verify before acting"), the same honesty
posture as the general-knowledge path's labelling.

## Consequences

- **Cost, stated plainly:** deterministic rules will miss patterns a model
  would catch, and the thresholds (`insights.py` constants) will need
  tuning against real pilot traffic. That trade buys explainability and a
  panel that works in the sandbox, in CI, and for a tenant with no Gemini
  configured.
- The one-narrative-per-click cost model holds only as long as the frontend
  keeps `narrative=1` off the page-load path — a future "auto-refresh
  insights" feature must budget for that explicitly.
- A model-written brief in OM/TI/SO/SW inherits those languages' model
  quality; the findings templates (first-pass drafted, like all staff-panel
  strings) are the reviewed floor beneath it.

## References

- `bankassist/insights.py` (rules + thresholds), `llm.summarize_operations`
  (prompt + budget), `GET /admin/api/{slug}/analytics/insights`
- `tests/test_insights.py` — including the digest-carries-no-customer-text
  test and the every-finding-has-a-six-language-template test
- ADR-0013 (docs tested against code), the extractive-mode doctrine in
  `CLAUDE.md`
