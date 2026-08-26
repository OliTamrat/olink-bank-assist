"""The bootstrap door gets a handle.

ADR-0031 made the admin token open exactly one door — creating a tenant's
first administrator — and shipped no tooling to walk through it. The cost
arrived in full: every tenant seeded with documents, roles and no users, so
every sign-in on every bank failed with "that email and password did not
match", and no supported command existed to fix it.

The property that matters most here is negative and easy to lose in a later
"convenience" commit: **the password must never be an argument.** This
project's four admin tokens were rotated on 2026-08-10 after one appeared in a
build log; a `--password` flag would put the next credential in argv, shell
history, the process list, and CI output. `test_the_password_can_never_be_an_argument`
is the guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import create_admin, passwords, permissions
from bankassist.models import User, UserCredential

PW = "CorrectHorseBattery9!"

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "create-first-administrator.yml"
)


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str], typed: str = PW) -> int:
    """Drive it as the terminal does, with the password arriving from getpass."""
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _prompt: typed)
    return create_admin.main(argv)


def test_it_creates_an_account_that_can_actually_sign_in(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point, asserted through the real login route.

    A bootstrap that writes a row the login path will not accept is worse than
    no bootstrap: it looks like it worked.
    """
    assert _run(monkeypatch, ["demo", "--email", "Boss@Olink.ET"]) == 0

    r = client.post(
        "/admin/api/demo/login", json={"email": "boss@olink.et", "password": PW}
    )
    assert r.status_code == 200, r.text

    wrong = client.post(
        "/admin/api/demo/login",
        json={"email": "boss@olink.et", "password": "NotThePassword9!"},
    )
    assert wrong.status_code == 401


def test_the_address_is_normalised(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed with capitals at 2am, signed in with lowercase the next morning."""
    _run(monkeypatch, ["demo", "--email", "  Boss@Olink.ET  "])
    user = db_session.execute(select(User)).scalars().one()
    assert user.email == "boss@olink.et"


def test_the_password_is_hashed_by_the_product_not_by_this_script(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bootstrap that stored a credential its own way would be a second
    place a password lives, with its own bugs to find."""
    _run(monkeypatch, ["demo", "--email", "boss@olink.et"])
    row = db_session.execute(select(UserCredential)).scalars().one()
    assert PW not in row.secret_hash
    assert row.secret_hash.startswith("$argon2id$")
    assert passwords.verify_password(row.secret_hash, PW)


def test_a_short_password_is_refused(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, ["demo", "--email", "boss@olink.et"], typed="short") == 1
    assert db_session.execute(select(User)).scalars().all() == []


def test_a_mistyped_confirmation_writes_nothing(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed twice because there is no "forgot password" behind this account."""
    answers = iter([PW, "SomethingElse9!"])
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _p: next(answers))
    assert create_admin.main(["demo", "--email", "boss@olink.et"]) == 1
    assert db_session.execute(select(User)).scalars().all() == []


def test_an_unknown_bank_names_the_ones_that_exist(
    client: TestClient, demo_bank: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slug typo is the likeliest way to run this wrong, and "no such bank"
    alone leaves the operator guessing at spelling."""
    assert _run(monkeypatch, ["dashen", "--email", "boss@olink.et"]) == 1
    assert "demo" in capsys.readouterr().err


def test_one_address_one_account(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, ["demo", "--email", "boss@olink.et"]) == 0
    assert _run(monkeypatch, ["demo", "--email", "boss@olink.et"]) == 1
    assert len(db_session.execute(select(User)).scalars().all()) == 1


def test_a_second_account_is_allowed_but_announced(
    client: TestClient, demo_bank: Any, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not refused: somebody locked out of their own tenant needs this most,
    and holding the connection string already outranks any account it makes.
    Said out loud, because a surprise second administrator is worth a sentence.
    """
    _run(monkeypatch, ["demo", "--email", "first@olink.et"])
    capsys.readouterr()
    assert _run(monkeypatch, ["demo", "--email", "second@olink.et"]) == 0
    assert "already has 1 account" in capsys.readouterr().out


def test_an_unknown_role_is_refused(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        _run(monkeypatch, ["demo", "--email", "boss@olink.et", "--role", "wizard"]) == 1
    )
    assert db_session.execute(select(User)).scalars().all() == []


def test_the_password_can_never_be_an_argument() -> None:
    """The guard, and the reason this file exists as much as the feature does.

    A `--password` flag would put the next credential into argv — the shell's
    history, the process list on a shared box, and any CI log that echoes the
    command. This project has already rotated four tokens over exactly that.
    `--stdin` is the scripted escape hatch, and a pipe is not a command line.
    """
    parser_flags = create_admin.main.__doc__ or ""
    with pytest.raises(SystemExit):
        create_admin.main(["demo", "--email", "a@b.et", "--password", PW])
    assert "--password" not in parser_flags


# ------------------------------------------------- the same door from Actions
#
# The command needs a connection string. The workflow is for whoever does not
# hold one — and it is only as good as its agreement with the code it calls,
# which nothing but these tests checks.


def _workflow() -> Any:
    assert WORKFLOW.exists(), WORKFLOW
    # PyYAML resolves the bare `on:` key to the boolean True. That is YAML 1.1
    # behaving correctly and GitHub reading the same file differently; look it
    # up by what PyYAML produced rather than "fixing" the workflow.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_role_menu_offers_only_roles_that_exist() -> None:
    """A dropdown is a promise. `viewer` was in the first draft of this list
    and is not a role this product has — the run would have reached the
    database, fetched the secret, and failed on the last line."""
    inputs = _workflow()[True]["workflow_dispatch"]["inputs"]
    assert set(inputs["role"]["options"]) <= set(permissions.BUILTIN_ROLES)
    assert inputs["role"]["default"] in permissions.BUILTIN_ROLES


def test_the_password_is_a_secret_and_never_an_input() -> None:
    """The property the whole workflow turns on.

    A `workflow_dispatch` input is rendered in the Actions UI and stored on
    the run, so a password typed into one is readable by anyone with read
    access to this repository — permanently, and with no rotation prompt. A
    secret is masked in logs instead. Asserted on the parsed inputs rather
    than on the file's text so a renamed field cannot slip past.
    """
    inputs = _workflow()[True]["workflow_dispatch"]["inputs"]
    for name in inputs:
        assert "pass" not in name.lower(), f"{name} must be a secret, not an input"
    assert "secrets.BOOTSTRAP_ADMIN_PASSWORD" in WORKFLOW.read_text(encoding="utf-8")


def test_the_password_reaches_the_command_down_a_pipe() -> None:
    """Not as an argument, on the runner either. `--stdin` is the whole reason
    that flag exists; a `--password` here would be the same leak the command
    refuses, one layer up."""
    script = _workflow()["jobs"]["create"]["steps"][-2]["run"]
    assert "--stdin" in script
    assert "--password" not in script


def test_no_input_is_interpolated_into_the_shell() -> None:
    """`${{ inputs.x }}` inside a `run:` block is expanded by the runner
    before any shell quoting can apply to it — a command-injection hole
    regardless of who is allowed to press the button. Every value arrives
    through `env:` instead."""
    step = _workflow()["jobs"]["create"]["steps"][-2]
    assert "inputs." not in step["run"], "pass inputs through env:, not into the script"
    assert set(step["env"]) >= {"SLUG", "EMAIL", "ROLE", "DISPLAY_NAME"}
