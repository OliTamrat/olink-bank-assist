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


SELF_SERVE_CHANNELS = {"web", "telegram"}
"""The channels a bank can switch on with nobody's permission and no bill.

`web` needs no credential at all; Telegram's comes from @BotFather in about a
minute. Everything else needs an account somebody else has to approve.

**Viber was in this set and is not any more.** Rakuten Viber moved chatbots to
an application-and-commercial-terms model on 5 February 2024, which no test in
this repo could have noticed — a vendor rewriting its onboarding is invisible
from inside the code. It was found by a human logging in and seeing no button,
after four separate files had told him it would take minutes.
"""


STALE_SELF_SERVE_CLAIMS = (
    "Telegram and Viber are self-serve",
    "Telegram and Viber self-serve",
    "with Viber — one of the two channels",
    "like Telegram — it can be turned",
    "A bot account from partners.viber.com",
    "Viber are self-serve and take minutes",
)
"""The exact sentences that were true before 5 February 2024, and were not
after it. Each one shipped somewhere a bank could read it.

Phrases, not a prose heuristic. **The first version of this test tried to
reason about the sentences** — find a paragraph mentioning both "self-serve"
and a channel that is not, unless the paragraph also contained a retraction
word. It passed the regression it was written to catch: the replacement
paragraph both makes and withdraws the claim, so the retraction word excused
the whole thing. A check that cannot tell an assertion from its retraction is
worse than none, because it reads as coverage.
"""


def test_no_surface_repeats_a_retired_self_serve_claim() -> None:
    """The vendor's terms are not checkable here. Agreeing with ourselves is.

    Four files carried the same stale claim — `channels.py`, the README,
    `CLAUDE.md` and `docs/market-position.md` — so correcting one and missing
    the others was the likely outcome, and this is what makes that a failure
    rather than a slow leak back into the sales copy.
    """
    surfaces = {
        "channels.py": (ROOT / "bankassist" / "channels.py"),
        "README.md": (ROOT / "README.md"),
        "CLAUDE.md": (ROOT / "CLAUDE.md"),
        "docs/market-position.md": (ROOT / "docs" / "market-position.md"),
        "docs/integrations/viber.md": (
            ROOT / "docs" / "integrations" / "viber.md"
        ),
        "admin_strings.json": (ROOT / "bankassist" / "admin_strings.json"),
    }
    for label, path in surfaces.items():
        # Whitespace-normalised: every one of these files is hard-wrapped, so
        # the claim routinely straddles a line break.
        flat = " ".join(path.read_text(encoding="utf-8").split())
        for claim in STALE_SELF_SERVE_CLAIMS:
            assert claim not in flat, (
                f"{label} still says {claim!r}. Only "
                f"{sorted(SELF_SERVE_CHANNELS)} are self-serve — Viber has "
                f"needed an application and commercial terms since "
                f"5 February 2024."
            )


def test_the_viber_page_does_not_promise_a_token_in_minutes() -> None:
    """The specific sentence that sent somebody to a page with no button."""
    page = (ROOT / "docs" / "integrations" / "viber.md").read_text(encoding="utf-8")
    for stale in ("connect this in minutes", "no review", "Create a bot account at"):
        assert stale not in page, (
            f"docs/integrations/viber.md still says {stale!r} — bot accounts "
            f"have not been self-created since 5 February 2024."
        )


def test_a_proposed_integration_page_says_so_until_it_is_in_the_catalogue() -> None:
    """`docs/integrations/` otherwise means "shipped", and USSD is not.

    The directory's every other page documents working code, so a reader — or
    a future agent reading the tree as context — reasonably takes a page here
    as a description of something that exists. `ussd.md` is a design argument
    with no code behind it, and the honest signal is cheap: the page is marked
    proposed exactly while the channel is absent from `channels.CATALOGUE`,
    and the day the adapter lands the marking has to come off.

    The failure this prevents is quiet and expensive: a spec that ages into
    looking like a feature, which is the same shape as the Viber page claiming
    self-serve eighteen months after it stopped being true.
    """
    catalogued = {str(e["key"]) for e in channels.CATALOGUE}
    page = ROOT / "docs" / "integrations" / "ussd.md"
    if not page.exists():
        return  # deleted along with the proposal — fine
    text = page.read_text(encoding="utf-8")
    if "ussd" in catalogued:
        assert "proposed, not built" not in text.lower(), (
            "USSD is in channels.CATALOGUE now, so docs/integrations/ussd.md "
            "must stop describing itself as a proposal"
        )
    else:
        assert "proposed, not built" in text.lower(), (
            "docs/integrations/ussd.md describes a channel that is not in "
            "channels.CATALOGUE — say so at the top, or this page reads as a "
            "feature the product does not have"
        )
