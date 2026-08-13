# ADR-0027 — A second factor for admin accounts

**Status:** accepted · **Date:** 2026-08-13

## Context

The founder asked whether to build self-serve signup and a pricing page. The
recommendation was to build neither — a product that white-labels itself as a
named bank must not let anyone create a tenant, and enterprise pricing does
not belong on a page — and to build **MFA** instead, because it is what a
bank's security questionnaire asks about on its first page, it has no
dependency on anything else, and it therefore parallelises with the Ethio
Telecom residency move exactly as the linguist review does.

The schema was already expecting it. `UserCredential.kind` has read
`password | totp | oidc` since per-person logins shipped, with a comment
saying it is a string precisely so that adding a method later is not a
migration in every environment.

## Decision

**TOTP written out, not pulled in** (`totp.py`). RFC 6238 is HMAC-SHA1 over a
counter — about twenty lines of `hmac` and `base64` — and the RFC publishes
test vectors. A hand-written implementation can be **proved** correct against
the standard in this repo's own suite, with no network and no trust in a third
party's release process; a dependency could only be trusted. All six SHA-1
vectors are asserted in `tests/test_totp.py`. Same trade as the
dependency-free BM25 retriever.

**The half-authenticated state lives on the session, not in a parallel
store.** A password that has been verified but not yet seconded has to exist
somewhere between two requests. A separate challenge table would be a second
thing that grants access, with its own expiry and revocation to get right.
Instead `admin_sessions.pending_mfa` marks it and **`admin_auth.resolve()`
returns None while it is set** — so the single gate every route in the product
already passes through is the one place that decides, and it fails closed. A
route written before MFA existed is still not reachable with a half-finished
login. Pending sessions expire in five minutes rather than eight hours.

**Replay is closed at the credential.** `user_credentials.last_used_step`
records the highest step spent, and `totp.verify` refuses anything at or below
it — which also retires the drift window, so the previous step's code stops
working the moment the current one is used. Without this, a code seen over a
shoulder or on a lock screen stays valid for its whole window plus the
allowance either side.

**Enrolment does not count until a code is proved.** The credential row is
written unverified; `verified_at` is set only after a working code. The
failure this prevents is somebody closing the tab between scanning the QR and
typing the first code, and being locked out by a secret nothing holds.

**Recovery codes are SHA-256, not Argon2** — 40 bits of machine-generated
randomness has no guessable structure for a slow hash to defend, and ten
Argon2 verifications per login attempt would make the login route a
denial-of-service amplifier. They are shown once, at activation, and are
destroyed when the factor is removed: leaving them would leave ten working
bypasses for an authenticator nobody holds.

**Turning it off costs the password again.** A signed-in session may be a
borrowed unlocked laptop, and removing a second factor from one is exactly
the move that turns momentary physical access into lasting access.
`banks.require_mfa` lets a tenant refuse the option entirely; it defaults
false, because switching it on for a bank whose staff have not enrolled would
lock all of them out at once.

## Consequences

- **Rendering the page found a bug the diff could not, and a pre-existing
  one.** The Security card was first placed on Settings, which is gated on
  `integrations.manage` — so only people who administer integrations could
  protect their own accounts. The same gate already sat in front of the
  *change-your-own-password* card, meaning **a teller could not change their
  own password**. Both now live on a new **Account** page carrying no
  permission at all, and `can(null)` now means "everyone" rather than
  silently "nobody".
- The `mfa/*` routes deliberately declare no permission, and
  `tests/test_permissions.py` records why: managing your own second factor is
  not a capability somebody grants you. They are not unauthenticated —
  `require_user` plus `_own_bank` mean a person can only ever act on their own
  credential, within their own tenant.
- **The per-bank admin token still bypasses all of this**, by design: it is a
  separate break-glass credential, rotated with
  `python -m bankassist.show_token <slug> --rotate`. The "use an admin token
  instead" link is hidden during the challenge — not because it would defeat
  it, but because an escape hatch that looks like a shortcut gets treated as
  one. **Retiring the token path is the natural next step** and is not in
  this change.
- 26 new strings across six languages. The call-site test caught two keys
  referenced by the panel and never added, which is the exact failure that
  test exists for.
- The second factor is rate-limited on the same limiter as the password, so
  an attacker cannot spend one budget to avoid the other.

## References

- `bankassist/totp.py`; `pending_mfa` / `complete_mfa` in `admin_auth.py`;
  the `mfa/*` and `login/mfa` routes in `api.py`; migration `0027`
- `tests/test_totp.py` (RFC 6238 vectors), `tests/test_mfa.py` (the wiring)
- ADR-0002 (permissions in code, roles in the database)
