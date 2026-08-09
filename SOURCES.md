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
| CBE founded in 1942 | — | title of CBE's own "CBE in Brief" PDF, surfaced via search snippet: [combanketh.et/cbeapi/uploads/CBE_Products_and_services_English...pdf](https://combanketh.et/cbeapi/uploads/CBE_Products_and_services_English_84e511c740.pdf) |

**"Why Choose CBE" document (2026-08-05):** introduces no new facts — it
reuses figures already sourced above (founding year, branch count, CBE Noor
scale, diaspora/CBE Connect, SWIFT code, agent banking) reframed positively
for comparison-intent questions ("is X better than CBE?"). It never names a
specific competitor or makes a claim about one — see CLAUDE.md for why
(comparative claims about a named real competitor carry their own
substantiation/legal risk, separate from the accuracy-about-CBE-itself
concern the rest of this file addresses).

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

## Added 2026-08-09 — gaps found from CBE's own chatbot

CBE runs a menu-driven assistant ("Selam") on combanketh.et. Its service menu
is CBE's **own published statement of what its customers ask about**, and four
of its branches had no counterpart in this knowledge base. That is a better
gap analysis than any guess about what to write next, so the four articles
below were written to close them.

| Fact | Source |
|---|---|
| Internet banking is a separate service needing branch registration | [newsaddis.com](https://newsaddis.com/how-to-activate-commercial-bank-of-ethiopia-internet-banking/) |
| Security pocket token + user ID issued at a branch | newsaddis.com |
| Portal is `https://cbeib.cbe.com.et/` | [cbeib.cbe.com.et](https://cbeib.cbe.com.et/) |
| Registration fields: user ID, token serial, memorable word, password | newsaddis.com |
| Token gives a one-time password for login and transfers; PIN changeable | newsaddis.com |
| Scope (balance, mini statement, history, transfers, bills), 24/7, personal + corporate | [combanketh.et internet banking](https://www.combanketh.et/PaymentServices/InternetBanking.aspx) |
| Import methods: LC, advance payment (TT), documentary collection (CAD), Franco Valuta | [combanketh.et/products/trade-services](https://combanketh.et/products/trade-services) |
| Guarantees: bid bond, performance, advance payment, loan, retention | combanketh.et/products/trade-services |
| Export: letters of credit, trade finance, consignment-basis payment | combanketh.et/products/trade-services |
| FX: separate cash vs transactional buy/sell rates, updated at least daily | [engocha.com](https://engocha.com/ethiopian-birr-foreign-exchange/cbe), [exchange.addisfortune.news](https://exchange.addisfortune.news/bank/commercial-bank-of-ethiopia) |
| USD is the benchmark; other rates derived from it | [kakupress.net](https://kakupress.net/commercial-bank-of-ethiopia-exchange-rate-today-latest-updates/) |
| Bills: electricity, water, telecom, DSTV, traffic fines, airtime, ET tickets | [allaboutethio.com](https://allaboutethio.com/how-to-use-cbe-birr-to-pay-utilities-water-electricity-tele-dstv-traffic.html), [capitalethiopia.com](https://capitalethiopia.com/2019/07/08/utilities-can-be-paid-at-commercial-bank-of-ethiopia/) |

### Deliberately NOT stated in these four

- **Any exchange rate figure.** The FX article says outright that it does not
  quote one. A rate written into a knowledge base is wrong the next day, and a
  stale rate is worse than no rate — the article's job is to say where the
  live number lives, not to be it.
- **Biller short codes** (water / electricity / DSTV / traffic fines). One
  secondary source, and the failure mode is a customer paying the wrong
  organisation. The article tells people to pick the biller from the in-app
  list instead.
- **Trade-service charges, requirements and processing times.** These vary by
  instrument and counterparty and are subject to NBE foreign-currency rules;
  the article directs to the trade services desk.

### Known retrieval miss, recorded rather than papered over

"bid bond guarantee for a tender" retrieves nothing, even though the
trade-services article names bid bonds explicitly. Lexical retrieval again:
the query's wording and the document's do not overlap enough to clear the
informativeness gate. Same class of problem as the account-opening miss, and
the same fix applies — this is not something more content can solve.
