# Language review — how to do it in one round

Two sheets, because the assistant needs two different things from a native
speaker and only one of them is translation.

| Sheet | What it is | Who fills it in |
|---|---|---|
| `strings.tsv` | What the assistant **says** — 18 replies × 5 languages | Reviewer corrects the translation cells |
| `phrasebook.tsv` | What the assistant must **understand** — sentences and what should happen to them | Reviewer writes sentences a real customer would type |

**The second sheet is the one that matters more.** Every language defect found
in the live demos so far was a phrase the assistant failed to understand, not a
reply worded badly: a request for a manager answered as a knowledge gap, a
forgotten PIN in Afaan Oromo, a transfer to a spouse refused as if it were
social engineering. Reviewing only the output strings would have caught none of
them.

---

## Sheet 1 — `strings.tsv`

```bash
python scripts/i18n_export.py          # regenerate from what is deployed
# ... reviewer edits the language columns ...
python scripts/i18n_import.py          # dry run: shows every change
python scripts/i18n_import.py --write  # apply
```

Open it in Excel, Google Sheets or LibreOffice. Edit **only** the five language
columns. Leave `key` alone — the code looks strings up by it.

**Read the "what it is for" column before translating.** Several strings will be
wrong in a way that is invisible from the English alone:

- **`ack_named`** is a fragment, not a sentence. Another sentence is glued onto
  the end of it.
- **`related_topics`** must be a *statement*. It was a question once, and it
  competed with the request below it — customers answered the wrong one and the
  assistant collected nothing.
- **`ask_contact`** is always the last line of a message, so it has to work as a
  closing question.
- **`{bank}`, `{name}`, `{contact}`** are placeholders. Keep them exactly, move
  them where the grammar needs them. The importer refuses a row whose
  placeholders don't match the English, because a lost `{bank}` crashes the
  reply at runtime, in production, in a language nobody on the team reads.

The importer also refuses to add a key that doesn't exist or drop one that has
gone missing from the sheet.

---

## Sheet 2 — `phrasebook.tsv`

```bash
python scripts/check_phrasebook.py        # all languages
python scripts/check_phrasebook.py ti so  # just these
```

Four columns: `language`, `phrase`, `expect`, `why it matters`.

Replace every row that starts with **FILL IN**. Add as many more as you like —
more sentences is strictly better. `expect` is one of:

| `expect` | Meaning |
|---|---|
| `human_request` | wants to speak to a person, a manager, the management |
| `account_specific` | wants a VALUE from an account — a balance, a transaction, an account number, whether a payment arrived. Anyone's, including their own |
| `account_procedure` | wants to know HOW — block a lost card, reset a PIN, close an account — or a published fact like a limit or a fee. Must be **answered normally** |
| `complaint` | reporting theft, fraud, a failed transfer, bad service |
| `question` | an ordinary question that must be **answered normally** |
| `greeting` | just saying hello |

### Three things that have caught us out — please cover them

**1. Inflected forms, not just dictionary forms.** Amharic and Tigrinya inflect
the *final character* rather than adding to the end, so a word matched in its
citation form misses every real use of it. `አመራር` → `አመራሩ` was invisible; so
were `ማኔጀር` → `ማኔጀሩ` and `አስኪያጅ` → `አስኪያጁ`. Write the sentence the way a
customer would actually type it, inflections and all.

**2. Every verb for the same idea.** Afaan Oromo turned out to have three verbs
for "forgot" — `irraanfachuu`, `dagachuu`, `walaaluu` — where Amharic has one.
Only the first was covered, so two of three phrasings walked through the
guardrail. If your language has more than one ordinary way to say something,
give all of them.

**3. Sentences that must NOT trigger.** These matter as much as the ones that
should, and they are the failure nobody can see from inside the product: a
customer asking a legitimate question gets stonewalled and nothing logs it as
wrong. Two real examples:

- `የባንኩ ኃላፊነት ምንድን ነው?` — "what is the bank's responsibility?" contains `ኃላፊ`
  ("head"), and was read as a demand for a manager.
- `Maallaqa gara herrega isaa ergu nan danda'aa?` — "can I send money to his
  account?" was refused as an attempt to obtain someone else's details.

Mark those rows `question`.

---

## What happens then

Both sheets round-trip into code, and the phrasebook becomes a permanent test
(`tests/test_phrasebook.py`) the moment it lands — so a sentence you supply once
is checked on every commit forever, and cannot regress silently.

Rows still marked FILL IN are reported separately and never counted as passing.
A language with nothing supplied reads as **untested**, which is the honest
description of Tigrinya and Somali today.
