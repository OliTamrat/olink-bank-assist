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
| CBE Noor customer count | 8M+ | [2merkato.com](https://www.2merkato.com/news/banking-and-finance/7693-ethiopia-cbe-celebrates-10-years-of-interest-free-banking-with-cbe-noor), corroborated by [birrmetrics.com](https://birrmetrics.com/cbes-islamic-banking-arm-tops-8-million-customers/) |
| CBE Noor deposits | 266 billion birr | 2merkato.com, corroborated by birrmetrics.com |
| CBE Noor product count / structure (Wadi'ah, Mudarabah, Murabahah, Kafala) | — | 2merkato.com |
| CBE Noor governance (Sharia Advisory Committee, IFRS/AAOIFI) | — | 2merkato.com |
| Current account minimum | 500 birr | [apexhab.com](https://www.apexhab.com/2025/06/04/commercial-banks-and-their-services-with-document-requirements-in-ethiopia/) |
| 7 current-account types (4 ECX-related, 3 general) | — | apexhab.com |
| Current account required documents | ID, 2 photos, MoA, business license | apexhab.com |
| CBE SWIFT/BIC code | CBETETAA | corroborated by 4 independent financial-data sites: [bank.codes](https://bank.codes/swift-code/ethiopia/cbetetaa/), [Wise](https://wise.com/gb/swift-codes/CBETETAAFIN), [Transfez](https://www.transfez.com/en/swift-codes/cbetetaa), [theswiftcodes.com](https://www.theswiftcodes.com/ethiopia/cbetetaa/) |
| CBE Connect (diaspora remittance platform) | — | [birrmetrics.com](https://birrmetrics.com/cbe-connect-opens-the-floodgates-for-money-coming-home-outbound-flow-still-on-pause/) |
| CBE Birr agent eligibility (nationality, 1yr business, TIN, trade license) | — | [mfw4a.org](https://www.mfw4a.org/news/ethiopia-commercial-bank-ready-launch-agent-banking) |
| "Follow only official channels" fraud-safety guidance | — | [addisinsight.net](https://addisinsight.net/2025/02/28/commercial-bank-of-ethiopia-tightens-access-to-customer-accounts-amid-escalating-fraud-crisis/), corroborated by birrmetrics.com |

**Deliberately excluded:** CBE's fraud-loss figures and the 2024 ATM/system
glitch incident are real, widely reported news but are not included in the
knowledge base — a sales-demo assistant has no reason to surface a
prospect's own negative press, and it isn't customer-facing information a
bank chatbot would proactively volunteer. The general safety guidance CBE
itself has publicly issued (official-channels-only, never share your PIN)
is included, since that's genuinely useful, bank-endorsed customer content.

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
