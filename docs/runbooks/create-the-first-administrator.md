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

## What this is not

- **Not a password reset.** It creates an account; it cannot change an
  existing one's credential. Somebody locked out of their own tenant can make
  themselves a second account with this — the command says so out loud rather
  than refusing, because whoever can run it already holds more power than any
  account it creates.
- **Not reachable from an agent sandbox.** Same boundary as
  `scripts/faq_export.py`: the production database and the Cloud Run host are
  both outside it. The workflow exists partly for that reason.
