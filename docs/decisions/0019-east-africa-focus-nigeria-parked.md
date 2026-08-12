# ADR-0019 — Regional focus narrows to East Africa; the Nigeria bundle is parked

**Status:** accepted · **Date:** 2026-08-12

## Context

ADR-0016 set the language-expansion order as Swahili → Hausa/Yoruba/Igbo (a
Nigeria-specific bundle) → Arabic, reasoned on reach per unit of effort.
Swahili shipped the same day (ADR-0018) and is East Africa's own language —
Kenya, Tanzania, Uganda, Rwanda. The founder's next instruction was explicit:
hold the Nigeria bundle and keep the product's language work inside East
Africa rather than making a second regional jump to West Africa immediately
after the first expansion.

## Decision

**The Hausa/Yoruba/Igbo bundle is parked, not cancelled.** The market case
recorded in ADR-0016 (real Nigerian bank precedent already running
WhatsApp/Telegram bots, an explicit "banking in Yoruba, Igbo, Hausa, and
Pidgin" competitor claim) still holds and is not being walked back — this is
a sequencing call, not a judgment that the opportunity is smaller than
thought.

**Any near-term language work stays evaluated against East Africa's reach
first**, building on the region Swahili already anchors, before a second
regional jump is reconsidered. Arabic's own sequencing (after the Nigeria
bundle, for the right-to-left engineering reason ADR-0016 already gave) is
unaffected by this — it was never a near-term candidate regardless of which
region comes next.

## Consequences

- **Real cost, stated plainly:** Nigeria's market is larger and its local
  competitive precedent is stronger than anything documented for the East
  African languages beyond Swahili. Parking it is a deliberate trade of
  reach for regional depth, not a free choice.
- **No new East African language is named here.** This ADR records the
  *regional* decision only — which languages (if any) follow Swahili within
  East Africa is still open and undecided; do not read this as committing to
  a specific next language.
- This is the second ADR to touch the roadmap ADR-0016 first set (ADR-0018
  being the first, recording Swahili's actual shipment). Per this repo's
  append-only ADR convention, ADR-0016 itself is left as the historical
  record of the original order and is not edited.

## References

- ADR-0016 (original language-expansion order and reasoning)
- ADR-0018 (Swahili shipped)
- `docs/market-position.md` — "Expanding language coverage"
