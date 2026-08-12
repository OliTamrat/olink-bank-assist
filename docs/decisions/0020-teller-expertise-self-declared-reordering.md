# ADR-0020 — Teller expertise is self-declared, and routing reorders, never hides

**Status:** accepted · **Date:** 2026-08-12

## Context

Not every teller knows every desk. A fraud report handled by somebody who
works cards gets a slower, worse answer than the same report handled by the
fraud desk — and the product already knows what a session is about, because
every escalation is classified onto one of eight desks by rule
(`departments.classify`, ADR to 0020's predecessor in migration 0020). The
live queue, though, treated all tellers as interchangeable: language routing
(migration 0019) was the only signal bending oldest-first order.

The founder's ask was explicit: classify tellers by subject-matter expertise,
because "all tellers do not have the same level of knowledge on their role,"
and use the service categories the product already has.

Two design questions had to be settled:

1. **Who declares a teller's expertise — the teller or a manager?**
2. **Does expertise filter the queue or reorder it?**

## Decision

**Expertise is a set of desk codes on the user row (`teller_departments`,
migration 0026), declared by the teller themselves — `teller.serve` and
self-only, exactly like languages.** The language precedent's reasoning
transfers whole: what you can competently handle on a live call is a fact
about you, and the person who knows it is you. A manager who thinks the
declarations are wrong has a conversation to have, not a box to tick —
routing a fraud call to somebody a manager once labelled "fraud" produces a
call where the customer is no better served, with a record saying they
should have been. Managers get **visibility** instead: the Team page shows
every person's declared coverage, which is how a bank notices nobody has
declared the fraud desk.

**Routing reorders and never hides**, as a third term in `queue_order`'s
sort key: `(starving, language-mismatch, expertise-mismatch, -waited)`.
Language outranks expertise deliberately — a conversation the teller cannot
hold at all is worse than a desk they know less well. Past `PATIENCE`, both
matches stop mattering entirely and the longest wait wins, the same
anti-starvation rule language routing already carries.

**The session's desk is classified from the customer's own words at request
time** (`TellerSession.department`, same migration) — the last three user
messages through `departments.classify`, falling to GENERAL when there is
nothing to read. Undeclared expertise covers everything; an unclassified
session matches everyone (`teller.covers`, the same semantics as
`teller.speaks`, on purpose — two predicates with different fail-open rules
would make the queue unexplainable).

## Consequences

- **Nothing changed for a bank that does nothing.** Every teller starts
  undeclared and every declaration only narrows what is *offered first* —
  the day-one queue is byte-identical to the day-zero queue. This is the
  same shipping rule migration 0019 wrote down.
- **The cost of self-declaration, stated plainly:** a teller can declare
  themselves into (or out of) work, and the product takes their word for it.
  The mitigations are the Team page's coverage column (a wrong declaration
  is visible, not silent), the audit log (`teller_expertise_updated`), and
  the fact that routing never hides — a mis-declaration reorders offers, it
  cannot orphan a customer.
- A manager-set override (or a manager *proposal* the teller confirms)
  remains open as a future step if self-declaration proves insufficient in
  a real pilot; nothing in this design blocks it.
- The queue card now shows each session's desk, so even an undeclared teller
  sees what a call is about before taking it — worth having independent of
  routing.

## References

- Migration `0026_teller_expertise.py`; `teller.covers` / `queue_order`;
  `PUT /admin/api/{slug}/teller/expertise`; `tests/test_teller_expertise.py`
- Migration 0019 (teller languages — the precedent this mirrors)
- Migration 0020 + `departments.py` (the eight desks and their classifier)
