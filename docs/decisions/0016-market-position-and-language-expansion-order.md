# ADR-0016 — Positioning stays horizontal; Swahili leads the next languages

**Status:** accepted · **Date:** 2026-08-12

## Context

Zero pilots are signed yet, which raised the question of whether marketing
should stay narrowly scoped to "Ethiopian banking" until one closes, and in
what order to expand language coverage beyond the current five (English,
Amharic, Afaan Oromo, Tigrinya, Somali). Both questions came up together
because they are the same question: how wide does the product's story get to
be before it has proven itself once.

## Decision

1. **Positioning stays horizontal, not banking-only**, and does not wait on a
   signed contract to say so. The underlying capability — multilingual
   detection, multi-channel handoff with no lost context, tool-output-is-truth
   guardrails, in-country data residency — reaches insurance, telecom/MFIs
   and government services, not only banks. What earns the right to say this
   is depth already built (the guardrail's native-phrasing history, the
   machine-checked general-knowledge boundary), not a signature. Every pitch
   still leads with the concrete, verifiable thing before the horizontal
   claim.
2. **Ethiopia stays the lead market for a second reason beyond data
   residency and Telegram penetration:** Addis Ababa hosts the African Union
   and a dense concentration of international institutions, which is a
   distinct network-access advantage — reaching African business and policy
   leadership without it costing years of separate outreach elsewhere on the
   continent.
3. **Next languages: Swahili first, then Hausa/Yoruba/Igbo as a Nigeria
   bundle, Arabic after** (RTL layout is real engineering, not a string
   change — sequence it last). Unlike Amharic/Afaan Oromo/Tigrinya/Somali,
   these already have strong general-purpose AI/NLP support, so the guardrail
   discovery phase should be materially faster — but native-speaker review of
   the account guardrail and every security rule still ships before a
   language is called done. That review is being resourced directly rather
   than tracked as an open risk here.
4. **The global search bar ships before language-expansion work starts.**

## Consequences

- Claiming reach across industries with zero production deployments is a
  real risk of sounding thinner than a single deep vertical claim — mitigated
  by sequencing (lead with the specific, verified thing), not by staying
  silent about the horizontal capability.
- Committing to Swahili next means the Nigeria-language bundle (Hausa/Yoruba/
  Igbo) and Arabic wait, even though Nigeria has the stronger documented
  local precedent (multiple banks already running channel bots there).
- A wrong guess on "these languages need less native-review effort" is
  itself a guess until the first one ships — the plan assumes it, the review
  step still gates it either way.

## References

`docs/market-position.md` (the fuller version of this reasoning, including
the Glia competitive comparison and the language-requirements breakdown),
ADR-0008 (five languages as complete string tables), ADR-0009 (prospect
disclaimers — why no tenant here is "live" yet).
