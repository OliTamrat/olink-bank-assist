# ADR-0022 — Desk assignment is a manager's tool as well as a self-declaration

**Status:** accepted · **Date:** 2026-08-12 · **Supersedes the self-only
half of ADR-0020**

## Context

ADR-0020 shipped teller expertise as self-declared only, mirroring the
language-declaration precedent, with manager visibility (the Team page's
Coverage column and Desk Teams cards) but no manager control — and named a
manager-set path as the open next step "if self-declaration proves
insufficient."

The founder's review settled it the same day: **a coverage view a manager
cannot act on is a report, not a tool.** The Desk Teams cards showed the
gaps and offered nothing to do about them — no way to add someone to a
desk, move them, or take them off one; the only action on the whole Team
page was Disable. The languages analogy also does not carry the whole way:
whether you can hold a conversation in Afaan Oromoo is a fact about you,
but *which desks you work* is a staffing decision — who has been trained
on what is exactly the thing a manager runs.

## Decision

**Both hands on the same field.** `users.teller_departments` is now set two
ways, with identical validation and canonical storage:

- **Self**, unchanged: `PUT /teller/expertise` (`teller.serve`, self-only)
  from the Live queue.
- **Manager**: `PUT /admin/api/{slug}/users/{user_id}/expertise`
  (`users.manage` — the Team page's own gate). Refused for a disabled
  account and for anyone who does not hold `teller.serve` (409): a desk
  assigned to somebody routing can never offer work to would make the
  roster look covered while routing as if it were not. Audited under its
  own action, `teller_expertise_assigned`, with the manager as the actor —
  a disagreement between a manager's assignment and a teller's
  self-adjustment is a visible conversation in the audit log, not a silent
  overwrite. Last write wins, deliberately: an approval workflow here would
  be ceremony around a decision teams settle by talking.

**The Team page becomes the management surface.** A desk card opens "who
handles this desk" (tick people on and off it); each person's row gains a
Desks button opening "which desks does this person handle." Both save
immediately per toggle and repaint from what the server stored. Add,
remove and relocate are all the same primitive — membership toggles — so
there is one code path to trust.

**Languages stay self-only.** ADR-0020's reasoning holds there untouched.

## Consequences

- Two writers to one field means the audit log is now load-bearing for
  "who set this": `teller_expertise_updated` (self) vs
  `teller_expertise_assigned` (manager) name the hand that moved it.
- A manager can mis-assign — the mitigations are unchanged from ADR-0020's
  cost analysis (routing reorders, never hides; the teller can adjust
  their own; everything is visible), which is what made granting the
  control cheap.
- ADR-0020's *routing* design — reorder-never-hide, language outranks
  expertise, the anti-starvation tier — is untouched by this ADR.

## References

- `PUT /admin/api/{slug}/users/{user_id}/expertise` in `api.py`;
  `deskMembersModal` / `personDesksModal` in `admin.html`
- `tests/test_teller_expertise.py` — manager assignment, canonical order,
  audit actor, non-teller 409, cross-tenant 404, plain-teller 403
- ADR-0020 (the superseded self-only decision, and the routing design that
  stands)
