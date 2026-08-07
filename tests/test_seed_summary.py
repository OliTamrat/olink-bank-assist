"""The seed scripts run on every deploy, so anything they print lands in the
GitHub Actions log permanently. These lock in that a tenant's admin token
never does — the exact regression that put four live tokens into CI logs.
"""

from __future__ import annotations

from typing import Any

import pytest


def _summary(capsys: pytest.CaptureFixture[str], bank: Any) -> str:
    from bankassist.seed_common import print_seed_summary

    print_seed_summary(bank, True, "Demo bank", "demo")
    return capsys.readouterr().out


def test_admin_token_is_not_printed_under_ci(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], demo_bank: Any
) -> None:
    monkeypatch.setenv("CI", "true")
    out = _summary(capsys, demo_bank)
    assert demo_bank.admin_token not in out
    assert "[hidden in CI]" in out
    assert "show_token" in out  # the retrieval path must be discoverable


def test_admin_token_is_printed_locally(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], demo_bank: Any
) -> None:
    # Local development keeps the convenience — the exposure only matters
    # where the output is captured and retained.
    monkeypatch.delenv("CI", raising=False)
    out = _summary(capsys, demo_bank)
    assert demo_bank.admin_token in out


def test_rotate_invalidates_the_previous_token(demo_bank: Any) -> None:
    from bankassist.show_token import main

    before = demo_bank.admin_token
    assert main([demo_bank.slug, "--rotate"]) == 0

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from bankassist.db import get_engine
    from bankassist.models import Bank

    with sessionmaker(bind=get_engine())() as db:
        after = db.execute(select(Bank).where(Bank.slug == demo_bank.slug)).scalar_one()
        assert after.admin_token != before


def test_show_token_unknown_slug_exits_nonzero(demo_bank: Any) -> None:
    from bankassist.show_token import main

    assert main(["no-such-bank"]) == 1
