"""Seed an Awash Bank sales-demo tenant from Awash's own publicly
published information.

This is a PROSPECT DEMO, not a live Awash product: Awash has not
commissioned or endorsed this. The widget shows a persistent disclaimer
banner (`Bank.disclaimer`) saying so — see seed_common.py. Every figure
below is sourced from public material; see SOURCES_AWASH.md in the repo
root for citations and confidence level per fact. awashbank.com itself
returned HTTP 403 to automated fetches during research, so content is
drawn from search-engine synthesis of the bank's own pages plus
independent secondary sources — several facts that would normally be
usable are instead left qualitative because they could only be confirmed
from a single source, or because sources gave conflicting numbers (e.g.
fixed-deposit rates, exact branch count, and most transfer/card fees are
not stated as figures anywhere in this file for that reason). Same "tool
output is truth" doctrine as the product itself — a wrong figure in a bank
demo is worse than a vaguer but honest one.

Run:  python -m bankassist.seed_awash
"""

from __future__ import annotations

from .agent import WHY_CHOOSE_CATEGORY
from .models import Bank
from .seed_common import print_seed_summary, prospect_disclaimer, seed_prospect_bank

AWASH_SLUG = "awash"
AWASH_NAME = "Awash Bank"

_DOCS: list[dict[str, str]] = [
    {
        "title": "Why Choose Awash Bank",
        "category": WHY_CHOOSE_CATEGORY,
        "language": "en",
        "content": (
            "Awash Bank — originally Awash International Bank — was "
            "established on November 10, 1994 by 486 founding "
            "shareholders, becoming Ethiopia's first private commercial "
            "bank after the 1994 Banking Business Proclamation ended the "
            "state banking monopoly. Three decades on, Awash has grown "
            "into one of Ethiopia's largest private banks, with a branch "
            "network approaching 1,000 locations nationwide.\n\n"
            "Awash was an early mover in interest-free banking with "
            "Ikhlas, its dedicated Sharia-compliant banking window, "
            "offering Wadiah current accounts, Mudarabah profit-sharing "
            "savings, Murabaha financing, and Ijarah lease-to-own "
            "products under an independent Shariah framework.\n\n"
            "In February 2024, Awash partnered with Mastercard to launch "
            "an international prepaid card and payment gateway service, "
            "extending its reach for customers who transact "
            "internationally. Awash also operates one of Ethiopia's "
            "broader agent banking networks, bringing basic banking "
            "services to areas without a full branch, and offers a "
            "dedicated suite of diaspora banking products — foreign "
            "currency accounts, and diaspora-specific mortgage and auto "
            "loan financing — for Ethiopians building a life abroad "
            "while investing back home.\n\n"
            "Whatever matters most — the heritage of Ethiopia's original "
            "private bank, interest-free banking, or a growing "
            "nationwide network — Awash was built to offer it at "
            "national scale."
        ),
    },
    {
        "title": "Savings Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "Awash Bank's savings accounts pay monthly interest on the "
            "minimum balance held during the month, at a rate set within "
            "the framework the National Bank of Ethiopia allows — ask a "
            "branch or check the AwashBIRR app for the current rate, "
            "since it can be revised.\n\n"
            "Awash offers several savings products for different needs: "
            "the Lucy Women's Special Savings Account for women 18 and "
            "over (salaried, self-employed, or professional), the Smart "
            "Children Account for parents and guardians saving toward a "
            "child's education, and a Student Account designed for "
            "full-time higher-education students. For interest-free "
            "banking, Awash's Ikhlas window offers a Wadiah-based "
            "current account and a Mudarabah profit-sharing savings "
            "account.\n\n"
            "To open a savings account you generally need a valid ID and "
            "to be 18 or over; a branch can confirm the current minimum "
            "opening deposit and any documents needed for the specific "
            "account type you want."
        ),
    },
    {
        "title": "Fixed Time Deposit Accounts",
        "category": "products",
        "language": "en",
        "content": (
            "An Awash Fixed (Time) Deposit Account locks your money for "
            "an agreed term — a minimum of six months — in exchange for "
            "a higher interest rate than a regular savings account, with "
            "larger amounts and longer terms generally earning more. "
            "Interest rates vary by amount and duration and are set by "
            "the bank; a branch or relationship officer can confirm the "
            "current rate for the term you want.\n\n"
            "If you withdraw before the agreed maturity date, you "
            "forfeit the interest that would otherwise have accrued — so "
            "a fixed deposit suits money you're confident you won't need "
            "before the term ends."
        ),
    },
    {
        "title": "Diaspora Accounts (Foreign Currency)",
        "category": "products",
        "language": "en",
        "content": (
            "Awash Bank offers foreign-currency accounts for Ethiopian "
            "nationals and Ethiopian-owned businesses based abroad. To "
            "qualify, you generally need to have lived or worked abroad "
            "for more than a year (or, for a business, be owned by a "
            "non-resident Ethiopian based outside the country for more "
            "than a year).\n\n"
            "Awash offers Non-Resident Transferable accounts in US "
            "Dollar, Euro, and British Pound, plus Retention Accounts "
            "that let exporters hold foreign currency earnings rather "
            "than converting immediately. You can open an account in "
            "person, by post, or through a nearby Ethiopian embassy, "
            "correspondent bank, or remittance service provider if you "
            "can't visit in person.\n\n"
            "Awash also offers diaspora-specific credit: mortgage and "
            "auto loans tailored for Ethiopians abroad who want to "
            "invest back home, available to applicants with verifiable, "
            "steady income."
        ),
    },
    {
        "title": "AwashBIRR Mobile Banking",
        "category": "how-to",
        "language": "en",
        "content": (
            "AwashBIRR is Awash Bank's mobile banking app, available for "
            "iOS and Android. To activate it, visit an Awash Bank branch "
            "or agent to receive a PIN sent to your registered mobile "
            "number, then dial *901#, enter your PIN, and set a new one. "
            "You don't need mobile internet to use it — only mobile "
            "network coverage.\n\n"
            "With AwashBIRR you can check your balance, transfer money, "
            "pay bills, and top up airtime. If you have trouble with your "
            "PIN, visit your nearest branch or call Awash's toll-free "
            "line."
        ),
    },
    {
        "title": "Transfers to Other Banks and Wallets",
        "category": "how-to",
        "language": "en",
        "content": (
            "You can transfer between your Awash account and other "
            "Ethiopian banks or mobile wallets through AwashBIRR. Fees "
            "vary by amount and channel and are published in Awash's own "
            "tariff schedule — the app shows the applicable fee before "
            "you confirm any transfer, which is the most reliable way to "
            "check the current amount. Internal transfers between Awash "
            "accounts are generally the most cost-effective option."
        ),
    },
    {
        "title": "International Transfers and SWIFT Code",
        "category": "how-to",
        "language": "en",
        "content": (
            "Awash Bank's SWIFT/BIC code is AWINETAA — use this when "
            "someone abroad is sending you money by international bank "
            "transfer, along with your Awash account number and branch "
            "details.\n\n"
            "For customers abroad, Awash also offers diaspora foreign-"
            "currency accounts you can open in person, by post, or "
            "through a nearby Ethiopian embassy or correspondent bank if "
            "you can't visit in person."
        ),
    },
    {
        "title": "ATM and Debit Cards",
        "category": "products",
        "language": "en",
        "content": (
            "Awash Bank offers the Sheba Miles debit card, co-branded "
            "with Ethiopian Airlines' ShebaMiles loyalty program, "
            "letting you earn miles on everyday banking. For "
            "interest-free banking, the Amanah Card is available under "
            "Awash's Ikhlas window. In February 2024, Awash partnered "
            "with Mastercard to launch an international multi-currency "
            "prepaid card and payment gateway, for customers who need to "
            "transact abroad.\n\n"
            "Awash ATMs operate 24 hours a day, every day, supporting "
            "cash withdrawal, balance inquiry, mini-statements, transfers "
            "between your own accounts, and PIN changes.\n\n"
            "If your card is lost or stolen, contact Awash customer care "
            "immediately to have it blocked, then visit a branch for a "
            "replacement."
        ),
    },
    {
        "title": "Personal and Business Loans",
        "category": "products",
        "language": "en",
        "content": (
            "Awash Bank offers mortgage/home loans, personal and "
            "consumer loans, car loans, and financing for selected "
            "productive business projects. A general-purpose Term Loan "
            "is available with repayment terms from 13 to 60 months, "
            "including any grace period.\n\n"
            "Awash-Lehulum is Awash's micro-credit product, with loans up "
            "to 20,000 birr; eligibility requires a valid, renewed ID, "
            "Ethiopian nationality, and permanent residence in Ethiopia. "
            "For a mortgage loan, Awash generally expects at least a "
            "year of prior deposit history and a down payment of at "
            "least 30% of the property price (a minimum of 100,000 birr) "
            "before financing the rest.\n\n"
            "Diaspora mortgage and auto loans are available to eligible "
            "Ethiopians abroad with verifiable, steady income.\n\n"
            "To apply for any loan, visit a branch with your ID and "
            "supporting income documents; a loan officer will confirm "
            "current terms for the loan type you need."
        ),
    },
    {
        "title": "Branches, Hours, and Customer Care",
        "category": "general",
        "language": "en",
        "content": (
            "Awash Bank branches are typically open Monday through "
            "Saturday, 8:00 AM to 5:00 PM — check your nearest branch's "
            "posted hours to confirm, as they can vary. Awash's "
            "toll-free customer care line, 8980, is available separately "
            "from branch hours for phone support.\n\n"
            "Awash's head office is at Awash Tower on Ras Abebe Aregay "
            "Street, in the Kirkos area of Addis Ababa. Awash also "
            "operates an agent banking network — authorized local "
            "businesses offering basic banking services — extending its "
            "reach beyond the branch network."
        ),
    },
    {
        "title": "Fraud Prevention and Account Safety",
        "category": "general",
        "language": "en",
        "content": (
            "To protect yourself from fraud, follow Awash Bank's own "
            "published safety guidance: at any ATM or card machine, "
            "shield the keypad with your other hand while entering your "
            "PIN, watch for hidden cameras, and stay at the machine "
            "until you've fully logged out — leaving early can let the "
            "next person access your session.\n\n"
            "Be alert to phone scams where someone poses as a bank "
            "employee or government official to ask for your PIN, "
            "password, card details, or your Awash Secure Code — never "
            "share these, even with someone claiming to call from the "
            "bank. Also watch for a common ATM scam where a stranger "
            "offers unsolicited help at the machine in order to see your "
            "card number and PIN.\n\n"
            "Change your Awash internet banking password regularly, and "
            "check your statements often for anything unfamiliar. If you "
            "suspect fraud on your account, or lose your card or phone, "
            "contact Awash customer care immediately, then visit a "
            "branch as soon as possible."
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
            "fund covering a few months of expenses in an account you "
            "can access quickly before considering longer-term or "
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
            "የአዋሽ ባንክ የቁጠባ ሂሳቦች በወሩ ውስጥ በያዙት ዝቅተኛ ቀሪ ሂሳብ ላይ ወርሃዊ ወለድ "
            "ይከፍላሉ። ትክክለኛውን የወለድ መጠን በቅርንጫፍ ወይም በAwashBIRR መተግበሪያ "
            "ያረጋግጡ።\n\n"
            "አዋሽ ለተለያዩ ፍላጎቶች የተለያዩ የቁጠባ ምርቶችን ያቀርባል፡ ለሴቶች የተዘጋጀ "
            "የሉሲ ልዩ የቁጠባ ሂሳብ (ከ18 ዓመት በላይ)፣ ወላጆች ለልጆቻቸው ትምህርት "
            "የሚቆጥቡበት ስማርት ችልድረን ሂሳብ፣ እና ለተማሪዎች የተዘጋጀ ሂሳብ።\n\n"
            "ሂሳብ ለመክፈት ህጋዊ መታወቂያ እና ዕድሜዎ 18 እና ከዚያ በላይ መሆን ያስፈልጋል።"
        ),
    },
    {
        "title": "የሞባይል ባንኪንግ (AwashBIRR Mobile Banking — Amharic)",
        "category": "how-to",
        "language": "am",
        "content": (
            "AwashBIRR የአዋሽ ባንክ የሞባይል ባንኪንግ መተግበሪያ ነው። ለማስጀመር ወደ "
            "ቅርንጫፍ ወይም ወኪል በመሄድ በተመዘገበው ስልክ ቁጥርዎ ፒን ያግኙ፣ ከዚያ *901# "
            "ደውለው ፒንዎን አስገብተው አዲስ ፒን ያዘጋጁ። የኢንተርኔት ግንኙነት ሳያስፈልግ "
            "የሞባይል ኔትወርክ ብቻ በቂ ነው።\n\n"
            "በAwashBIRR ቀሪ ሂሳብዎን ማየት፣ ገንዘብ ማስተላለፍ፣ የአገልግሎት ክፍያዎችን "
            "መክፈል እና የአየር ሰዓት መሙላት ይችላሉ።"
        ),
    },
]


def seed() -> tuple[Bank, bool]:
    """Create the Awash prospect-demo bank if missing. Returns (bank, created)."""
    return seed_prospect_bank(
        slug=AWASH_SLUG,
        name=AWASH_NAME,
        primary_color="#c8102e",
        disclaimer=prospect_disclaimer("Awash Bank", AWASH_NAME),
        docs=_DOCS,
    )


if __name__ == "__main__":
    bank, created = seed()
    print_seed_summary(bank, created, "Awash prospect-demo bank", "awash")
