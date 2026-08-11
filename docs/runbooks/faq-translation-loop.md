# The curated-answer translation loop

The 160 curated FAQ answers belong to the **`dashen`** tenant (not CBE — that
error cost a morning; PR #111 holds the correction with a test) and live in
the production database, not the repo. As of 2026-08-11 they are English-only:
the last thing a customer can reach in English after asking in Amharic.

A curated answer is served **verbatim, with no model call and no gate after
it** — so a translation of one is a second piece of bank-approved copy, and
the reviewer's sign-off matters more here than anywhere else in the product.

## The loop

1. **Export.** Either the **Download button on the Curated Answers page**
   (produces the sheet for the signed-in tenant, no connection string
   needed — PR #109), or `python scripts/faq_export.py dashen` wherever the
   production DB is reachable. Same TSV either way: one row per question and
   per answer, five language columns, BOM for Excel, newlines as a visible
   `⏎`, grouped by `source_faq_id` so a translation sits on the same row as
   its original.
2. **Translate.** Fill the four language columns. The sheet is the same shape
   as `review/strings.tsv`; the same reviewer reads both.
3. **Import.** `python scripts/faq_import.py dashen` — **dry-run by
   default**, prints every change. `--write` applies, as **drafts only**,
   whatever the status column says.
4. **Approve.** Publishing is a separate act in the admin panel. The importer
   cannot publish; that separation is deliberate.

An unedited round trip reports `0 to create, 0 to update` — worth checking,
since "imports everything every time" is the easy bug in any importer.

`tests/test_faq_sheet_import.py` asserts the export and import halves name
the same tenant in their usage examples — the drift that caused the
CBE/Dashen error cannot recur silently.
