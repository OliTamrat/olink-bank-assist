# Per-person admin logins — scope

Status: **scoped, not started.** Decisions below were taken 2026-08-08.

## Why

The admin panel authenticates a *tenant*, not a *person*. One shared bearer
token per bank, in every operator's browser. Three consequences, and the third
is the one procurement stops on:

1. **Nobody can be removed.** Someone leaves the bank and the only remedy is
   rotating the token for everyone who remains.
2. **Nothing records who acted.** `Handoff` carries a resolution note and
   deliberately has no `resolved_by` — a name there would have been a guess
   dressed up as an audit trail.
3. **The audit log says `"admin"`.** Every entry, for every person.

#59 made a *rejected* attempt visible and rate-limited. That is detection. It
is not identity, and no amount of it becomes identity.

## Decisions taken

### Passwords, set by a tenant admin

**There is no email capability in this repo at all** — no Resend, no SMTP.
That rules out invite links, magic links and self-service password reset until
email exists, and it is the constraint that shaped everything else.

So: an admin creates a user and sets an initial password, handed over in
person or by phone. Reset means an admin sets a new one.

The honest weakness is that handover — a password read down a phone line is a
password that has been transmitted in the clear, and there is no
force-change-on-first-login without a way to notify anyone. Mitigated by
making the initial password single-use in practice: the user is prompted to
change it on first login, and an admin can see (but never read) whether they
have.

Wiring email later upgrades this in place — invites and resets become
additional paths to the same `users` table, not a rewrite.

### Two roles: operator and admin

The split follows what the routes actually do rather than an org chart.

| Route | operator | admin |
|---|---|---|
| `GET /analytics` | ✅ | ✅ |
| `GET /conversations`, `/conversations/{id}/messages` | ✅ | ✅ |
| `GET /handoffs` | ✅ | ✅ |
| `GET /content-gaps` | ✅ | ✅ |
| `GET /documents` | ✅ | ✅ |
| `POST /handoffs/{id}/close` | ✅ | ✅ |
| `POST /handoffs/{id}/reopen` | ✅ | ✅ |
| `POST /documents` | — | ✅ |
| `POST /documents/bulk` | — | ✅ |
| `PUT /documents/{id}` | — | ✅ |
| `DELETE /documents/{id}` | — | ✅ |
| `POST /telegram/connect` | — | ✅ |
| `POST /handoff-webhook` | — | ✅ |
| user management (new) | — | ✅ |

The principle: **an operator works the queue; an admin changes what the
assistant says and where the data goes.** The person calling customers back is
not the person who should be re-pointing the handoff webhook at a new
endpoint, and `POST /handoff-webhook` is the sharpest example — it decides
where customers' phone numbers are sent.

Read access is deliberately *not* split further. A viewer role was considered
and dropped: it adds a tier to test and explain, and nothing in the current
surface justifies it. It can be added later without a migration.

### No MFA in the first pass

TOTP needs no email or SMS, so it is a contained addition later. Bundling it
now doubles the surface of the change — enrolment, recovery codes, the
lost-my-phone path — and delays the thing that actually unblocks a bank.

## Data model

```
users
  id, bank_id, email, password_hash, role, must_change_password,
  disabled_at, created_at, last_login_at

sessions
  id, user_id, token_hash, expires_at, revoked_at, created_at,
  created_ip, user_agent

handoffs
  + resolved_by            (nullable; null for every row that predates this)
```

**Server-side sessions, not JWTs.** The whole point is being able to remove
someone. A stateless token cannot be revoked before it expires, which defeats
the feature it is meant to deliver. `revoked_at` is what makes "disable this
person" take effect on their next request rather than in an hour.

**Only the hash of a session token is stored**, exactly as for a password. A
database read must not yield a working credential.

`disabled_at` rather than deleting the row: an audit trail that references a
user id has to still resolve after that person leaves.

## The shared token survives

`Bank.admin_token` is **not** deleted. It becomes a break-glass and automation
credential:

- It is how the first user for a tenant gets created. Without it, a fresh
  tenant has no way in.
- It is how a script authenticates, with no person involved.
- It is the recovery path when the last admin locks themselves out.

Its audit entries stay `actor="admin-token"` — honest about being an
unattributable credential, and distinguishable at a glance from a person.

Removing it would mean a tenant could be locked out with no recovery, which is
a worse failure than the one this change fixes.

## Auth flow

1. `POST /admin/api/{slug}/login` — email + password. Constant-time compare,
   same 401 and the same failure counter as #59 whether the email is unknown,
   the password is wrong, or the user is disabled. A login form that
   distinguishes them is an account-enumeration oracle.
2. Session token returned in an **httpOnly, Secure, SameSite=Lax cookie**, not
   in the response body. The current token lives in `localStorage`, which any
   XSS on the page can read; httpOnly means script cannot.
3. `POST /logout` revokes the current session. `POST /users/{id}/disable`
   revokes every session that user holds.
4. Sessions expire on an absolute deadline. No sliding renewal in v1 — a
   session that renews forever is not a session.

## Explicitly out of scope

- MFA (separate, later)
- Email of any kind
- SSO / OIDC
- Password complexity rules beyond a minimum length — arbitrary composition
  rules push people toward `Bank@2026!` and a sticky note
- A viewer role
- Cross-tenant users. A person who administers two banks gets two accounts;
  merging identities across tenants is a different product.

## Work breakdown

Four changes, each independently deployable:

1. **Schema + login.** Migration, hashing, `POST /login` / `/logout`, session
   dependency alongside the existing token path. Nothing switches over yet.
2. **User management.** Create, list, disable, change-own-password, set-password.
   Admin-only. Bootstrap via the shared token.
3. **Migrate the routes.** All 14 accept either credential; role enforcement
   applied; `audit_log.actor` becomes the person's email; `handoffs.resolved_by`
   populated.
4. **The UI.** Login screen, cookie-based session, logout, a Users tab.

Step 3 is the one that can break existing access, so it lands last among the
API changes and keeps the token path working throughout.

## Risks worth naming up front

- **This is the largest single change since the project started**, and it
  touches every admin route. The migration is additive and reversible; the
  route changes are not, in the sense that a mistake locks a bank out of its
  own dashboard. The token path staying alive is the mitigation.
- **The initial-password handover is the weak link** and no amount of code
  fixes it. Email would; that is the argument for doing email sooner.
- **Sessions in the database add a query per request.** At MVP traffic this is
  noise, but it is a real coupling: the admin panel stops working if the
  database is slow, where a JWT would not. That is the correct trade here —
  revocation is the feature.
