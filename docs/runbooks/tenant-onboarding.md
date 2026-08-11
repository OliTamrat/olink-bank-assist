# Onboarding a tenant

## A prospect (pitch-demo) tenant

A fifth prospect is a content file, not new plumbing
(`seed_common.py: seed_prospect_bank()`): aliases/name/colour, a `_DOCS`
list, one `seed()` call. Every figure must carry a source and pull date —
follow `SOURCES_DASHEN.md` as the template. The mandatory disclaimer banner
is applied by `prospect_disclaimer()`; **do not** remove it or make it
conditional (ADR-0009 — trademark and regulatory risk with a real,
non-consenting bank).

## A real, signed bank

1. Create the tenant + admin users (roles are per-bank rows; permissions are
   code — see `docs/per-person-logins.md`).
2. Load **their** verified content through the admin panel or `ingest.py` —
   never repurpose a prospect tenant's scraped corpus.
3. **The corpus is the ceiling.** Fifteen documents answer fifteen documents'
   worth of questions; a real bank's site is hundreds of pages. Content work
   moves the answer rate more than any model change — check corpus size
   before tuning anything else.
4. Connect channels as the bank's credentials arrive (`docs/integrations/`).
   Telegram and Viber are same-day; Meta and SMS have external clocks.
5. Curate: watch Content Gaps (built from handoff misses), promote the
   answers everybody asks for into curated FAQs, run the translation loop
   (`faq-translation-loop.md`).
6. Before go-live: golden-question evals green, disclaimer replaced by the
   bank's own legal text, data-residency posture agreed (Art. 22 — in-country
   deployment path exists via Ethio Telecom ECS).
