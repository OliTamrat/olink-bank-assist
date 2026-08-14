"""Seed a Dashen Bank sales-demo tenant from Dashen's own publicly
published information.

This is a PROSPECT DEMO, not a live Dashen product: Dashen has not
commissioned or endorsed this. The widget shows a persistent disclaimer
banner (`Bank.disclaimer`) saying so — see seed_common.py. Every figure
below is sourced from public material; see SOURCES_DASHEN.md in the repo
root for citations and confidence level per fact. dashenbanksc.com itself
was unreachable for direct fetching during research (session-wide fetch
block), so content is drawn from search-engine synthesis of the bank's own
pages plus independent secondary sources — several facts that would
normally be usable are instead left qualitative because they could only be
confirmed from a single source, or because two sources gave conflicting
numbers (e.g. the general savings account's exact interest rate and minimum
opening deposit, and Fixed Time Deposit rates, are not stated as figures
anywhere in this file for that reason). Same "tool output is truth"
doctrine as the product itself — a wrong figure in a bank demo is worse
than a vaguer but honest one.

Run:  python -m bankassist.seed_dashen
"""

from __future__ import annotations

from .agent import WHY_CHOOSE_CATEGORY
from .models import Bank
from .seed_common import print_seed_summary, prospect_disclaimer, seed_prospect_bank

DASHEN_SLUG = "dashen"
DASHEN_NAME = "Dashen Bank"

