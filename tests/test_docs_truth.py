"""The docs are claims about the code, so the code gets to grade them.

This is ADR-0013 made executable, and it exists because drift here is not
hypothetical: the docs named the wrong tenant for the curated FAQs with
runnable commands that silently exported an empty sheet (PR #111), and
hard-coded test counts went stale within days of being written.

Each test names the prose it holds, so a failure reads as "update this
sentence", not as archaeology.
"""

from __future__ import annotations

import re
from pathlib import Path

from bankassist import channels

ROOT = Path(__file__).resolve().parent.parent
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

_NUMBER_WORDS = {
    2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
    8: "Eight", 9: "Nine", 10: "Ten",
}


def _latest_migration() -> str:
    """The real schema head: the highest-numbered migration file."""
    versions = ROOT / "migrations" / "versions"
    numbers = sorted(
        m.group(1)
        for p in versions.glob("[0-9]*.py")
        if (m := re.match(r"(\d{4})_", p.name))
    )
    assert numbers, "no migrations found — the glob is broken, not the schema"
    return numbers[-1]


def test_claude_md_states_the_real_schema_head() -> None:
    """CLAUDE.md 'Current state' says `schema at migration **NNNN**`."""
    stated = re.search(r"schema at migration\s+\*\*(\d{4})\*\*", CLAUDE)
    assert stated, "CLAUDE.md no longer states the schema head — restore it"
    assert stated.group(1) == _latest_migration(), (
        f"CLAUDE.md says schema {stated.group(1)} but the latest migration is "
        f"{_latest_migration()} — update the 'Current state' paragraph."
    )


def test_readme_states_the_real_schema_head() -> None:
    """README's directory map says `0001 baseline .. NNNN head`."""
    stated = re.search(r"0001 baseline \.\. (\d{4}) head", README)
    assert stated, "README no longer states the migration range — restore it"
    assert stated.group(1) == _latest_migration(), (
        f"README says head {stated.group(1)} but the latest migration is "
        f"{_latest_migration()} — update the directory map."
    )


def test_the_readme_channel_count_is_the_catalogue_length() -> None:
    """README's feature table opens its channel row with a number word.

    Adding an eighth channel to `channels.py` without touching the README is
    exactly the drift this file exists for.
    """
    n = len(channels.CATALOGUE)
    word = _NUMBER_WORDS.get(n, str(n))
    assert f"| **{word} channels** |" in README, (
        f"channels.CATALOGUE has {n} entries; the README feature table must "
        f"open that row with '**{word} channels**'."
    )


def test_every_channel_is_named_in_the_readme_channel_row() -> None:
    row = next(
        (line for line in README.splitlines() if "channels** |" in line), ""
    )
    assert row, "README channel row not found"
    for entry in channels.CATALOGUE:
        # The row uses display names ('Web widget'), the catalogue fuller
        # ones ('Website widget') — match on the distinctive word.
        marker = {
            "web": "widget", "telegram": "Telegram", "viber": "Viber",
            "whatsapp": "WhatsApp", "messenger": "Messenger",
            "instagram": "Instagram", "sms": "SMS",
        }.get(str(entry["key"]), str(entry["name"]))
        assert marker.lower() in row.lower(), (
            f"channel '{entry['key']}' is missing from the README channel row"
        )


def test_every_credentialed_channel_has_an_integrations_page() -> None:
    """docs/integrations/ must cover every channel a bank can connect.

    The Meta trio shares meta.md deliberately (ADR-0011); web needs no page
    because it needs no credential.
    """
    page_for = {
        "telegram": "telegram.md", "viber": "viber.md",
        "whatsapp": "meta.md", "messenger": "meta.md", "instagram": "meta.md",
        "sms": "sms.md",
    }
    for entry in channels.CATALOGUE:
        key = str(entry["key"])
        if key == "web":
            continue
        page = ROOT / "docs" / "integrations" / page_for[key]
        assert page.exists(), (
            f"channel '{key}' has no integrations page — docs/integrations/"
            f"{page_for[key]} is missing"
        )
        assert str(entry["name"]).split()[0].lower() in page.read_text(
            encoding="utf-8"
        ).lower(), f"{page.name} does not mention {entry['name']}"


def test_adrs_are_numbered_without_gaps_or_duplicates() -> None:
    """decisions/ is append-only and sequential — a gap means a decision was
    deleted instead of superseded, a duplicate means two sessions collided."""
    files = sorted((ROOT / "docs" / "decisions").glob("[0-9]*.md"))
    numbers = [int(p.name[:4]) for p in files]
    assert numbers, "no ADRs found"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"ADR numbering is broken: {numbers} — decisions are superseded, "
        "never deleted, and numbers are never reused."
    )


def test_every_adr_is_listed_in_the_decisions_index() -> None:
    index = (ROOT / "docs" / "decisions" / "README.md").read_text(
        encoding="utf-8"
    )
    for p in sorted((ROOT / "docs" / "decisions").glob("[0-9]*.md")):
        number = p.name[:4]
        assert f"| {number} |" in index, (
            f"ADR {number} exists but is not in decisions/README.md's table"
        )


def test_no_doc_hard_codes_an_exact_test_count() -> None:
    """Exact counts drifted twice in two weeks; the CI run is the count.

    Floors like '1,350+' are allowed — they age gracefully. Bare exact
    counts ('1,289 tests') are the bug.
    """
    for name, text in (("CLAUDE.md", CLAUDE), ("README.md", README)):
        exact = re.findall(r"\b(1,\d{3})(?!\+)\s+tests", text)
        assert not exact, (
            f"{name} hard-codes an exact test count {exact} — state a floor "
            "('1,350+') or nothing; the CI run is the count."
        )
