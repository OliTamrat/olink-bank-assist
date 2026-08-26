# ADR-0037: The bootstrap door gets a handle, and the password never touches argv

**Date:** 2026-08-26
**Status:** Accepted
**Supersedes:** nothing — implements ADR-0031

## Context

ADR-0031 retired the per-bank admin token as a login. It now authenticates
only while a tenant has **zero users** — enough to create the first
administrator, and after that a correct token gets a `403` naming its
replacement. That decision was right and is not reopened here.

What it shipped without was any way to walk through the door it left. The only
tooling on that path was `show_token`, which prints a token and leaves the
operator to hand-write an HTTP call.

The bill arrived on 2026-08-26, when sign-in failed on all four banks with
*"that email and password did not match"*.

**Separate what was measured from what was guessed here, because this ADR
originally ran them together.** Measured, and reproducible on a clean
database: a freshly seeded tenant holds documents and roles and **no users**,
so email-and-password sign-in on it cannot work until somebody bootstraps the
first administrator. That is itself correct — a seeded default account with a
known password would be far worse — and it is the whole justification for the
decision below.

What was *guessed* was that this described the live tenants. Nobody looked:
production is unreachable from an agent sandbox, and the conclusion came from
replaying the deploy sequence locally. The founder later recalled having
created an administrator through the token, which if right means at least one
live tenant does have users and his lockout was a forgotten password, not an
empty table. Both causes produce the identical sentence on the identical
screen, which is the actual finding:

**the sign-in screen cannot distinguish "no account exists here" from "wrong
password" from "the token retired", and neither could the session spent
diagnosing it.** It looks identical to a broken deploy and a dead database
too. That is a defect in its own right, tracked separately.

The decision below is unchanged by which cause it was: a tenant with no users
needs a way to make the first one, and there wasn't one.

Two properties had to hold for whatever replaced that.

**The password must never be an argument.** `argv` is the shell's history
file, the process list on a shared box, and any CI log that echoes the
command. This is not a hypothetical for this repository: all four admin tokens
were rotated on 2026-08-10 after one appeared in a build log.

**It has to work for someone who does not hold the connection string.** The
command writes to the database directly, so it needs one. The person locked
out may not have it to hand, and the production database is unreachable from
an agent sandbox in any case.

## Decision

`python -m bankassist.create_admin <slug> --email you@bank.et` creates a
tenant's first administrator. It prompts twice with `getpass`, echoes neither,
and **has no `--password` flag**. `--stdin` is the scripted escape hatch,
because a pipe is not a command line.

For anyone without the connection string, the **Create first administrator**
workflow runs the same command from the Actions tab on the deployer's
credentials, exactly the way `deploy.yml`'s migration step reaches the
database. The password is a **repository secret**
(`BOOTSTRAP_ADMIN_PASSWORD`), never a `workflow_dispatch` input: an input is
rendered in the Actions UI and stored on the run, readable by anyone with read
access to this repository, permanently and with no rotation prompt. GitHub
masks a secret in logs instead, and the job pipes it to `--stdin`.

It writes to the database directly rather than calling the API, like
`show_token` — whoever runs it already holds strictly more power than any
account it can create. It still goes through the product's own
`hash_password` and role rows, because a bootstrap that stored a credential
its own way would be a second place a password lives, with its own bugs.

A second account is **announced, not refused**. Somebody locked out of their
own tenant needs this most, and refusing would only send them to `psql`.

## Consequences

- The lockout is a five-minute fix with a runbook
  (`docs/runbooks/create-the-first-administrator.md`), and it is item 1 in
  `needs-a-human.md` because nothing else on that list can be done while
  nobody can sign in.
- **Do not add `--password` later.**
  `test_the_password_can_never_be_an_argument` asserts the parser rejects it.
  The convenience is real and the trade has already been priced once.
- The workflow is held to the code it calls. Its role menu offered a `viewer`
  role this product does not have; the run would have authenticated, fetched
  the database secret and failed on its last line. `tests/test_create_admin.py`
  now compares the menu against `permissions.BUILTIN_ROLES`, and asserts no
  input is interpolated into the shell script — `${{ inputs.x }}` inside a
  `run:` block is expanded by the runner before any shell quoting applies,
  which is a command-injection hole regardless of who may press the button.
- `pyyaml` joins the dev dependencies so those checks cannot skip silently,
  the same reason `openpyxl` and `fonttools` are declared.
- **`create_admin` is not a password reset**, and the gap that leaves is real
  enough to close in the same breath. `change_own_password` is the only route
  that writes a password and it requires the current one; on a tenant that has
  users the token authenticates nothing; no colleague can reset anybody; MFA
  recovery codes recover the *second* factor. So a forgotten admin password
  was a total lockout with no supported path back, and the best `create_admin`
  could offer was "make a second account under a different address and abandon
  the first" — which is not a recovery. Hence
  `python -m bankassist.reset_password <slug> --email …`, same discipline,
  which additionally **revokes every existing session** (as
  `change_own_password` does — a reset that left them alive keeps whoever knew
  the old password signed in) and **deliberately does not touch the second
  factor**: clearing MFA from a command line would make ADR-0027's second
  factor something one command removes. It reports whether one is enrolled
  instead, so nobody reads "password reset" as "back in" and then meets a code
  prompt they cannot answer.

## What was considered and rejected

- **A `--password` flag, "just for scripts."** `--stdin` covers the scripted
  case without the leak.
- **The workflow generating a random password and printing it.** The log is
  the one place the password must not be.
- **A one-time signed setup link, mailed or printed.** The right long-term
  shape, and a new token type with its own expiry, revocation and single-use
  accounting to get wrong — a guardrail surface for a problem a repository
  secret already closes.
- **Seeding a default administrator.** A known password on every deployment
  is the failure this whole design exists to avoid.
