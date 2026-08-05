# CBE Prospect-Demo Content — Sources

`bankassist/seed_cbe.py` builds a sales-demo tenant from **Commercial Bank of
Ethiopia's own publicly available information**, pulled 2026-08-05. This is
not affiliated with or endorsed by CBE — see the `disclaimer` banner shown in
the widget for that tenant.

`combanketh.et` itself returned HTTP 403 to automated fetches, so content is
drawn from secondary sources that quote or corroborate CBE's public
material. Where sources disagreed on a specific number (e.g. exact
telebirr-transfer fee tiers, exact branch hours), the knowledge base
deliberately stays qualitative rather than stating an unverified figure —
same "tool output is truth" doctrine the product itself enforces. **Before
any real pitch meeting, verify contested figures with a current CBE rate
sheet or branch visit.**

| Fact | Value used | Source |
|---|---|---|
| Ordinary savings rate | 7%/year | [ethiopia.deposits.org](https://ethiopia.deposits.org/accounts/commercial-bank-of-ethiopia-savings-account.html) |
| NBE interest-rate deregulation | Effective Jan 9, 2026 | [birrmetrics.com](https://birrmetrics.com/ethiopia-launches-interest-rate-framework-sets-repo-at-15/) |
| Diaspora account currencies (USD/GBP/EUR) | — | [combanketh.et/diaspora](https://combanketh.et/diaspora) (via search snippet) |
| Diaspora current account minimum | USD 100 | combanketh.et/diaspora (via search snippet) |
| Diaspora fixed deposit minimum, 3-month maturity | USD 5,000 | combanketh.et/diaspora (via search snippet) |
| Diaspora required documents | passport / origin ID / resident ID | combanketh.et/diaspora (via search snippet) |
| CBE Connect diaspora wallet | — | [addisfortune.news](https://addisfortune.news/news-alert/cbe-launches-digital-wallet-targeting-diaspora-finance-foreign-exchange-flows) |
| Mobile banking activation (branch auth, *889#) | — | [newsaddis.com](https://newsaddis.com/how-to-activate-cbe-ethiopia-mobile-banking-app/) |
| CBE Birr activation (branch, deposit form, *847#) | — | [typicalethiopian.com](https://typicalethiopian.com/how-to-use-cbe-birr-step-by-step-guide/) |
| epaymentsupport@cbe.com.et | — | newsaddis.com |
| cbediaspora@combanketh.et | — | search snippet, combanketh.et/diaspora |
| Loan eligibility (18+, resident, income, collateral) | — | [combanketh.et/loan-eligibility-criteria](https://combanketh.et/loan-eligibility-criteria/) (via search snippet) |
| ~1,900+ branches | — | [banksdaily.com](https://banksdaily.com/info/combank-ethiopia) |
| Head office: Ras Desta Damtew St, Kirkos, Addis Ababa | — | banksdaily.com |
| Interbank RTGS transfer fee, ATM fee tiers, exact telebirr fee amounts, precise branch hours | **not used as stated figures** — described qualitatively instead | multiple secondary sources disagreed; see note above |

## Not verified — flagged for the sales conversation

- Fixed time deposit rates by term (3/6/12/24 months): not found from a
  source specific enough to quote; the knowledge base describes the product
  qualitatively and directs to a branch/officer.
- Exact CBE-to-telebirr fee tiers and daily limit: two secondary sources gave
  different numbers; omitted rather than guessed.
- ATM withdrawal fee percentages and card replacement fee: single
  low-confidence secondary source; omitted rather than guessed.
- Exact branch hours: sources ranged 8:00–17:00 to 8:00–19:00; described as
  "varies by branch."

**The pitch point this supports:** when CBE's own team loads their real,
verified rate sheet through the admin panel, these gaps close immediately —
this is exactly the "tool output is truth" behavior in action, not a flaw to
paper over.
