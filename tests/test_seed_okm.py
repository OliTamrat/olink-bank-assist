"""Ask OKM's markdown ingestion — title/category parsing and re-run safety.

Two things a portal-sync source makes easy to get wrong, both caught here:
a re-run must UPDATE existing pages by title rather than duplicating them
(the "seed_okm re-run REPLACES" contract in the module docstring), and the
title parser must handle both plain files (first `# H1`) and the handful of
landing pages sync_docs.py stamps with fenced front matter — getting either
wrong silently mistitles a page rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from bankassist.models import Bank, Document
from bankassist.seed_okm import OKM_SLUG, parse_markdown, seed_okm


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestParseMarkdown:
    def test_title_from_h1(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bank-assist/overview.md", "# What Bank Assist is\n\nBody text.")
        title, category, content = parse_markdown(path, tmp_path)
        assert title == "What Bank Assist is"
        # The H1 stays part of the body — only fenced front matter is
        # stripped, so a plain file's content is untouched, byte for byte.
        assert content == "# What Bank Assist is\n\nBody text."

    def test_title_from_front_matter_wins_over_any_h1(self, tmp_path: Path) -> None:
        # This is the exact shape sync_docs.py's _stamp_title writes.
        path = _write(
            tmp_path, "onekof/README.md",
            '---\ntitle: "Onekof"\n---\n\n# The knowledge base — OKM index\n\nBody.',
        )
        title, _category, content = parse_markdown(path, tmp_path)
        assert title == "Onekof"
        # The front matter is stripped; the H1 stays part of the body.
        assert content.startswith("# The knowledge base")

    def test_no_h1_falls_back_to_filename(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "dispatch/gotchas.md", "Just prose, no heading.")
        title, _category, _content = parse_markdown(path, tmp_path)
        assert title == "Gotchas"

    def test_category_from_top_two_path_segments(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bank-assist/decisions/0001-never-move-money.md", "# ADR\n\nBody.")
        _title, category, _content = parse_markdown(path, tmp_path)
        assert category == "bank-assist/decisions"

    def test_root_level_file_categorised_by_product_alone(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "gada-5k/overview.md", "# Overview\n\nBody.")
        _title, category, _content = parse_markdown(path, tmp_path)
        assert category == "gada-5k"


class TestSeedOkm:
    def test_first_run_creates_the_tenant_and_every_document(
        self, tmp_path: Path, db_session: Any
    ) -> None:
        _write(tmp_path, "dispatch/overview.md", "# Dispatch\n\nWhat it is.")
        _write(tmp_path, "dispatch/decisions/0001-x.md", "# ADR 1\n\nWhy.")

        result = seed_okm(tmp_path)

        assert result == {"created": 2, "updated": 0, "seen": 2}
        bank = db_session.execute(select(Bank).where(Bank.slug == OKM_SLUG)).scalar_one()
        assert bank.allow_general_knowledge is False
        docs = db_session.execute(
            select(Document).where(Document.bank_id == bank.id)
        ).scalars().all()
        assert {d.title for d in docs} == {"Dispatch", "ADR 1"}
        # reindex_document ran — retrieval has nothing to chunk otherwise.
        assert all(d.chunks for d in docs)

    def test_rerun_updates_by_title_instead_of_duplicating(
        self, tmp_path: Path, db_session: Any
    ) -> None:
        path = _write(tmp_path, "dispatch/overview.md", "# Dispatch\n\nOriginal text.")
        seed_okm(tmp_path)

        path.write_text("# Dispatch\n\nRevised text.", encoding="utf-8")
        result = seed_okm(tmp_path)

        assert result == {"created": 0, "updated": 1, "seen": 1}
        db_session.expire_all()
        bank = db_session.execute(select(Bank).where(Bank.slug == OKM_SLUG)).scalar_one()
        docs = db_session.execute(
            select(Document).where(Document.bank_id == bank.id)
        ).scalars().all()
        assert len(docs) == 1  # not two rows titled "Dispatch"
        assert docs[0].content == "# Dispatch\n\nRevised text."

    def test_a_page_removed_from_the_source_is_left_in_place(
        self, tmp_path: Path, db_session: Any
    ) -> None:
        """Documented in the module docstring: a stale page beats a silently
        missing one for an internal Q&A tool, and deleting would also force
        every untouched document through a needless reindex on every run."""
        _write(tmp_path, "gada-5k/overview.md", "# Gada\n\nText.")
        seed_okm(tmp_path)

        empty = tmp_path / "empty"
        empty.mkdir()
        seed_okm(empty)

        db_session.expire_all()
        bank = db_session.execute(select(Bank).where(Bank.slug == OKM_SLUG)).scalar_one()
        docs = db_session.execute(
            select(Document).where(Document.bank_id == bank.id)
        ).scalars().all()
        assert len(docs) == 1
        assert docs[0].title == "Gada"

    def test_a_whitespace_only_file_is_skipped_rather_than_stored_blank(
        self, tmp_path: Path, db_session: Any
    ) -> None:
        _write(tmp_path, "oli-mentor/blank.md", "   \n\n  \n")
        result = seed_okm(tmp_path)
        assert result == {"created": 0, "updated": 0, "seen": 1}

    def test_missing_source_directory_raises_cleanly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            seed_okm(tmp_path / "does-not-exist")
