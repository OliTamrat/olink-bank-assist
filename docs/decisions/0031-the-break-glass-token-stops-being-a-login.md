# ADR-0031 — The break-glass token stops being a login

**Status:** accepted · **Date:** 2026-08-14

## Context

Every tenant has an `admin_token`: one long random string, held in the
environment, sent as `X-Admin-Token`. It predates per-person logins. When
people got their own accounts the token was left in place as the
break-glass credential, and when MFA shipped (ADR-0027) it was left in
place again — deliberately, and recorded as such: *"the per-bank admin
token still bypasses MFA. Retiring it is the natural next step and is not
done."*

That note was honest but it understated the problem. **The token is not a
person.** It cannot hold a second factor, because there is nobody to hold
it. So every route the token reached was a route where two-factor could be
walked past by anyone holding one shared string, and an account with MFA
switched on was only ever as strong as its bank's token was secret. That
is not what a bank understands "we require two-factor" to mean, and it is
the second question on the security questionnaire that ADR-0027 exists to
answer.

It was not theoretical here. The founder had been signing in to Dashen
with the token for weeks, precisely because it was easier than the
password.

## Decision

**The token authenticates only while a tenant has no users.**

```python
def _token_is_still_a_credential(db, bank) -> bool:
    return count_of_users(bank) == 0
```

Once one user account exists on a tenant, a correct token gets **403** with
a message naming the replacement — *"Sign in with your email and
password."* — not a 401, because a 401 reads as "wrong token" and would
send a person hunting for a better one.

### Why not delete it outright

Because of the circle it was invented to break: a tenant with no users has
nobody who could authorise creating the first one. Deleting the token
means the first administrator has to be inserted by hand into the database
of every new tenant, which is worse than what we have — it puts a human
with SQL access into the onboarding path of every customer.

So the token keeps exactly that one job and loses every other. On a fresh
tenant it can create the first administrator. The moment that person
exists, it stops being a credential.

### Why the gate is tenant state, not a route allowlist

The obvious alternative is a list of routes the token is still allowed to
reach. It was rejected because such a list is only correct on the day it
is written: a route added later is a route nobody remembers to add to the
list, and the failure mode is silent — the token quietly regains reach.

Scoping by tenant state has no such drift. On a tenant with zero users
there is nothing to reach *except* bootstrap: every other route is about
content, conversations or colleagues that a brand-new tenant does not have
yet. A new route cannot become token-reachable later, because by the time
anyone is using the product the token has already stopped answering.

## Consequences

- **Ops must have a real account.** Confirmed safe before shipping: CBE is
  fully enrolled on MFA, and Dashen and Awash both have email logins.
- **Recovery is by recovery code, not by token.** Ten single-use codes are
  issued at enrolment and rotatable from the Account page behind a password
  check. That is the break-glass path now, and unlike the token it belongs
  to a person.
- **The test suite had to learn to sign in.** Roughly a third of the admin
  tests reached for the token because it was the shortest path to an
  authenticated request. `tests/conftest.py:create_user` now uses the token
  to create the *first* user and then signs in as that person for every
  later one — which means **the first user a test creates must be an
  admin**. This is not incidental tidying: a suite that authenticates by a
  route real users cannot use is a suite that stops testing the real
  boundary.
- **The rate limit and the audit trail are unchanged.** A wrong token is
  still 401 and still rate-limited; `TOKEN_ACTOR` still records bootstrap
  in the audit log. What changed is that being right is no longer
  sufficient.
