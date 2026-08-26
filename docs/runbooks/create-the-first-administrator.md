# Creating a tenant's first administrator

A tenant that has just been seeded holds documents and roles and **no user
accounts**. That is correct — a seeded default account with a known password
would be far worse — but it means email-and-password sign-in cannot work until
somebody creates the first person, and ADR-0031 deliberately narrowed the admin
token to that one job and nothing else.

Read this before concluding a bank is "locked out". On 2026-08-26 every sign-in
on all four tenants failed with *"that email and password did not match"*,
which is true and tells nobody anything, and the diagnosis took a session.

## The fast path

Two routes. Pick by whether you hold the production connection string.

### You have the database URL

```bash
export BANKASSIST_DATABASE_URL='postgresql://…'
python -m bankassist.create_admin dashen --email you@bank.et
```

It prompts for the password twice and echoes neither. **There is no
`--password` flag** and there must never be one: it would put the credential
in `argv`, the shell's history file, the process list on a shared box, and any
CI log that echoes the command. This project rotated all four admin tokens on
2026-08-10 after exactly that happened to one of them.
`tests/test_create_admin.py::test_the_password_can_never_be_an_argument` is
the guard. `--stdin` is the scripted alternative — a pipe is not a command
line.

### You do not

Run the **Create first administrator** workflow from the Actions tab. It
reaches the database on the deployer's credentials, exactly the way
`deploy.yml`'s migration step does.

1. Add a repository secret `BOOTSTRAP_ADMIN_PASSWORD` (Settings → Secrets and
   variables → Actions). At least 12 characters — `passwords.MIN_LENGTH`.
   **A secret, not a workflow input:** an input is rendered in the Actions UI
   and stored on the run, readable by anyone with read access to this repo,
   for good. A secret is masked in logs.
2. Run the workflow with the slug, the email, and a role.
3. Sign in, change the password from the **Account** page, and **delete the
   secret**.

## Afterwards

The bank's admin token stops being able to do anything at all the moment the
first account exists — a correct token then gets a `403` naming its
replacement (ADR-0031). That is the intended end state, not a regression.

Everyone after the first person is created from **Team** inside the panel,
which is why the first one should almost always be an `admin`: only an admin
can add colleagues. The command will make an `operator` or a `teller` if you
ask it to, and then that tenant still has nobody who can grow the team.

## Forgot the password on an account that already exists

Different command — `create_admin` creates, it does not repair:

```bash
export BANKASSIST_DATABASE_URL='postgresql://…'
python -m bankassist.reset_password dashen --email you@bank.et
```

Prompts twice, same as the other one, and has no `--password` flag for the
same reason. Two things it does that are worth knowing before you run it:

- **Every existing session is revoked.** Whoever was signed in as that account
  is signed out, including you on another machine. That is the point: a reset
  that left old sessions alive keeps whoever knew the old password in.
- **It does not remove two-factor.** If the account has MFA enrolled, the new
  password alone will not sign you in — you need the authenticator or a
  recovery code, and the command tells you how many unused codes are left.
  Clearing a second factor from a command line is a decision somebody should
  take on purpose, so it is not a flag here.

## Which is it? — a sign-in failing tells you almost nothing

"That email and password did not match" is what you get for a tenant with no
accounts, for a wrong password, and for a mistyped address alike, and the
token tab's "not accepted for this bank" covers both a wrong token and a
retired one. Distinguish them from the outside:

```bash
curl -si -H "X-Admin-Token: <token>" \
  "https://<host>/admin/api/<slug>/analytics?days=1" | head -1
```

- **200** → the tenant has **no users**; you are already in, and `create_admin`
  is the command you want.
- **403** → the tenant **has users** (ADR-0031 retired the token); somebody's
  password is the problem, so `reset_password`.
- **401** → wrong or stale token; this tells you nothing either way.

The commands themselves also report it: `create_admin` prints `Note: … already
has N account(s)` and `reset_password` prints the tenant's account count when
the address does not match.

## What this is not

- **Not reachable from an agent sandbox.** Same boundary as
  `scripts/faq_export.py`: the production database and the Cloud Run host are
  both outside it. The workflow exists partly for that reason.
