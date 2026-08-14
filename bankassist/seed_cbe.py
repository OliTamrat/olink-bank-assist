"""Seed a CBE (Commercial Bank of Ethiopia) sales-demo tenant from CBE's own
publicly published information.

This is a PROSPECT DEMO, not a live CBE product: CBE has not commissioned or
endorsed this. The widget shows a persistent disclaimer banner
(`Bank.disclaimer`) saying so. Every figure below is sourced from public
material (CBE's own site/PDFs where reachable, otherwise corroborated
secondary reporting) — see SOURCES.md in the repo root for citations and
pull date. Where public sources disagreed or a figure could not be
corroborated, the content stays qualitative rather than guessing a number —
same "tool output is truth" doctrine as the product itself; a wrong figure
in a bank demo is worse than a vaguer but honest one.

Run:  python -m bankassist.seed_cbe
"""

from __future__ import annotations

from .agent import WHY_CHOOSE_CATEGORY
from .models import Bank
from .seed_common import print_seed_summary, prospect_disclaimer, seed_prospect_bank

CBE_SLUG = "cbe"
CBE_NAME = "Commercial Bank of Ethiopia"

_DOCS: list[dict[str, str]] = [
    {
        # Looked up directly by category for COMPARISON-intent questions
        # ("is X better than CBE?") — see agent.py's WHY_CHOOSE_CATEGORY.
        # Never names or makes claims about a specific competitor; states
        # only CBE's own sourced facts, positively.
        "title": "Why Choose CBE",
        "category": WHY_CHOOSE_CATEGORY,
        "language": "en",
        "content": (
            "Commercial Bank of Ethiopia is Ethiopia's oldest and largest "
            "bank, founded in 1942, with a nationwide network of over 1,900 "
            "branches — the widest branch reach of any bank in the "
            "country.\n\n"
            "CBE offers one of the most complete digital banking ecosystems "
            "in Ethiopia: CBE Mobile Banking, the CBE Birr mobile wallet, "
            "and CBE Noor — CBE's interest-free banking service, the first "
            "of its kind in Ethiopia, now serving over 8 million customers "
            "with more than 266 billion birr in deposits, more than half "
            "of the entire domestic interest-free banking market.\n\n"
            "For customers abroad, CBE offers dedicated diaspora accounts "
            "in USD, GBP, and EUR, plus CBE Connect, a digital platform "
            "built specifically to make sending money home easier, and "
            "international transfers through CBE's own SWIFT network "
            "(SWIFT/BIC: CBETETAA).\n\n"
            "CBE also extends its reach through CBE Birr agents — "
            "authorized local businesses bringing basic banking services "
            "to areas without a full branch — and supports businesses "
            "directly, from ordinary current accounts to accounts linked "
            "to the Ethiopian Commodity Exchange.\n\n"
            "Whatever matters most — branch access, digital convenience, "
            "interest-free banking, or reaching family abroad — CBE was "
            "built to offer it at national scale."
        ),
    },
    {
        "title": "Ordinary Savings Account",
        "category": "products",
        "language": "en",
        "content": (
            "CBE's Ordinary Savings Account is open to any Ethiopian citizen "
            "aged 18 or over. The savings account interest rate published by "
            "CBE is 7% per year. The savings account interest rate is subject "
            "to change: the National Bank of Ethiopia deregulated interest "
            "rates across the banking sector effective January 2026, so CBE "
            "now sets its savings account interest rate commercially — "
            "always confirm the current savings account interest rate with a "
            "branch or the CBE app, since it can be revised.\n\n"
            "To open a savings account you need a valid ID (Kebele ID, "
            "national ID, passport, or driving licence), a passport-size "
            "photo, and the minimum opening deposit. A savings account can "
            "be opened at any of CBE's branches — CBE operates one of the "
            "largest branch networks in Ethiopia, with over 1,900 branches "
            "nationwide."
        ),
    },
    {
        "title": "Fixed Time Deposit Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "A fixed time deposit locks your money with CBE for an agreed "
            "term in exchange for a higher rate of return than an everyday "
            "account. CBE offers fixed deposit terms across a range of "
            "durations; the exact return for each term is set commercially "
            "following the National Bank of Ethiopia's 2026 deregulation and "
            "is best confirmed with a branch or relationship officer, since "
            "it is reviewed periodically.\n\n"
            "As a general rule with fixed deposits: the return is paid at "
            "maturity, and withdrawing early typically pays less than the "
            "full agreed term would have. A fixed deposit suits money you "
            "will not need for a while; an everyday account suits money you "
            "may need at any time."
        ),
    },
    {
        "title": "Diaspora Accounts (Foreign Currency)",
        "category": "products",
        "language": "en",
        "content": (
            "CBE's Diaspora Account lets Ethiopians and foreign nationals of "
            "Ethiopian origin living abroad hold foreign-currency accounts in "
            "US Dollar, Pound Sterling, or Euro (other convertible currencies "
            "are accepted and converted at the prevailing rate).\n\n"
            "A diaspora current account can be opened with an initial deposit "
            "of USD 100 or its equivalent. A diaspora fixed deposit account "
            "requires an initial deposit of USD 5,000 or its equivalent, is "
            "interest-bearing, and has a minimum maturity period of three "
            "months.\n\n"
            "Required documents: a valid passport, and/or an Ethiopian-origin "
            "identification document, and/or a resident identification "
            "document from the country where you live. CBE also offers 'CBE "
            "Connect', a multicurrency digital wallet aimed at the diaspora, "
            "and diaspora account holders can convert their foreign currency "
            "to Birr at market rates and transfer instantly. For diaspora "
            "banking questions, CBE's diaspora desk can be reached at "
            "cbediaspora@combanketh.et."
        ),
    },
    {
        "title": "How to Activate CBE Mobile Banking",
        "category": "how-to",
        "language": "en",
        "content": (
            "CBE Mobile Banking must first be authorized at a CBE branch: "
            "visit any branch to register and receive an authorization code "
            "and PIN. After that, you can download the CBE Mobile Banking app "
            "(available on Android and iOS) and log in with your credentials.\n\n"
            "If you cannot use the app, standard mobile banking services are "
            "also available by dialing *889# from your registered phone "
            "number.\n\n"
            "With mobile banking you can check balances, view recent "
            "transactions, and transfer funds. For help, CBE's e-payments "
            "support can be reached at epaymentsupport@cbe.com.et."
        ),
    },
    {
        "title": "CBE Birr (Mobile Wallet)",
        "category": "how-to",
        "language": "en",
        "content": (
            "CBE Birr is CBE's mobile wallet service, separate from standard "
            "mobile banking. To open a CBE Birr account: visit a nearby CBE "
            "branch with your phone number and your CBE bank passbook or a "
            "valid ID, fill out a CBE Birr deposit form, and deposit an "
            "opening amount. You will receive a PIN to access your wallet.\n\n"
            "You can then download the CBE Birr mobile app (recommended over "
            "the USSD code for speed and ease of use) or dial *847# for "
            "wallet services via USSD."
        ),
    },
    {
        "title": "Transfers to Telebirr and Other Wallets",
        "category": "how-to",
        "language": "en",
        "content": (
            "You can transfer funds from your CBE account to telebirr and "
            "other mobile money wallets through CBE Mobile Banking or CBE "
            "Birr. Transfer fees apply and are tiered by amount; CBE and Ethio "
            "telecom have revised these fees more than once, so the exact "
            "birr amount is best confirmed in the app before you send — the "
            "app always shows the fee before you confirm a transfer.\n\n"
            "There is also a daily limit on how much you can send from CBE to "
            "telebirr in a single day; this limit is set by CBE and may "
            "change, so check the current limit in the app if you are sending "
            "a large amount."
        ),
    },
    {
        "title": "Transfers to Other Banks",
        "category": "how-to",
        "language": "en",
        "content": (
            "CBE supports transfers to other Ethiopian banks through the "
            "national real-time payment system. In the CBE Mobile Banking "
            "app, choose the transfer-to-other-banks option, select the "
            "receiving bank, and enter the account number and amount. "
            "A service fee applies to interbank transfers, in addition to any "
            "National Bank of Ethiopia charges — the app displays the exact "
            "fee before you confirm. Always check the receiving account "
            "holder's name shown on the confirmation screen before sending."
        ),
    },
    {
        "title": "ATM and Debit Cards",
        "category": "products",
        "language": "en",
        "content": (
            "CBE issues several ATM/debit card tiers, including domestic and "
            "international options (such as Classic, Gold, and Platinum "
            "cards), each with its own withdrawal limits and features. Cards "
            "work at any CBE ATM and at other banks' ATMs on the shared "
            "network; using another bank's ATM typically costs a somewhat "
            "higher fee than using a CBE ATM. A replacement fee applies for a "
            "lost or damaged card.\n\n"
            "If your card is lost or stolen, contact CBE customer care "
            "immediately to have it blocked, then visit a branch to request a "
            "replacement. Never share your PIN with anyone, including anyone "
            "claiming to call from the bank."
        ),
    },
    {
        "title": "Personal and Consumer Loans",
        "category": "products",
        "language": "en",
        "content": (
            "CBE offers consumer loans (for household or durable goods) and "
            "personal loans (for expenses such as weddings, education, or "
            "medical costs), alongside business and mortgage lending.\n\n"
            "General eligibility: you must be at least 18 years old, resident "
            "in Ethiopia (or hold a valid residence permit), have a stable "
            "income or viable business able to service the loan, and a "
            "satisfactory credit history. Collateral may be required "
            "depending on the loan type and amount.\n\n"
            "To apply, visit a branch with your ID and supporting income "
            "documents; a loan officer will guide you through the specific "
            "requirements and current terms for the loan type you need."
        ),
    },
    {
        "title": "CBE Noor — Interest-Free (Sharia-Compliant) Banking",
        "category": "products",
        "language": "en",
        "content": (
            "CBE Noor is CBE's interest-free banking service, operated "
            "according to Sharia principles. CBE was the first Ethiopian "
            "bank to offer interest-free banking, and CBE Noor has grown to "
            "over 8 million customers, with deposits mobilized under the "
            "interest-free window exceeding 266 billion birr — more than "
            "half of the domestic market for interest-free banking in "
            "Ethiopia.\n\n"
            "CBE Noor offers more than 30 deposit and financing products "
            "structured under Sharia-compliant principles, including a "
            "Wadi'ah-based savings account, an Amana-based current/checking "
            "account, and Mudarabah savings and term deposit accounts. It "
            "also provides full trade finance services (including "
            "Murabahah-structured import financing and export financing) "
            "and Kafala (Sharia-compliant guarantee) services. CBE also "
            "offers an interest-free deposit saving service for customers "
            "saving toward Hajj and Umrah.\n\n"
            "All CBE Noor products are supervised by an independent Sharia "
            "Advisory Committee and comply with IFRS and AAOIFI standards. "
            "To open a CBE Noor account, visit any CBE branch — the same ID "
            "and photo requirements apply as for a conventional account; "
            "ask specifically for CBE Noor / interest-free banking."
        ),
    },
    {
        "title": "Business and Current Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "CBE's Current Account is designed for businesses and "
            "individuals who need frequent transactions and cheque "
            "facilities. It is a non-interest-bearing account, with a "
            "minimum opening balance of 500 birr.\n\n"
            "CBE offers seven types of current accounts in total: four are "
            "related to the Ethiopian Commodity Exchange (ECX) for "
            "commodity traders, and three address the needs of different "
            "customer segments, including the ordinary current account "
            "available to businesses and individuals generally.\n\n"
            "Required documents to open a current account: a renewed ID "
            "card, two passport-size photos, and — for a business — the "
            "company's Memorandum of Association and a valid business "
            "license. Visit a branch to open a current account; a bank "
            "officer will confirm which of the seven account types fits "
            "your business."
        ),
    },
    {
        "title": "International Transfers and Receiving Money from Abroad",
        "category": "how-to",
        "language": "en",
        "content": (
            "CBE's SWIFT/BIC code is CBETETAA — use this when someone "
            "abroad is sending you money by international bank transfer, "
            "along with your CBE account number and branch details.\n\n"
            "CBE also receives inbound remittances through partnerships "
            "with licensed money transfer operators, and through 'CBE "
            "Connect', CBE's digital platform for diaspora Ethiopians to "
            "send money home directly into a CBE account or mobile wallet. "
            "For diaspora and international transfer questions, CBE's "
            "diaspora desk can be reached at cbediaspora@combanketh.et."
        ),
    },
    {
        "title": "Agent Banking (CBE Birr Agents)",
        "category": "products",
        "language": "en",
        "content": (
            "CBE Birr agents are businesses — such as shops, supermarkets, "
            "or fuel stations — authorized by CBE, under National Bank of "
            "Ethiopia rules, to offer basic banking services like cash-in "
            "and cash-out on behalf of the bank. This extends CBE's reach "
            "into areas without a full branch.\n\n"
            "To become a CBE Birr agent, a business generally needs "
            "Ethiopian nationality of the owner, a valid and lawful "
            "business, at least one year of business experience, a renewed "
            "trade license and Tax Identification Number (TIN), and a "
            "valid ID. Interested businesses should inquire at a CBE "
            "branch or through CBE's official channels for the current "
            "application process."
        ),
    },
    {
        "title": "Fraud Prevention and Account Safety",
        "category": "general",
        "language": "en",
        "content": (
            "To protect yourself from fraud and scams, follow these basic "
            "safety rules: never share your PIN, password, or any SMS/app "
            "one-time code with anyone, including someone claiming to be "
            "calling from CBE — CBE staff will never ask for these, and "
            "sharing them is the most common way fraud happens. Do not "
            "click links in unsolicited messages claiming to be from the "
            "bank, and be alert to scams that impersonate CBE, such as "
            "fake 'gift' or 'giveaway' promotions asking you to share a "
            "post or click a link. Always check that you are using the "
            "official CBE app (Google Play Store or Apple App Store) or "
            "the official combanketh.et website, and follow only CBE's "
            "official social media pages for accurate information — this "
            "is CBE's own published advice for protecting yourself from "
            "fraud.\n\n"
            "If you suspect fraud on your account, or lose your card or "
            "phone, contact CBE customer care immediately to secure your "
            "account, then visit a branch as soon as possible."
        ),
    },
    {
        "title": "Branches, Hours, and Customer Care",
        "category": "general",
        "language": "en",
        "content": (
            "CBE operates one of Ethiopia's largest branch networks, with "
            "over 1,900 branches nationwide, plus digital channels available "
            "outside branch hours. Typical branch hours are Monday through "
            "Saturday; exact opening and closing times can vary by branch, so "
            "it's best to check your nearest branch's posted hours.\n\n"
            "To contact CBE customer care, phone support is available, and "
            "the bank also operates a dedicated call center for customer "
            "support. For mobile banking or CBE Birr contact details "
            "specifically, epaymentsupport@cbe.com.et is the dedicated "
            "e-payments support contact address. CBE's head office contact "
            "address is Ras Desta Damtew Street, Kirkos, Addis Ababa."
        ),
    },
    {
        "title": "ATM Took My Money But Gave No Cash",
        "category": "general",
        "language": "en",
        "content": (
            "If an ATM debited your account but did not dispense the cash, "
            "keep the slip if one printed and note the date, time, amount and "
            "which ATM it was.\n\n"
            "Most of these reverse on their own. Ethiopia's interbank "
            "transactions clear through EthSwitch, whose rules require a "
            "transaction that was authorised but not completed at the machine "
            "to be reversed — including failures from a power cut or a "
            "cash-dispensing fault. Where the daily reconciliation of that "
            "machine shows a difference, the bank owning the ATM refunds the "
            "bank that issued the card without waiting to be asked.\n\n"
            "If the money has not come back, report it to your own bank, not "
            "to the bank that owns the machine — your bank raises the claim "
            "for you even when the ATM belonged to someone else. Ask for a "
            "reference number and use it to chase.\n\n"
            "If it is still unresolved after ten business days, the National "
            "Bank of Ethiopia's financial consumer protection office will "
            "review a complaint that the provider has had that long to settle."
        ),
    },
    {
        "title": "How Do I Close My Account",
        "category": "general",
        "language": "en",
        "content": (
            "Closing an account is done at a branch, not from the app, because "
            "the bank has to confirm your identity face to face before it "
            "acts.\n\n"
            "Bring your original ID and the account's passbook or card. If "
            "there is money left in the account you can withdraw it or move "
            "it to another account at the same time. Any cheque book issued "
            "on the account has to be handed back, and any standing "
            "instruction or salary payment pointing at the account should be "
            "moved first so nothing is sent to a closed account.\n\n"
            "If the account is joint, every holder has to agree to the "
            "closure. If it is a business account, whoever asks must be an "
            "authorised signatory."
        ),
    },
    {
        "title": "My Account Is Dormant — How to Reactivate It",
        "category": "general",
        "language": "en",
        "content": (
            "An account with no customer-initiated activity for a long period "
            "is marked dormant. Interest already earned is not lost and the "
            "money remains yours — dormancy stops transactions, it does not "
            "take the balance.\n\n"
            "To reactivate it, go to a branch with your original ID. It is "
            "usually the branch where the account was opened that can do this "
            "fastest, though any branch can start it. Bring the passbook or "
            "card if you still have them. You may be asked to update the "
            "details held on file — a current phone number and address — "
            "because those are often what went out of date while the account "
            "sat unused.\n\n"
            "Reactivation cannot be done over the phone or in the app: the "
            "point of the dormancy rule is that the bank confirms face to "
            "face that the account holder is the one asking."
        ),
    },
    {
        "title": "Saving and Budgeting Basics",
        "category": "financial-education",
        "language": "en",
        "content": (
            "This is general financial education, not investment advice.\n\n"
            "A simple starting rule for budgeting is 50/30/20: roughly half "
            "of income for needs (rent, food, transport), 30% for wants, and "
            "20% saved. What matters most is saving something every month, "
            "even a small amount, and building the habit.\n\n"
            "Pay yourself first: move savings to a separate account as soon "
            "as you're paid, before spending. Build an emergency fund "
            "covering a few months of expenses in an account you can access "
            "quickly before considering longer-term or higher-risk "
            "products.\n\n"
            "Ethiopia's Ethiopian Securities Exchange (ESX) opened in 2025 as "
            "the country's stock market, giving savers a new way to invest "
            "in listed companies through licensed brokers regulated by the "
            "Ethiopian Capital Market Authority. As with any investment, "
            "higher potential returns come with higher risk, and it's wise "
            "to speak with a licensed advisor before making investment "
            "decisions with money you may need soon."
        ),
    },
    {
        "title": "የቁጠባ ሂሳብ (Ordinary Savings Account — Amharic)",
        "category": "products",
        "language": "am",
        "content": (
            "የCBE መደበኛ የቁጠባ ሂሳብ ዕድሜያቸው 18 እና ከዚያ በላይ ለሆኑ ማንኛውም የኢትዮጵያ "
            "ዜጎች ክፍት ነው። የታወጀው የወለድ መጠን በዓመት 7% ነው። የኢትዮጵያ ብሔራዊ ባንክ "
            "ከጃንዋሪ 2026 ጀምሮ በባንክ ዘርፍ ውስጥ ያለውን የወለድ መጠን ቁጥጥር ስላነሳ፣ ባንኮች "
            "የቁጠባና የተቀማጭ ወለድ መጠኖችን በገበያ መሠረት ይወስናሉ — ስለዚህ የአሁኑን መጠን "
            "ሁልጊዜ በቅርንጫፍ ወይም በCBE መተግበሪያ ያረጋግጡ።\n\n"
            "ሂሳብ ለመክፈት ህጋዊ መታወቂያ (የቀበሌ መታወቂያ፣ ብሔራዊ መታወቂያ፣ ፓስፖርት ወይም "
            "መንጃ ፈቃድ)፣ አንድ ጉርድ ፎቶ እና ዝቅተኛው መክፈቻ ገንዘብ ያስፈልጋል። ሂሳብ ከ1,900 "
            "በላይ በሆኑ የCBE ቅርንጫፎች ውስጥ በማንኛውም ቦታ መክፈት ይችላሉ።"
        ),
    },
    {
        "title": "የሞባይል ባንኪንግ ማስጀመሪያ (Mobile Banking Activation — Amharic)",
        "category": "how-to",
        "language": "am",
        "content": (
            "የCBE ሞባይል ባንኪንግ አገልግሎት ከመጠቀምዎ በፊት በቅርንጫፍ መረጋገጥ አለበት፡ "
            "ወደ ማንኛውም ቅርንጫፍ በመሄድ ይመዝገቡና የማረጋገጫ ኮድ እና ፒን ያግኙ። ከዚያ በኋላ "
            "የCBE ሞባይል ባንኪንግ መተግበሪያውን (ለAndroid እና iOS ይገኛል) አውርደው "
            "በመረጃዎ ይግቡ።\n\n"
            "መተግበሪያውን መጠቀም ካልቻሉ፣ *889# በመደወል መደበኛ የሞባይል ባንኪንግ "
            "አገልግሎቶችን ማግኘት ይችላሉ።\n\n"
            "በሞባይል ባንኪንግ ቀሪ ሂሳብዎን ማየት፣ የቅርብ ጊዜ ግብይቶችን መመልከት እና ገንዘብ "
            "ማስተላለፍ ይችላሉ።"
        ),
    },
    # The four below close gaps found by reading CBE's OWN live chatbot menu
    # (combanketh.et, August 2026). Its service list is CBE's published
    # statement of what its customers ask about, and four of its branches had
    # no counterpart here: internet banking, international trade, exchange
    # rates, and everyday bill payments.
    {
        "title": "Internet Banking",
        "category": "how-to",
        "language": "en",
        "content": (
            "CBE Internet Banking lets you bank from a web browser, 24 hours a "
            "day, and is offered to both personal and corporate customers.\n\n"
            "You must already hold a CBE account, and registration starts in "
            "person: visit any branch and apply for internet banking. The "
            "branch issues you a user ID and a security pocket token — a small "
            "physical device that generates a one-time password.\n\n"
            "To register the first time, open https://cbeib.cbe.com.et/ in a "
            "web browser and choose the option for a new customer. You will be "
            "asked for your user ID, the serial number printed on your token, "
            "a memorable word, and a password of your choosing.\n\n"
            "The token is used at every login and again to authorise a "
            "transfer: switch it on, enter its PIN, and it displays a one-time "
            "password. You can change the token's PIN yourself.\n\n"
            "Internet banking covers most of what a branch counter does: "
            "checking your balance, viewing a mini statement or full "
            "transaction history, transferring funds, and paying bills. It is "
            "separate from CBE Mobile Banking and from CBE Birr, and needs its "
            "own registration."
        ),
    },
    {
        "title": "International Trade Services (Import, Export and Guarantees)",
        "category": "products",
        "language": "en",
        "content": (
            "CBE provides trade services for businesses importing and "
            "exporting goods, handled through its trade services and "
            "international banking teams rather than at an ordinary counter.\n\n"
            "For imports, the available payment methods are the documentary "
            "letter of credit (LC), advance payment (TT), documentary "
            "collection (CAD), and Franco Valuta.\n\n"
            "For exports, CBE handles letters of credit and trade finance, and "
            "also supports documentary collection, advance payment and "
            "consignment-basis payment.\n\n"
            "CBE also issues guarantees used in tendering and contracting: bid "
            "bonds, performance bonds, advance payment guarantees, loan "
            "guarantees and retention guarantees.\n\n"
            "Requirements, charges and processing times depend on the "
            "instrument, the counterparty's bank and the goods involved, and "
            "trade transactions are also subject to National Bank of Ethiopia "
            "foreign-currency rules. Speak to the trade services desk at a "
            "branch for the requirements that apply to a specific shipment."
        ),
    },
    {
        "title": "Foreign Exchange Rates",
        "category": "general",
        "language": "en",
        "content": (
            "CBE publishes foreign exchange rates for major currencies "
            "including the US dollar, euro and pound sterling, and quotes "
            "separate buying and selling rates, with cash rates quoted "
            "separately from transactional rates.\n\n"
            "Rates are updated at least once every business day, so the rate "
            "that applies is the one published on the day of your "
            "transaction. Check the current rate on the CBE website, in the "
            "CBE Mobile Banking app, or at any branch.\n\n"
            "The US dollar is the benchmark currency in Ethiopia's foreign "
            "exchange market; rates for other currencies are generally derived "
            "from the dollar rate.\n\n"
            "This page deliberately does not quote a figure. An exchange rate "
            "written down is out of date the following day, and a stale rate "
            "is worse than no rate — always take the live figure from the app, "
            "the website or a branch."
        ),
    },
    {
        "title": "Paying Bills — Utilities, DSTV, Traffic Fines and Airtime",
        "category": "how-to",
        "language": "en",
        "content": (
            "You can pay everyday bills through CBE without queueing at a "
            "counter, using CBE Birr or CBE Mobile Banking.\n\n"
            "Payments CBE collects include electricity (Ethiopian Electric "
            "Utility), water, telecom bills, DSTV and other entertainment "
            "subscriptions, and traffic fines for Addis Ababa. You can also "
            "buy mobile airtime and pay for Ethiopian Airlines tickets.\n\n"
            "From a smartphone, use the CBE Mobile Banking app or the CBE Birr "
            "app. From any phone without internet, dial *889# for mobile "
            "banking or *847# for CBE Birr and follow the menu.\n\n"
            "Each biller has its own short code inside the payment menu. Pick "
            "the biller from the list in the app or USSD menu rather than "
            "typing a code from memory — the list is the authoritative one and "
            "paying to the wrong code sends money to the wrong organisation.\n\n"
            "You will need your customer or contract number for the utility "
            "you are paying: the meter number for electricity, the contract "
            "number for water, or the smartcard number for DSTV."
        ),
    },
]