_DOCS: list[dict[str, str]] = [
    {
        "title": "Why Choose Dashen Bank",
        "category": WHY_CHOOSE_CATEGORY,
        "language": "en",
        "content": (
            "Dashen Bank was founded by 11 shareholders in 1995 and opened "
            "for business on January 1, 1996 with 11 branches — named "
            "after Ras Dashen, Ethiopia's highest peak. Three decades "
            "later, Dashen has been named Bank of the Year – Ethiopia by "
            "The Banker (part of the Financial Times) fifteen times, "
            "including in 2024 and 2025, recognized for its innovative "
            "Super App.\n\n"
            "Dashen was among the first banks in Ethiopia to build a "
            "true digital ecosystem: Amole, its digital wallet and "
            "payments platform, and Dashen Mobile Plus, which customers "
            "can register for entirely without a branch visit — through "
            "the mobile app, internet banking, or USSD — using one login "
            "across every channel. Dashen also partnered with IBM to "
            "modernize its core banking integration on hybrid cloud, "
            "supporting open connections to fintech and telecom "
            "partners.\n\n"
            "Dashen was an early mover in interest-free banking with its "
            "Sharik window, and in 2024 launched DubeAle, a Sharia-"
            "compliant buy-now-pay-later financing service built with "
            "EagleLion System Technology — interest-free financing over "
            "3, 6, or 12 months.\n\n"
            "Whatever matters most — a genuinely mobile-first banking "
            "experience, interest-free options, or a bank recognized "
            "internationally for its digital transformation — Dashen has "
            "built its reputation on being early to what's next in "
            "Ethiopian banking."
        ),
    },
    {
        "title": "Savings Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "Dashen Bank's regular savings account pays interest "
            "compounded monthly on your minimum monthly balance, at a "
            "rate that can be revised — ask a branch or check the Dashen "
            "Mobile Plus app for the current savings interest rate. "
            "Opening a savings account requires a modest minimum deposit; "
            "the exact amount is best confirmed at a branch since figures "
            "found publicly for this vary. To open a savings account you "
            "generally need a valid, renewed national ID or passport, two "
            "recent passport-size photos, and to be 18 or over.\n\n"
            "Dashen also offers a Youth Saving Account with a very low "
            "entry point (an initial deposit as low as 25 birr), no "
            "minimum or maximum balance, and no withdrawal limit — it can "
            "even be opened with a zero balance by a parent or guardian "
            "for a child, with free standing-instruction transfers into "
            "it. For interest-free banking, Dashen's Mudarabah Saving "
            "Account is available under its Sharia-compliant Sharik "
            "window with a 500 birr minimum opening deposit.\n\n"
            "Savings accounts can be opened at any "
            "Dashen Bank branch."
        ),
    },
    {
        "title": "Fixed Time Deposit Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "A Dashen Fixed Time Deposit works like a certificate of "
            "deposit: you lock your money for an agreed term in exchange "
            "for a higher interest rate than a regular savings account. "
            "Interest is calculated on a simple-interest basis and paid "
            "monthly rather than only at maturity. The specific rate for "
            "each term is set by the bank and reviewed periodically — a "
            "branch or relationship officer can confirm the current "
            "rate.\n\n"
            "As with most fixed deposits, withdrawing before the agreed "
            "maturity date typically means forfeiting some or all of the "
            "extra interest a fixed term earns over a regular savings "
            "account."
        ),
    },
    {
        "title": "Diaspora Accounts (Foreign Currency)",
        "category": "products",
        "language": "en",
        "content": (
            "Dashen Bank offers several account types for Ethiopians and "
            "foreign nationals of Ethiopian origin living abroad, held "
            "in US Dollar, British Pound, or Euro.\n\n"
            "The Diaspora Qard Current Account gives ready access to your "
            "foreign-currency funds, with a minimum balance of USD 100 or "
            "its equivalent, structured on an interest-free (Qard) "
            "basis. The Diaspora Non-Repatriable Saving Account converts "
            "inbound foreign currency into a high-interest birr savings "
            "account for use inside Ethiopia — once converted, funds stay "
            "in birr and cannot be converted back to foreign currency, "
            "with an initial deposit of USD 100. For longer-term saving, "
            "the Diaspora Fixed Time Deposit requires a minimum of USD "
            "5,000 and blocks withdrawals during the fixed term in "
            "exchange for a higher rate.\n\n"
            "Interest-free options are also available: the Diaspora "
            "Mudarabah Fixed Time Deposit and Diaspora Wadi'ah Saving "
            "Account follow Sharia-compliant structures.\n\n"
            "Dashen also promotes remote account registration — you can "
            "open a diaspora account while still abroad, without needing "
            "to visit Ethiopia in person first."
        ),
    },
    {
        "title": "Amole and Dashen Mobile Plus",
        "category": "how-to",
        "language": "en",
        "content": (
            "Amole is Dashen Bank's digital wallet and payments platform "
            "— one of Ethiopia's earliest digital wallets, now part of "
            "what Dashen calls its banking Super App. With Amole you can "
            "send peer-to-peer transfers, pay utility bills, top up "
            "airtime, cash in and cash out, pay merchants by QR code, and "
            "make bulk transfers to other Amole wallets.\n\n"
            "Dashen Mobile Plus is Dashen's broader mobile and internet "
            "banking service. You can register two ways: visit a branch "
            "or agent, or self-register entirely without a branch visit "
            "through the mobile app, internet banking, or USSD. All "
            "three channels — app, internet banking, and USSD — share "
            "the same username and password, so you only set up your "
            "login once.\n\n"
            "Dashen has also partnered with Thunes to enable instant "
            "cross-border transfers directly into Dashen bank accounts "
            "and Amole wallets from abroad."
        ),
    },
    {
        "title": "Transfers to Telebirr and Other Banks",
        "category": "how-to",
        "language": "en",
        "content": (
            "You can transfer between your Dashen account and other "
            "Ethiopian banks through Dashen Mobile Plus. Dashen also "
            "partners directly with Ethio telecom on telebirr digital "
            "financial services — including telebirr Mela (micro-credit), "
            "telebirr Endekise (credit/overdraft), and telebirr Sanduq "
            "(micro-savings) — aimed at extending financial services to "
            "underserved customers.\n\n"
            "Transfer fees and any transaction limits are set by the bank "
            "and can change; Dashen Mobile Plus and the Amole app show "
            "the applicable fee before you confirm any transfer, which is "
            "the most reliable way to check the current amount."
        ),
    },
    {
        "title": "International Transfers and SWIFT Code",
        "category": "how-to",
        "language": "en",
        "content": (
            "Dashen Bank's SWIFT/BIC code is DASHETAA — use this when "
            "someone abroad is sending you money by international bank "
            "transfer, along with your Dashen account number and branch "
            "details.\n\n"
            "For diaspora customers, Dashen also offers remote account "
            "registration so you can open a Dashen account while still "
            "abroad, and has partnered with Thunes to enable instant "
            "cross-border transfers directly into Dashen bank accounts "
            "and Amole wallets."
        ),
    },
    {
        "title": "ATM and Debit Cards",
        "category": "products",
        "language": "en",
        "content": (
            "Dashen Bank issues co-branded American Express debit cards. "
            "The Dashen American Express Gold Debit Card has a daily ATM "
            "withdrawal limit of up to 30,000 birr, an annual fee of 100 "
            "birr, and a joining fee of 15 birr. The Dashen American "
            "Express Green Debit Card has a daily ATM withdrawal limit of "
            "up to 20,000 birr, an annual fee of 25 birr, and a joining "
            "fee of 10 birr.\n\n"
            "Dashen also offers a Dashen Mastercard multi-currency "
            "international prepaid card, usable for ATM withdrawals and "
            "online purchases both in Ethiopia and abroad.\n\n"
            "If your card is lost or stolen, contact Dashen customer care "
            "immediately to have it blocked, then visit a branch to "
            "request a replacement."
        ),
    },
    {
        "title": "Personal and Business Loans",
        "category": "products",
        "language": "en",
        "content": (
            "Dashen's consumer loans cover house financing, car loans, "
            "education loans, and loans for household equipment "
            "purchases. General eligibility requires holding a Dashen "
            "account already, proof of income, and being employed or "
            "self-employed; the amount considered typically draws on the "
            "applicant's (and where relevant, spouse's) salary.\n\n"
            "Business loans, including working capital financing, "
            "require business registration and license documents, a TIN "
            "certificate, recent tax clearance, financial statements for "
            "the preceding three fiscal years (audited if the loan "
            "request is 5 million birr or more), and adequate "
            "collateral.\n\n"
            "For interest-free financing, DubeAle is Dashen's Sharia-"
            "compliant buy-now-pay-later service, offering terms of 3, 6, "
            "or 12 months with no interest or profit mark-up, up to a "
            "maximum spending limit of 700,000 birr.\n\n"
            "To apply for any loan, visit a branch with your ID and "
            "supporting documents; a loan officer will confirm current "
            "terms for the specific loan type you need."
        ),
    },
    {
        "title": "Branches and Customer Care",
        "category": "general",
        "language": "en",
        "content": (
            "Dashen Bank operates a growing nationwide branch, ATM, and "
            "point-of-sale network across Ethiopia, alongside its Amole "
            "and Dashen Mobile Plus digital channels for banking outside "
            "branch hours.\n\n"
            "For customer care, Dashen can be reached by email at "
            "info@dashenbanksc.com. For account-specific issues, current "
            "phone numbers and your nearest branch are listed on Dashen's "
            "official website and in the Dashen Mobile Plus app — always "
            "verify you're using the official app or the official "
            "dashenbanksc.com website."
        ),
    },
    {
        "title": "Fraud Prevention and Account Safety",
        "category": "general",
        "language": "en",
        "content": (
            "To protect yourself from fraud and scams, follow Dashen "
            "Bank's own published safety guidance: Dashen will never ask "
            "you to share personal, account, or security information "
            "through social media, and social media is never an "
            "appropriate channel to discuss your products or financial "
            "arrangements with the bank.\n\n"
            "Never share your PIN, password, or any one-time code with "
            "anyone, including someone claiming to be calling from "
            "Dashen. Always confirm you're using the official Dashen "
            "Mobile Plus app or the official dashenbanksc.com website "
            "before entering any banking details.\n\n"
            "If you suspect fraud on your account, or lose your card or "
            "phone, contact Dashen customer care immediately to secure "
            "your account, then visit a branch as soon as possible."
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
            "A simple starting rule for budgeting is 50/30/20: roughly "
            "half of income for needs (rent, food, transport), 30% for "
            "wants, and 20% saved. What matters most is saving something "
            "every month and building the habit, even if the amount "
            "starts small.\n\n"
            "Pay yourself first: move savings to a separate account as "
            "soon as you're paid, before spending. Build an emergency "
            "fund covering a few months of expenses in an account you can "
            "access quickly before considering longer-term or "
            "higher-risk products.\n\n"
            "Ethiopia's Ethiopian Securities Exchange (ESX) opened in "
            "2025 as the country's stock market, giving savers a new way "
            "to invest in listed companies through licensed brokers "
            "regulated by the Ethiopian Capital Market Authority. As "
            "with any investment, higher potential returns come with "
            "higher risk, and it's wise to speak with a licensed advisor "
            "before making investment decisions with money you may need "
            "soon."
        ),
    },
    {
        "title": "የቁጠባ ሂሳቦች (Savings Accounts — Amharic)",
        "category": "products",
        "language": "am",
        "content": (
            "የዳሸን ባንክ መደበኛ የቁጠባ ሂሳብ በወርሃዊ ዝቅተኛ ቀሪ ሂሳብዎ ላይ በየወሩ የሚደራረብ "
            "ወለድ ይከፍላል። ትክክለኛውን የወለድ መጠን በቅርንጫፍ ወይም በDashen Mobile "
            "Plus መተግበሪያ ያረጋግጡ።\n\n"
            "ለወጣቶች የቁጠባ ሂሳብ በዝቅተኛ የመክፈቻ መጠን (እስከ 25 ብር)፣ ዝቅተኛ ወይም "
            "ከፍተኛ ገደብ ሳይኖረው፣ እና ያለ ገንዘብ በወላጅ ወይም በአሳዳጊ ሊከፈት ይችላል።\n\n"
            "ሂሳብ ለመክፈት የሚያስፈልጉ ነገሮች፡ ዘምኖ የተሰራ ብሔራዊ መታወቂያ ወይም ፓስፖርት፣ "
            "ሁለት ጉርድ ፎቶዎች እና ዕድሜዎ 18 እና ከዚያ በላይ መሆን አለበት።"
        ),
    },
    {
        "title": "Amole እና የሞባይል ባንኪንግ (Amole and Mobile Banking — Amharic)",
        "category": "how-to",
        "language": "am",
        "content": (
            "Amole የዳሸን ባንክ ዲጂታል ዋሌት እና የክፍያ መድረክ ነው — ገንዘብ ማስተላለፍ፣ "
            "የአገልግሎት ክፍያዎችን መክፈል፣ የአየር ሰዓት መሙላት እና በQR ኮድ ለነጋዴዎች "
            "መክፈል ይችላሉ።\n\n"
            "Dashen Mobile Plus ለመመዝገብ ሁለት መንገዶች አሉ፡ ወደ ቅርንጫፍ ወይም ወኪል "
            "በመሄድ፣ ወይም ያለ ቅርንጫፍ ጉብኝት በመተግበሪያው፣ በኢንተርኔት ባንኪንግ ወይም "
            "በUSSD በራስዎ መመዝገብ ይችላሉ — ሁሉም በአንድ የይለፍ ቃል ይሰራሉ።"
        ),
    },
]


def seed() -> tuple[Bank, bool]:
    """Create the Dashen prospect-demo bank if missing. Returns (bank, created)."""
    return seed_prospect_bank(
        slug=DASHEN_SLUG,
        name=DASHEN_NAME,
        primary_color="#0e4d92",
        disclaimer=prospect_disclaimer("Dashen Bank", DASHEN_NAME),
        docs=_DOCS,
    )


if __name__ == "__main__":
    bank, created = seed()
    print_seed_summary(bank, created, "Dashen prospect-demo bank", "dashen")
