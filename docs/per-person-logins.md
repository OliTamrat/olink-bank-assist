# Identity and access control — scope

Status: **steps 2 and 3 shipped; step 1 blocked on a domain; steps 4–5 open.**
Last updated 2026-08-08.

| Step | State |
|---|---|
| 0. Domain | ⛔ not started — user-side, and it gates step 1 |
| 1. Email service | ⛔ blocked on step 0 |
| 2. Identity core | ✅ merged (#62) and **live** — migration 0010 applied in production, revision `bankassist-00101-vb9` |
| 3. Authorization | ✅ merged (#64) — 15 routes, migration 0011 |
| 4. Admin UI | ⏭ next: login screen, Users tab, and the visual rework |
| 5. TOTP | ⏭ deferred by decision, should not drift far behind step 3 |

## Why

The admin panel authenticates a *tenant*, not a *person*. One shared bearer
token per bank, in every operator's browser. Three consequences:

1. **Nobody can be removed.** Someone leaves the bank and the only remedy is
   rotating the token for everyone who remains.
2. **Nothing records who acted.** `Handoff` carries a resolution note and
   deliberately has no `resolved_by` — a name there would have been a guess
   dressed up as an audit trail.
3. **The audit log says `"admin"`.** Every entry, for every person.

#59 made a rejected attempt visible and rate-limited it. That is detection. It
is not identity, and no amount of it becomes identity.

## What changed from the first draft, and why

The first version of this document recommended admin-set passwords, two
hardcoded roles, and no MFA — then listed the resulting weaknesses underneath.
That is the wrong shape for a decision record. **If a control cannot be
implemented, the design is depending on process discipline instead of the
system**, and writing the gap in the margin does not close it.

Three things failed that test and were changed:

- **Email was treated as a missing convenience.** It is three missing security
  controls: invitation without a spoken secret, self-service reset without an
  admin handling plaintext, and *notification* — nobody is ever told "your
  password changed" or "a new device signed in". Notification is how a
  compromise gets noticed at all.
- **Roles were strings compared in route handlers.** Every new distinction
  would be a code change plus a migration, no tenant could have its own org
  structure, and an auditor asking "who can do what" would be pointed at an
  enum in source.
- **`password_hash` was welded onto `users`.** A bank will require SSO against
  its own directory, and the reason matters more than the preference: when IT
  disables a leaver's account, they must lose access here too. With local
  passwords they do not — which is this feature's own failure mode,
  reintroduced one level up.

## Architecture

### Identity is separate from credentials

```
users               id, bank_id, email, display_name, disabled_at,
                    created_at, last_login_at

user_credentials    id, user_id, kind, secret_hash, verified_at, created_at
                    kind ∈ {password, totp, oidc}

sessions            id, user_id, token_hash, expires_at, revoked_at,
                    created_at, created_ip, user_agent
```

Splitting credentials out is what makes SSO additive later rather than a
rewrite: an OIDC subject becomes another row, and nothing about `users`,
`sessions` or authorization changes. It is also what lets one person hold a
password *and* a TOTP secret without a second nullable column per method.

**Server-side sessions, not JWTs.** The entire point is removing someone. A
stateless token cannot be revoked before it expires, which defeats the feature
it is meant to deliver. `revoked_at` is what makes "disable this person" take
effect on their next request rather than in an hour.

**Only hashes are stored** — of passwords, of session tokens, of TOTP
recovery codes. A database read must never yield a working credential.

`disabled_at` rather than deleting a row: an audit entry referencing a user id
has to still resolve after that person leaves.

### Permissions are the unit of authorization

Routes declare a permission, never a role:

```python
@app.post(...)
def create_document(user: User = Depends(require(Perm.DOCUMENTS_WRITE))): ...
```

Roles are **named bundles of permissions, stored as data**. Adding a role, or
letting a bank define its own, never touches route code — and the permission
matrix becomes a table that can be handed to an INSA reviewer instead of an
enum buried in source.

| Permission | Routes |
|---|---|
| `analytics.read` | `GET /analytics` |
| `conversations.read` | `GET /conversations`, `GET /conversations/{id}/messages` |
| `handoffs.read` | `GET /handoffs` |
| `handoffs.resolve` | `POST /handoffs/{id}/close`, `/reopen` |
| `gaps.read` | `GET /content-gaps` |
| `documents.read` | `GET /documents` |
| `documents.write` | `POST /documents`, `/documents/bulk`, `PUT`, `DELETE` |
| `integrations.manage` | `POST /telegram/connect`, `POST /handoff-webhook` |
| `users.manage` | user routes (new) |

Ships with two built-in roles:

- **operator** — everything `.read`, plus `handoffs.resolve`
- **admin** — operator, plus `documents.write`, `integrations.manage`,
  `users.manage`

`conversations.read` is deliberately its own permission even though both
built-in roles hold it. Conversation transcripts are customer personal data;
analytics is aggregated and contact-redacted. The first bank that wants a
manager who sees the numbers but not the transcripts gets that without a
schema change — and under Art. 22 that distinction is likely to be asked for.

`integrations.manage` is the sharpest reason the operator/admin line exists at
all: `POST /handoff-webhook` decides where customers' phone numbers are sent,
and the person calling customers back is not the person who should be
repointing it.

### Email is part of the security design

Needed for three things, not one:

- **Invitation.** A signed, single-use, expiring link. No initial secret is
  ever spoken aloud or typed into a chat window.
- **Reset.** Self-service. No admin ever holds another person's plaintext.
- **Notification.** Password changed, MFA enrolled or removed, sign-in from a
  new device, account disabled. This is the control that turns a silent
  compromise into a phone call.

Resend, following the pattern `olink-dispatch` already runs. Delivery failure
must never block the action it reports — the same rule the handoff webhook
follows.

#### A sending domain is a hard prerequisite

**This product has no custom domain at all today.** `APP_BASE_URL` points at
the raw Cloud Run URL, so the admin panel, the widget and any link in an email
all live at `bankassist-…run.app`.

That blocks step 1, and not for cosmetic reasons. The recipients of these
emails are bank staff — the population most trained to distrust an unexpected
link. An invitation whose sender domain and link domain disagree is
indistinguishable from phishing, and its entire job is *"click here to set
your password"*. The sending domain and the product domain must therefore
agree, which also rules out the cheap option of borrowing `olinkgo.us`: a bank
that looks that up finds a US trucking dispatch company.

Needed before step 1 ships:

1. A registered domain (decided: a new dedicated one; name pending).
2. A Cloud Run domain mapping, so `APP_BASE_URL` stops being a `run.app` URL.
3. Resend domain verification — DKIM, SPF, and a DMARC record.
4. A real deliverability test into an Ethiopian corporate mailbox, *before* a
   pilot rather than during one.

**Naming carries a regulatory question worth checking first.** The National
Bank of Ethiopia licenses banks, and "bank" in a trading name is commonly
restricted to licensed institutions. "Olink Bank Assist" as a product name is
very likely fine — it plainly describes software sold *to* banks — but a
domain like `olinkbank.com` reads as a claim rather than a description. Worth
one question to counsel before registering, because a domain is cheap to
choose well and expensive to change once it is printed on a proposal, baked
into every widget embed, and verified as a sending identity.

### MFA — deferred to its own change

TOTP on the local-credential path: no email or SMS dependency, recovery codes
issued once and stored hashed. Under SSO the identity provider owns MFA, so
this only ever matters for the password path — which is the fallback a small
MFI will actually use.

**Deliberately not in the first pass.** It slots in cleanly afterwards
*because* the architecture above is right: credentials are already a separate
table keyed by `kind`, so a TOTP secret is another row rather than a schema
change. Deferring it costs nothing structural, which is the only reason
deferring it is acceptable.

What it does cost is an answer. INSA certification is a documented Phase 3
requirement and Onekof is already certified P1–P6; an access-control review
will ask about MFA, and until this lands the honest answer is "designed for,
not yet built". That is a fine answer before a pilot and a poor one during
procurement, so it should not drift far behind step 3.

## The shared token survives, narrowed

`Bank.admin_token` is **not** deleted. It becomes break-glass and automation:

- Creating the first user for a tenant — without it, a fresh tenant has no way
  in.
- Script and integration access with no person involved.
- Recovery when the last admin locks themselves out.

Its audit entries stay `actor="admin-token"` — honest about being an
unattributable credential and distinguishable at a glance from a person. It
holds all permissions, and that is precisely why every use of it is logged as
such.

Removing it would let a tenant be locked out with no recovery: a worse failure
than the one being fixed.

## Sequence

Each step is independently deployable, and the shared-token path stays alive
throughout so a mistake cannot lock a bank out of its own dashboard.

0. **Domain.** Register, map to Cloud Run, verify in Resend. Not code, and it
   gates step 1 — see above.
1. **Email service.** Resend client, templates, failure-swallowing. No user
   surface yet.
2. **Identity core.** Migration, password hashing, sessions, login/logout,
   invitation and reset flows.
3. **Authorization.** Permission registry, role bundles, applied to all 15
   routes — the count was 14 in the original scope, which missed
   `POST /users` itself. `audit_log.actor` becomes the person;
   `handoffs.resolved_by` populated.
4. **Admin UI.** Login screen, session cookie, logout, Users tab — and the
   UI/UX rework the current dashboard needs, which this is the natural moment
   for rather than bolting a form onto the existing page.
5. **TOTP.** Enrolment, verification, recovery codes. Deferred out of the
   first pass, but it should not drift far behind step 3 — see above.

Step 3 is the one that can break existing access, so it landed after identity
was proven **in production** — migration 0010 confirmed applied in the deploy
log, not assumed — and before the UI depends on it.

Steps 2 and 3 both shipped with **no user-facing change**, exactly as the
sequence predicted. The dashboard still authenticates with the shared token,
which retains every permission, so nothing an operator does today behaves
differently. That is the cost of building the foundation first, and it is the
point: the access-control model was proven against the real route table before
a single screen depended on it.

## Deliberately not building

- **Attribute-based access control.** Permissions-as-data gives the
  flexibility; ABAC gives a policy engine nobody has asked for.
- **A custom role-builder UI.** The mechanism supports custom roles; the
  screen for it waits for a bank that wants one.
- **SCIM provisioning.** Real for a large bank, meaningless before one exists.
- **SSO in this pass.** Additive by design, and it needs a real identity
  provider to test against rather than assumptions.
- **Password composition rules** beyond a length minimum. Arbitrary rules
  produce `Bank@2026!` on a sticky note.
- **Cross-tenant users.** A person administering two banks gets two accounts.

## Risks

- **This is the largest change since the project started** and it touches
  every admin route. The migration is additive; the route changes are the
  dangerous part, which is why the token path stays alive through all of it.
- **Sessions add a database query per request.** A JWT would not. This is the
  correct trade — revocation is the feature — but it does couple the admin
  panel to database health, and that should be a known property rather than a
  surprise.
- **Email deliverability into Ethiopian corporate mail is unproven here.** If
  invitations do not arrive, onboarding stalls. Worth testing against a real
  bank domain early rather than discovering it during a pilot.
- **Sequencing puts email before anything visible.** Two steps land with no
  user-facing change. That is the cost of building the foundation first, and
  it is the point.
