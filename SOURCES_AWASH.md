# Awash Bank Prospect-Demo Content — Sources

`bankassist/seed_awash.py` builds a sales-demo tenant from **Awash Bank's
own publicly available information**, researched 2026-08-05. This is not
affiliated with or endorsed by Awash Bank — see the `disclaimer` banner
shown in the widget for that tenant.

`awashbank.com` returned HTTP 403 to direct fetching throughout research
(as did `en.wikipedia.org`), so content is drawn entirely from
search-engine synthesis of the bank's own pages and independent secondary
sources. Where sources disagreed or a figure could only be confirmed once,
the content stays qualitative rather than stating an unverified number —
same doctrine as the CBE and Dashen tenants.

| Fact | Value used | Confidence |
|---|---|---|
| Founded Nov 10, 1994 by 486 shareholders, began operations Feb 13, 1995, Ethiopia's first private commercial bank, Birr 24.2M paid-up capital | — | Well-corroborated across 3+ independent aggregator summaries converging on the same date/figures |
| Savings accounts pay monthly interest on minimum monthly balance, NBE sets the floor | — | Well-corroborated (2+ search passes, consistent wording) |
| Lucy Women's Special Savings Account exists, for women 18+ | — | Moderately corroborated (2 Awash-hosted URLs + a Facebook post) — note the two URLs may be the same page; rate NOT used (single-source pattern) |
| Smart Children Account, Student Account exist | — | Single-source, names/purpose only |
| Fixed Time Deposit minimum term | 6 months | Single-source |
| Fixed deposit: early withdrawal forfeits accrued interest | — | Single-source, same page as above |
| Diaspora eligibility: lived/worked abroad 1+ year | — | Single-source (search synthesis) |
| NR Transferable accounts (USD/EUR/GBP), Retention Accounts for exporters | — | Single-source, terminology not independently confirmed |
| Diaspora mortgage/auto loans | — | Moderately corroborated (2 Awash-hosted URLs) |
| AwashBIRR app name | — | Confirmed via official App Store listing |
| Mobile banking activation: branch/agent PIN + *901# | — | Single-source (newsaddis.com, third-party explainer) |
| Sheba Miles debit card (co-branded with Ethiopian Airlines) | — | Single-source synthesis, but ShebaMiles is a well-known, verifiable real program |
| Amanah Card (Ikhlas/interest-free ATM card) | — | Single-source |
| Mastercard prepaid card + payment gateway partnership, Feb 2024 | — | **High confidence** — official Mastercard newsroom press release |
| ATM 24/7 availability, standard features | — | Single-source synthesis |
| Term Loan repayment 13–60 months | — | Single-source |
| Awash-Lehulum micro-credit max | 20,000 birr | Moderately corroborated (Awash's own T&C page + Ethio telecom partner page reproducing the same terms) |
| Mortgage loan: 1yr+ deposit history, ≥30% down payment, min 100,000 birr | — | Single-source |
| Ikhlas interest-free window: Wadiah/Mudarabah/Murabaha/Ijarah products | — | Moderately corroborated (own website + own Facebook) |
| Agent banking network exists | — | Moderately corroborated (2 Awash-hosted URLs); "most accessible" superlative explicitly NOT used (single aggregator's characterization) |
| Awash SWIFT/BIC code | AWINETAA / AWINETAAXXX | Well-corroborated — 7+ independent sources agree (bank.codes, Wise, Transfez, theswiftcodes.com, XTransfer, Remitly, RemitFinder, ohmyfin.ai) |
| Toll-free number | 8980 | Well-corroborated — 2 independent source contexts (contact page aggregator + mobile-banking activation guide) |
| Branch hours | Mon–Sat, 8:00 AM–5:00 PM | Well-corroborated — 2 independent searches returned the same hours |
| Head office | Awash Tower, Ras Abebe Aregay St, Kirkos, Addis Ababa | Corroborated by 2 independent contexts (SWIFT registry address + contact aggregator) |
| Email | contactcenter@awashbank.com | Single-source aggregator, moderate confidence |
| Fraud safety tips (PIN shielding, stay logged in until done, vishing warning re: "Awash Secure Code", "May I Help You?" ATM scam) | — | Single-source (search synthesis of awashbank.com/it-security/, page confirmed to exist) |

## Not verified — deliberately not used as stated figures

- **Savings account interest rate (5.5%–7.5% range, or 7.5% for Lucy
  account)** — single-source claims; described qualitatively (monthly
  interest on minimum balance) without stating a rate.
- **Fixed deposit interest rate** — two possibly-different-product figures
  (6–12% vs. 5.5–7.5%) that may not even refer to the same account type;
  omitted entirely rather than guessed.
- **Branch count** — contested: 947 (dated, older aggregator) vs. 989
  (undated, more recent aggregator). Described as "approaching 1,000
  branches" rather than a precise figure.
- **Transfer fees/limits** — no Awash-specific figures found with
  confidence (the only concrete numbers surfaced during research were for
  a different bank and are explicitly not used here). Described
  qualitatively (published in Awash's own tariff schedule).
- **ATM/debit card fees** (issuance ~50–150 birr, interbank withdrawal
  ~7–15 birr) — low-confidence generic aggregator figures, not Awash-
  specific; omitted.
- **Customer count (15 million)** — single-source, unverified; not used.
- **Call-center hours (9 AM–11 PM daily)** — single-source and describes a
  *different* thing than branch hours; not included to avoid implying it's
  the same schedule as branch hours.

**Deliberately excluded (not researched at all, per instruction):** any
negative press, financial losses, fraud incidents, or regulatory issues —
this demo is built to pitch *to* Awash, and surfacing a prospect's own
negative coverage in their own product demo would be inappropriate.