def seed() -> tuple[Bank, bool]:
    """Create the CBE prospect-demo bank if missing. Returns (bank, created)."""
    return seed_prospect_bank(
        slug=CBE_SLUG,
        name=CBE_NAME,
        # Nobody says "Commercial Bank of Ethiopia". The registered name stays
        # on the printed report and in the model prompt; this is what goes in
        # front of a customer and on the panel.
        short_name="CBE",
        # CBE's own purple, read off combanketh.et — the maroon here before was
        # simply wrong. Read off a screenshot rather than from a brand book, so
        # treat it as a good default and not as authoritative: the Branding
        # panel in Settings lets CBE correct it without a deploy, which is why
        # a guess is acceptable here at all.
        primary_color="#722282",
        # Served from combanketh.et — CBE's own host, which is the only kind of
        # source this should point at. The panel had been hotlinking a
        # logo-aggregator site, where nobody at CBE controls the file and a
        # takedown would blank the mark in the chat header on the bank's own
        # website.
        #
        # Still a hotlink rather than a copy we serve, so it inherits whatever
        # uptime and hotlink policy that host has. Mirroring it behind our own
        # domain is the durable fix; this is the right source in the meantime.
        logo_url="https://combanketh.et/uploads/Logo_849ddbfbe1.jpg",
        disclaimer=prospect_disclaimer("CBE", CBE_NAME),
        docs=_DOCS,
    )


if __name__ == "__main__":
    bank, created = seed()
    print_seed_summary(bank, created, "CBE prospect-demo bank", "cbe")
