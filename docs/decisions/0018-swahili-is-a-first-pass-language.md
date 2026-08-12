# ADR-0018 — Swahili ships as a sixth language, first-pass like Somali

**Status:** accepted · **Date:** 2026-08-12

## Context

ADR-0016 recorded the language-expansion order — Swahili first, on reach per
unit of effort — and named the reason Swahili costs less than Amharic, Afaan
Oromo, Tigrinya or Somali did: it already has substantial representation in
mainstream AI/NLP tooling, so the *discovery* phase (finding the
disambiguation shape, the guardrail phrasings) draws on far more existing
reference material than the Ethiopian languages had when this product's
guardrails were first built from a standing start.

That claim needed testing before it could be trusted, and this session tested
it by actually shipping the language rather than estimating the cost from
outside.

## Decision

**Swahili (`sw`) is now a sixth supported language, following the exact
implementation pattern Somali already established** — a Latin-script
elimination rule for `detect_language()`, a positive-signal word set, BM25
stopwords, and native-informed (not guessed) phrasings across every guardrail
regex block: the account-noun list, the possessive/kinship marker, the
disclosure-intent verbs, the forgotten-PIN stem, the human-request
manager/person fence, and the complaint/theft vocabulary.

**Shipped as a first-pass draft, exactly like Somali was — not as reviewed.**
`review/phrasebook.tsv` carries 13 Swahili rows (7 must-catch, 6 must-NOT-catch,
split across `human_request`, `account_specific`, `complaint`, `question` and
`greeting`), and `tests/test_swahili_intents.py` pins both directions the same
way `tests/test_tigrinya_somali_intents.py` does for Somali. All three string
tables (`strings.json`, `ui_strings.json`, `admin_strings.json` — 338 keys)
carry a machine-translated `sw` column. The review workbook's fourth sheet now
lists Swahili as first-pass alongside Oromo, Tigrinya and Somali.

**`detect_language()` changed shape, not just content.** It was a binary
Oromo/Somali tie-break (`return "om" if om >= so else "so"`); adding a third
Latin-script local language forced a genuine three-way comparison
(`local_best = max(om, so, sw)`, then a priority order om → so → sw on ties).
The tie order is unchanged from before for om/so — Swahili can only win a
comparison it is genuinely ahead in, never a tie against either original
language.

**One real bug found and fixed by testing rather than reading the rule** — the
same discipline this repo has already learned costs less than it looks:
Swahili's "forgot" verb (`sahau`) takes its subject/tense marker as a prefix
(`nimesahau`, `amesahau`), unlike Oromo's suffixing, so it is matched
unanchored rather than with a leading `\b`. That meant the `-ki-` conditional
infix ("if I forget", `nikisahau`) also contained the bare stem, and without
Oromo's existing `_CONDITIONAL` carve-out extended to Swahili's own "if"
words (`kama`, `ikiwa`), "Kama nikisahau PIN yangu, nifanye nini?" — an
entirely ordinary hypothetical — was refused as a security violation. Caught
by writing the over-refusal case out and running it against the real
classifier, not by reading the regex, which is exactly how the equivalent
Oromo `yoo`/`yoon` gap was found originally.

## Consequences

- **Not reviewed by a native speaker.** Every guardrail phrasing here is my
  own drafting from standard Swahili grammar, the same status Somali carried
  (and still carries) before ADR-0018. The founder's stated intent is to
  handle native-speaker review resourcing directly, separate from this
  session — until that happens, this rule should be talked about the same
  way Tigrinya and Somali are: "first pass," not "done."
- **The "costs less" claim is partially confirmed, not fully.** The
  *discovery* phase did go faster — no supplied phrasings were needed to find
  the account-noun list, the possessive pattern, or the manager/person fence,
  unlike every one of the four Ethiopian languages. But discovery is not the
  whole cost: the conditional-infix bug above is exactly the class of defect
  Amharic/Oromo/Tigrinya/Somali needed multiple rounds of native phrasing to
  find, and it surfaced here on the very first adversarial pass rather than
  needing five rounds — which argues the *volume* of such bugs may be lower,
  not that the *category* of risk disappears. Native review still has to run
  before a real pilot, exactly as ADR-0016 already said.
- **Possessive-agreement risk is real and named, not hidden.** Swahili's
  possessive concords vary by noun class (`yake` for N-class nouns like
  `akaunti`, `lake` for `salio`, `wake` for class-1 kinship nouns); the
  implementation matches the possessive marker words broadly rather than
  enforcing class agreement, which is safe (the three-part conjunction still
  gates it) but may under-match a construction I did not anticipate. This is
  the kind of gap only a native speaker reliably closes.
- `SUPPORTED_LANGUAGES` gained `sw` **appended at the end**, not inserted
  alphabetically — `scripts/build_review_workbook.py` locates the Ge'ez-script
  columns (`ETHIOPIC_COLS`) by position, and this session also fixed two other
  hardcoded-position bugs in that file (a column-width list one entry short,
  and a `c <= 7` boundary that would have left the Swahili review column
  unstyled) that a mid-list insertion would have made worse, not better.
  Future languages should append the same way.

## References

- `bankassist/classifier.py` — `_SWAHILI_WORDS`, `detect_language()`,
  every guardrail block's Swahili addition, `_CONDITIONAL`.
- `bankassist/retrieval.py` — `_STOPWORDS_SW`.
- `bankassist/i18n.py` — `SUPPORTED_LANGUAGES`, `LANGUAGE_NAMES`.
- `tests/test_swahili_intents.py`, `review/phrasebook.tsv` (sw rows).
- ADR-0008 (the original five-language string-table decision), ADR-0016
  (positioning and language order, including the "costs less" claim tested
  here).
