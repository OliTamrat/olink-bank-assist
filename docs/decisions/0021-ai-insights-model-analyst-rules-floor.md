# ADR-0021 — AI insights: the model is the analyst, the rules are the offline floor, and no customer text reaches it

**Status:** accepted · **Date:** 2026-08-12

## Context

The founder asked for AI-powered analytics: a layer above the numbers that
tells a manager what to *do*. The first design inverted the emphasis —
deterministic threshold findings as the product, with the model writing
optional prose over them, presented as a panel at the bottom of the
Performance page. **The founder reviewed it before merge and rejected three
things at once: it was too rule-based to be called AI, the panel's look was
an afterthought, and the bottom of another page was the wrong surface
entirely.** That review is the context for this record; the design below is
the second, accepted one.

Two constraints survived the redesign untouched, because they are doctrine
rather than taste:

- The page must work with no model configured (extractive-mode rule — the
  product is demoable in every configuration, its analytics included).
- No customer text may reach a model from an analytics surface gated only
  by `analytics.read`.

## Decision

**The model is the analyst.** `llm.analyze_operations` receives the full
aggregate picture — Overview (volumes, deflection, per-day series, language
outcomes, channel mix), Performance (desks, live-call funnel, staffing, the
hourly load matrix) and the machine-computed findings *as hints only* — and
composes a structured brief itself: a one-sentence headline, two to four
assessment sections, two to four actions each tagged `now`/`soon`/`later`.
The reply is strict JSON, validated by `_parse_brief`; anything malformed is
treated exactly like an unreachable model, because a half-parsed brief is a
worse page than an honest fallback.

**The threshold rules (`insights.py`) are demoted to the offline floor.**
They render — translated through the admin string table like any other
label — only when there is no model, the call fails, or the reply does not
parse. They also ride along in the digest as `machine_findings`, hints the
model may confirm, reprioritise or supersede.

**AI Insights is its own page**, in the rail after Performance, designed as
a brief rather than a list: headline hero (the same brand-tinted banner
language as the dashboard's welcome), action cards above the assessment so
the page answers before it explains, prose sections in panels. **Opening
the page is the consent for the model call** — no button to find first —
with the result cached per (window, language) so navigating around the
console does not re-bill a call whose numbers have not moved. Regenerate
forces a fresh one; the window control re-analyzes for the chosen range.

**No customer text reaches the model, structurally.** The digest excludes
`top_topics` — the one aggregate field carrying (already-redacted) customer
wording. The prompt's "use only the numbers given" is the second fence;
what the model is *given* is the first. A test posts a real chat message
and asserts its words never appear in what the model receives.

## Consequences

- **Cost, stated plainly:** one model call per page open per (window,
  language), plus regenerates. The cache bounds it; a future auto-refresh
  or scheduled-report feature must budget for its own calls explicitly.
- **The brief's quality is the model's quality**, including in OM/TI/SO/SW.
  The fallback findings remain the reviewed floor beneath it, and the
  verify-before-acting caption stays on the page in both modes.
- The model may weight things differently than the thresholds would — that
  is now the point, not a bug. The machine findings remain in the payload
  (`findings`) alongside the brief, so a supervisor asking "why did it say
  that" always has the deterministic view to compare against.
- The first design's panel-on-Performance is gone; Performance stays a
  numbers page, and the two surfaces link by adjacency in the rail rather
  than by sharing a scroll.

## References

- `bankassist/insights.py` (fallback rules + thresholds),
  `llm.analyze_operations` + `_parse_brief` (contract + validation),
  `GET /admin/api/{slug}/analytics/insights`
- `tests/test_insights.py` — the digest-carries-no-customer-text test, the
  malformed-brief degradation test, the priority-coercion test, and the
  every-fallback-key-has-a-six-language-template pin
- ADR-0013 (docs tested against code); the extractive-mode doctrine in
  `CLAUDE.md`
