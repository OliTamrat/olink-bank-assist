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

The bill arrived on 2026-08-26. Every seeded tenant holds documents and roles
and **no users** — which is itself correct, since a seeded default account
with a known password would be far worse — so every email-and-password sign-in
on all four banks failed with *"that email and password did not match"*. That
sentence is true and it names nothing: it looks identical to a forgotten
password, a mistyped address, a broken deploy and a dead database. The founder
reported it as an outage across every tenant, and diagnosing it took a session
that ended with no supported command to fix it.

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
- **This is not a password reset.** It creates accounts; it cannot change an
  existing credential. That remains the Account page.

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
