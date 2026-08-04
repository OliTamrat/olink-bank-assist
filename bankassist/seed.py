"""Seed a demo tenant with a realistic (but fictional) Ethiopian banking
knowledge base. All figures are illustrative — this is sales-demo data for a
made-up institution, deliberately NOT branded as any real bank.

Run:  python -m bankassist.seed
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import get_engine, init_db
from .models import Bank, Document
from .retrieval import reindex_document

DEMO_SLUG = "demo"

_DOCS: list[dict[str, str]] = [
    {
        "title": "Savings Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "Demo Bank Ethiopia offers three savings products.\n\n"
            "Regular Savings Account: minimum opening balance 50 birr, interest rate 7% "
            "per year (illustrative), no monthly fee, unlimited deposits and withdrawals "
            "at any branch or via mobile banking.\n\n"
            "Youth Savings Account: for customers under 18, opened with a parent or "
            "guardian, minimum opening balance 25 birr, interest rate 8% per year "
            "(illustrative), no fees.\n\n"
            "Women's Savings Account: designed for women entrepreneurs, minimum opening "
            "balance 50 birr, preferential loan consideration after 6 months of regular "
            "saving.\n\n"
            "To open any savings account you need: a valid ID (kebele ID, national ID, "
            "passport, or driving licence), one passport-size photograph, and the minimum "
            "opening balance. Opening takes about 15 minutes at any branch."
        ),
    },
    {
        "title": "Fixed (Time) Deposit Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "A fixed deposit (also called a time deposit) locks your money for an agreed "
            "period in exchange for a higher interest rate than a regular savings "
            "account.\n\n"
            "Demo Bank fixed deposit terms (illustrative rates): 3 months at 8.5% per "
            "year, 6 months at 9%, 12 months at 10%, 24 months at 11%. Minimum deposit "
            "10,000 birr.\n\n"
            "Interest is paid at maturity. If you withdraw before the maturity date, the "
            "deposit earns the regular savings rate instead of the fixed rate. There is "
            "no penalty fee beyond losing the higher rate.\n\n"
            "A fixed deposit suits money you will not need for a while — for example "
            "savings for school fees due next year. For money you may need at any time, "
            "a regular savings account is more suitable."
        ),
    },
    {
        "title": "Diaspora Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "Ethiopians and foreign nationals of Ethiopian origin living abroad can open "
            "diaspora accounts in foreign currency (USD, GBP, or EUR).\n\n"
            "Fixed Diaspora Deposit: minimum 5,000 USD equivalent, terms from 3 months to "
            "2 years, interest paid in foreign currency (rates follow National Bank of "
            "Ethiopia directives).\n\n"
            "Non-Repatriable Birr Account: deposit foreign currency, hold birr for local "
            "use such as supporting family or investing in Ethiopia.\n\n"
            "Required documents: copy of passport or origin ID card, proof of residence "
            "abroad (such as a residence permit or utility bill), and a completed "
            "application form. Accounts can be opened remotely — email the completed "
            "forms to our diaspora banking desk and a relationship officer will guide "
            "you through verification."
        ),
    },
    {
        "title": "How to Activate and Use Mobile Banking",
        "category": "how-to",
        "language": "en",
        "content": (
            "To activate Demo Bank mobile banking: download the Demo Bank app from the "
            "Google Play Store or Apple App Store, choose Register, enter your account "
            "number and the phone number registered with the bank, then enter the "
            "one-time code sent by SMS and set your PIN.\n\n"
            "With mobile banking you can check your balance, view your last "
            "transactions, transfer to Demo Bank and other Ethiopian banks, buy airtime, "
            "and pay utility bills.\n\n"
            "If you forget your PIN, choose Forgot PIN in the app, or dial our USSD "
            "short code and follow the reset steps, or visit any branch with your ID. "
            "For your security, bank staff will NEVER ask for your PIN or the SMS codes "
            "— do not share them with anyone, including people claiming to call from "
            "the bank."
        ),
    },
    {
        "title": "Transfers Between Banks and to telebirr",
        "category": "how-to",
        "language": "en",
        "content": (
            "You can send money from Demo Bank to any Ethiopian bank through the "
            "national instant payment switch. In the mobile app choose Transfer, then "
            "Other Banks, select the receiving bank, and enter the account number and "
            "amount. Transfers normally arrive within seconds.\n\n"
            "You can also transfer between your bank account and mobile money wallets "
            "such as telebirr: choose Transfer to Wallet, enter the wallet phone "
            "number and amount, and confirm with your PIN.\n\n"
            "Transfer fees (illustrative): transfers between Demo Bank accounts are "
            "free; transfers to other banks or wallets cost 5 to 15 birr depending on "
            "the amount. Daily mobile transfer limit: 100,000 birr for standard "
            "accounts. Always check the receiver's name shown on the confirmation "
            "screen before you confirm."
        ),
    },
    {
        "title": "ATM and Debit Cards",
        "category": "products",
        "language": "en",
        "content": (
            "Every Demo Bank current or savings account holder can request a debit "
            "card at their branch. The first card is free; replacing a lost card costs "
            "100 birr (illustrative).\n\n"
            "Cards work at Demo Bank ATMs and at any ATM on the shared national "
            "network. Daily ATM withdrawal limit: 10,000 birr (illustrative).\n\n"
            "If your card is lost or stolen, block it immediately: in the mobile app "
            "choose Cards then Block Card, or call our 24-hour customer care line. "
            "You can order a replacement at any branch. Never write your PIN on the "
            "card or share it with anyone."
        ),
    },
    {
        "title": "Personal and Business Loans",
        "category": "products",
        "language": "en",
        "content": (
            "Demo Bank offers the following credit products (illustrative terms).\n\n"
            "Personal Loan: for salaried employees, up to 20 times monthly salary, "
            "repayment up to 5 years, interest from 15% per year. Requires an employer "
            "salary letter and 6 months of salary history.\n\n"
            "Business Working Capital Loan: for licensed businesses, amount based on "
            "business cash flow and collateral, repayment up to 3 years.\n\n"
            "Mortgage Loan: up to 80% of the property value, repayment up to 20 years.\n\n"
            "Women-owned businesses that have saved regularly in a Women's Savings "
            "Account for 6 months receive preferential consideration and may qualify "
            "with reduced collateral.\n\n"
            "To apply, visit any branch with your ID, your business licence (for "
            "business loans), and collateral documents. A loan officer will assess your "
            "application; typical decisions take 5 to 10 working days."
        ),
    },
    {
        "title": "Understanding Treasury Bills and the Ethiopian Securities Exchange",
        "category": "financial-education",
        "language": "en",
        "content": (
            "This is general financial education, not investment advice.\n\n"
            "A treasury bill (T-bill) is a short-term security issued by the government "
            "through the National Bank of Ethiopia. You lend money to the government "
            "for 28, 91, 182, or 364 days and receive it back with a return determined "
            "at auction. T-bills are considered among the lowest-risk investments "
            "because they are backed by the government.\n\n"
            "The Ethiopian Securities Exchange (ESX) opened in 2025 as Ethiopia's stock "
            "market. Companies list shares on the exchange, and investors can buy and "
            "sell those shares through licensed brokers regulated by the Ethiopian "
            "Capital Market Authority (ECMA).\n\n"
            "General principles of investing: higher potential returns come with higher "
            "risk; spreading money across different investments (diversification) "
            "reduces risk; and money you may need soon is usually better kept in "
            "savings or short-term deposits than in shares. For decisions about your "
            "own money, speak with a licensed investment advisor."
        ),
    },
    {
        "title": "Saving and Budgeting Basics",
        "category": "financial-education",
        "language": "en",
        "content": (
            "A simple starting rule for budgeting is 50/30/20: about half of income "
            "for needs (rent, food, transport), 30% for wants, and 20% saved. Adjust "
            "the shares to your situation — what matters is saving something every "
            "month, even a small amount.\n\n"
            "Pay yourself first: move savings to a separate account on payday, before "
            "spending. An account without a debit card linked can help resist "
            "temptation.\n\n"
            "Build an emergency fund covering 3 to 6 months of expenses before "
            "considering longer-term investments. Keep it in a savings account where "
            "you can reach it quickly.\n\n"
            "Equb (rotating savings groups) are a traditional way many Ethiopians "
            "save. A bank savings account can complement an equb by keeping your "
            "payout safe and earning interest."
        ),
    },
    {
        "title": "Branches, Hours, and Customer Care",
        "category": "general",
        "language": "en",
        "content": (
            "Demo Bank branches are open Monday to Friday 8:00 to 17:00 and Saturday "
            "8:00 to 12:30. Selected city branches offer extended evening hours.\n\n"
            "Customer care: call 8000 (illustrative short code) from any phone, "
            "available 24 hours for card blocking and urgent issues, 7:00 to 21:00 for "
            "general questions. You can also reach us on Telegram or at any branch.\n\n"
            "Services available at every branch: account opening, cash deposit and "
            "withdrawal, transfers, loan applications, card requests, and foreign "
            "currency services at licensed branches."
        ),
    },
    {
        "title": "የቁጠባ ሂሳቦች (Savings Accounts — Amharic)",
        "category": "products",
        "language": "am",
        "content": (
            "ዴሞ ባንክ ኢትዮጵያ ሶስት የቁጠባ ምርቶችን ያቀርባል።\n\n"
            "መደበኛ የቁጠባ ሂሳብ፡ ዝቅተኛ መክፈቻ 50 ብር፣ የወለድ መጠን በዓመት 7% (ለማሳያ)፣ "
            "ወርሃዊ ክፍያ የለውም፣ በማንኛውም ቅርንጫፍ ወይም በሞባይል ባንኪንግ ገንዘብ ማስገባትና "
            "ማውጣት ይቻላል።\n\n"
            "የወጣቶች ቁጠባ ሂሳብ፡ ከ18 ዓመት በታች ለሆኑ፣ ከወላጅ ወይም ከአሳዳጊ ጋር የሚከፈት፣ "
            "ዝቅተኛ መክፈቻ 25 ብር፣ የወለድ መጠን በዓመት 8% (ለማሳያ)።\n\n"
            "ሂሳብ ለመክፈት የሚያስፈልጉ ነገሮች፡ ህጋዊ መታወቂያ (የቀበሌ መታወቂያ፣ ብሔራዊ መታወቂያ፣ "
            "ፓስፖርት ወይም መንጃ ፈቃድ)፣ አንድ ጉርድ ፎቶ እና ዝቅተኛው መክፈቻ ገንዘብ። "
            "በማንኛውም ቅርንጫፍ በ15 ደቂቃ ውስጥ መክፈት ይችላሉ።"
        ),
    },
    {
        "title": "የሞባይል ባንኪንግ አጠቃቀም (Mobile Banking — Amharic)",
        "category": "how-to",
        "language": "am",
        "content": (
            "የዴሞ ባንክ ሞባይል ባንኪንግ ለማስጀመር፡ መተግበሪያውን ከGoogle Play ወይም ከApp Store "
            "ያውርዱ፣ ይመዝገቡ የሚለውን ይምረጡ፣ የሂሳብ ቁጥርዎን እና በባንኩ የተመዘገበውን ስልክ ቁጥር "
            "ያስገቡ፣ በSMS የሚላከውን ኮድ አስገብተው ፒን ያዘጋጁ።\n\n"
            "በሞባይል ባንኪንግ ቀሪ ሂሳብዎን ማየት፣ ገንዘብ ወደ ማንኛውም ባንክ ማስተላለፍ፣ የአየር ሰዓት "
            "መግዛት እና የአገልግሎት ክፍያዎችን መክፈል ይችላሉ።\n\n"
            "ለደህንነትዎ፡ የባንክ ሰራተኞች ፒንዎን ወይም የSMS ኮድ በፍጹም አይጠይቁም። "
            "ከባንክ ነን ብለው ለሚደውሉ ሰዎች ፒንዎን ወይም ኮድዎን አያካፍሉ።"
        ),
    },
    {
        "title": "የገንዘብ ዝውውር (Transfers — Amharic)",
        "category": "how-to",
        "language": "am",
        "content": (
            "ከዴሞ ባንክ ወደ ማንኛውም የኢትዮጵያ ባንክ በብሔራዊ የክፍያ ሲስተም በኩል ገንዘብ መላክ "
            "ይችላሉ። በመተግበሪያው ውስጥ ማስተላለፍ የሚለውን ይምረጡ፣ ተቀባዩን ባንክ ይምረጡ፣ "
            "የሂሳብ ቁጥርና መጠን ያስገቡ። ዝውውሩ በሰከንዶች ውስጥ ይደርሳል።\n\n"
            "እንዲሁም ወደ ቴሌብር እና ሌሎች የሞባይል ገንዘብ አገልግሎቶች ማስተላለፍ ይችላሉ፡ ወደ ዋሌት "
            "ማስተላለፍ የሚለውን መርጠው የስልክ ቁጥሩንና መጠኑን ያስገቡ።\n\n"
            "የዝውውር ክፍያ (ለማሳያ)፡ በዴሞ ባንክ ሂሳቦች መካከል ነጻ፤ ወደ ሌሎች ባንኮች ወይም ዋሌቶች "
            "ከ5 እስከ 15 ብር። ከማረጋገጥዎ በፊት በማያ ገጹ ላይ የሚታየውን የተቀባይ ስም ሁልጊዜ ያረጋግጡ።"
        ),
    },
]


def seed() -> tuple[Bank, bool]:
    """Create the demo bank if missing. Returns (bank, created)."""
    init_db()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as db:
        existing = db.execute(select(Bank).where(Bank.slug == DEMO_SLUG)).scalar_one_or_none()
        if existing is not None:
            return existing, False
        bank = Bank(slug=DEMO_SLUG, name="Demo Bank Ethiopia", primary_color="#0f766e")
        db.add(bank)
        db.flush()
        for spec in _DOCS:
            doc = Document(bank_id=bank.id, **spec)
            db.add(doc)
            db.flush()
            reindex_document(db, doc)
        db.commit()
        return bank, True


if __name__ == "__main__":
    bank, created = seed()
    status = "created" if created else "already exists"
    print(f"Demo bank {status}: {bank.name} (slug={bank.slug})")
    print(f"Admin token: {bank.admin_token}")
    print("Widget:  http://localhost:8100/widget?bank=demo")
    print("Admin:   http://localhost:8100/admin")
