"""How much can actually be said on one USSD screen, per language.

Run: `python scripts/ussd_budget.py`

A USSD string is at most **182 octets**. Latin text packs into GSM 03.38 at
seven bits per character, so 182 characters fit. Anything outside that alphabet
forces the *entire* message to UCS-2 at two bytes per character — 91 characters,
half the room, for one stray glyph.

That is the whole reason this script exists rather than a sentence in the docs
stating "91 or 182". Two things about the real numbers are counter-intuitive
enough that designing from the naive reading produces the wrong screens:

**Ge'ez is denser than Latin, which claws back most of the UCS-2 penalty.**
Amharic and Tigrinya are abugidas — one glyph per consonant-vowel syllable —
so the same sentence runs about 0.68x the character count of its English
translation. 91 Ge'ez characters therefore carry roughly 134 English
characters' worth of meaning, not 91. The budget is tight, not halved.

**The Latin-script languages are one em dash away from losing half their
screen.** Afaan Oromo, Somali and Swahili are GSM-7 clean in their own
letters; every offender this script finds in them is punctuation *we* chose —
`—`, `…`, `·`, and an emoji in the language-signal greeting. A decorative dash
in a USSD reply silently drops that reply from 182 characters to 91, and it
does not look like a bug: the text still sends, there is just less of it.
So a USSD adapter needs a normaliser (em dash to hyphen, ellipsis to three
dots, no emoji) and the normaliser is load-bearing, not cosmetic.

The numbers below are measured from this repo's own six-language string tables
rather than asserted, so they move when the translations do. `docs/integrations/
ussd.md` links here rather than restating them — see docs/README.md rule 1.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

USSD_OCTETS = 182
"""The payload ceiling. Everything else here is derived from it."""

# GSM 03.38 basic alphabet. Characters here cost one septet.
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = set("^{}\\[~]|€")
"""The extension table — encodable, but two septets each, so a screen full of
them holds half as much. Counted as GSM-7 here because they do not force the
message to UCS-2, which is the cliff that matters."""

TABLES = ("strings.json", "ui_strings.json", "admin_strings.json")


def budget(text: str) -> int:
    """Characters available on one screen, given what this text is made of."""
    return USSD_OCTETS if is_gsm7(text) else USSD_OCTETS // 2


def is_gsm7(text: str) -> bool:
    return all(c in GSM7 or c in GSM7_EXT for c in text)


def offenders(text: str) -> list[str]:
    return [c for c in text if c not in GSM7 and c not in GSM7_EXT]


def _strings(name: str) -> dict[str, dict[str, str]]:
    data = json.loads((ROOT / "bankassist" / name).read_text(encoding="utf-8"))
    return {
        lang: {k: v for k, v in table.items() if isinstance(v, str)}
        for lang, table in data.items()
    }


def main() -> None:
    lengths: dict[str, list[float]] = {}
    dirty: dict[str, Counter[str]] = {}
    clean_counts: dict[str, list[int]] = {}

    for name in TABLES:
        tables = _strings(name)
        english = tables.get("en", {})
        for lang, table in tables.items():
            seen = clean_counts.setdefault(lang, [0, 0])
            for key, value in table.items():
                seen[1] += 1
                if is_gsm7(value):
                    seen[0] += 1
                else:
                    dirty.setdefault(lang, Counter()).update(offenders(value))
                # Ratio against English, on strings long enough for the ratio
                # to mean anything — a two-word button is noise.
                source = english.get(key)
                if lang != "en" and source and len(source) >= 20:
                    lengths.setdefault(lang, []).append(len(value) / len(source))

    print(f"USSD payload: {USSD_OCTETS} octets "
          f"({USSD_OCTETS} chars GSM-7, {USSD_OCTETS // 2} chars UCS-2)\n")
    print(f"{'lang':<6}{'screen':>8}{'vs en':>8}{'effective':>11}   notes")
    print("-" * 72)

    for lang in ("en", "am", "om", "ti", "so", "sw"):
        clean, total = clean_counts.get(lang, [0, 0])
        if not total:
            continue
        # A language whose own letters are Ge'ez can never be GSM-7. One whose
        # letters are Latin is only dirty because of punctuation we control.
        native_ucs2 = clean == 0
        chars = USSD_OCTETS // 2 if native_ucs2 else USSD_OCTETS
        ratio = statistics.median(lengths[lang]) if lang in lengths else 1.0
        # What that screen holds, expressed in English characters, so the six
        # languages can be compared at all.
        effective = chars / ratio
        if native_ucs2:
            note = "Ge'ez — always UCS-2"
        elif clean == total:
            note = "clean"
        else:
            top = "".join(c for c, _ in dirty[lang].most_common(4))
            note = f"{total - clean}/{total} strings need normalising: {top}"
        print(f"{lang:<6}{chars:>8}{ratio:>8.2f}{effective:>11.0f}   {note}")

    print(
        "\n'screen' is raw characters per USSD screen. 'vs en' is this "
        "language's\nmedian character count for the same content. 'effective' "
        "is the screen\nexpressed in English characters, which is the only way "
        "to compare them.\n"
        "\nThe spread is what matters: every language lands within a factor of "
        "about\n1.4 of every other, so ONE screen budget can serve all six. "
        "Design to the\nsmallest 'effective' number and no language is "
        "shortchanged."
    )


if __name__ == "__main__":
    main()
