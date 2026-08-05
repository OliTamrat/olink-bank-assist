# Dashen Bank Prospect-Demo Content — Sources

`bankassist/seed_dashen.py` builds a sales-demo tenant from **Dashen Bank's
own publicly available information**, researched 2026-08-05. This is not
affiliated with or endorsed by Dashen Bank — see the `disclaimer` banner
shown in the widget for that tenant.

`dashenbanksc.com` itself was unreachable for direct fetching throughout
research (session-wide fetch failure that also affected unrelated domains,
not specific to Dashen), so content is drawn entirely from search-engine
synthesis of the bank's own pages and independent secondary sources. Where
sources disagreed or a figure could only be confirmed once, the content
stays qualitative rather than stating an unverified number — same doctrine
as the CBE and Awash tenants.

| Fact | Value used | Confidence |
|---|---|---|
| Founded 1995, opened Jan 1, 1996 with 11 branches, 11 founding shareholders, named after Ras Dashen | — | Well-corroborated across dashenbanksc.com's own company-profile PDFs, about-us page, and Wikipedia synthesis |
| Bank of the Year – Ethiopia (The Banker/FT), 15th time in 2025, also 2024 | — | Well-corroborated: Dashen's own press release + LinkedIn citing The Banker + birrmetrics.com |
| Amole digital wallet exists, P2P/bill-pay/airtime/cash-in-out/QR/mPOS/DSTV features | — | Well-corroborated across press releases and product pages |
| "Super App" branding | — | Well-corroborated across multiple independent articles |
| Dashen Mobile Plus: branch/agent OR self-register via app/internet banking/USSD, one shared login | — | Well-corroborated, repeated consistently across 3 search passes |
| Thunes cross-border transfer partnership | — | Single dated press release (prnewswire.com), specific and credible |
| Youth Saving Account: 25 birr initial, no min/max, zero-balance parent-opened | — | Single-source but detailed/specific |
| Mudarabah Saving Account (IFB) minimum | 500 birr | Single-source |
| Diaspora Qard Current Account minimum | USD 100 | Single-source |
| Diaspora Non-Repatriable Saving Account initial deposit | USD 100 | Single-source (rate claim of 14% explicitly NOT used — single-source, unverified) |
| Diaspora Fixed Time Deposit minimum | USD 5,000 | Single-source |
| Consumer loan sub-types (house, car, education, equipment) | — | Well-corroborated (product page + Studocu overview) |
| Business loan documentation (registration, TIN, tax clearance, 3yr financials, audited if ≥5M birr) | — | Single-source but specific and internally consistent |
| DubeAle-IFB: 3/6/12 month terms, no interest, max 700,000 birr | — | Well-corroborated (Dashen press release + Capital Ethiopia + Shega.co all consistent) |
| Dashen Amex Gold: 30,000 birr daily ATM limit, 100 birr annual fee, 15 birr joining fee | — | Sourced from American Express's own partner card pages |
| Dashen Amex Green: 20,000 birr daily ATM limit, 25 birr annual fee, 10 birr joining fee | — | Same source |
| Dashen Mastercard multi-currency prepaid card exists | — | Single-source, name/description only |
| Dashen–telebirr partnership (telebirr Mela/Endekise/Sanduq) | — | Well-corroborated (Ethio telecom's own site + Ethiopian Business Review) |
| Dashen SWIFT/BIC code | DASHETAA / DASHETAAXXX | Well-corroborated — 8 independent aggregator sources agree (Transfez, Remitly, Topremit, TheSwiftCodes.com, OhMyFin, XE.com, Bank-Codes.com, Bank-Code.net) |
| Email | info@dashenbanksc.com | Repeated across 3 independent directory aggregators |
| Never asks for personal/account/security info via social media | — | Single-source (search synthesis of dashenbanksc.com/privacy-and-security/), specific and concrete enough to use |
| IBM hybrid-cloud partnership | — | Well-corroborated — IBM's own newsroom + Dashen's own press release |
| Sharik interest-free banking window name | — | Single-source, plausible naming, used generically without a specific product breakdown |

## Not verified — deliberately not used as stated figures

- **Regular savings account interest rate** — a 7.00% figure and a separate
  "up to 9%" claim both single-sourced via search synthesis, not
  independently reproduced. Content describes the mechanism (monthly
  compounding) without stating a rate.
- **Regular savings minimum opening deposit** — contested: one source says
  25 birr, another (a different product-review blog) says 50 birr.
  Described as "a modest minimum deposit" without a figure.
- **Fixed Time Deposit interest rate** — not found in any source at all.
- **Branch/ATM/POS network size** — contested: "500+ branches" (2022
  article) vs. "900+ branches, 1,100+ ATMs, 2,000+ POS" (2024–25
  aggregator), likely both correct for their respective dates but not
  usable as a single current figure. Described qualitatively as "a growing
  nationwide network."
- **Transfer fees and limits** — no concrete ETB figures found anywhere;
  described qualitatively (app shows the fee before you confirm).
- **Super App user count (1.5 million)** and **telebirr lending volume
  figures (ETB 14 billion, 2.3 million customers)** — single-sourced,
  not used.
- **"First bank in Ethiopia" superlatives** (agent banking, Super App) —
  promotional framing from single-source award coverage; omitted rather
  than repeated as fact.
- **Branch operating hours** — not found anywhere; omitted.

**Deliberately excluded (not researched at all, per instruction):** any
negative press, financial losses, fraud incidents, or regulatory issues —
this demo is built to pitch *to* Dashen, and surfacing a prospect's own
negative coverage in their own product demo would be inappropriate.
