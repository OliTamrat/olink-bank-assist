"""What a bank's customers ask that its corpus cannot answer.

Run: `python scripts/corpus_gaps.py`            # every seeded tenant
     `python scripts/corpus_gaps.py cbe dashen` # just these

**The corpus is the ceiling** (CLAUDE.md). Every tenant runs on fifteen to
twenty-three documents where a real bank's public site is several hundred
pages, and nothing about the model, the prompt or retrieval moves the answer
rate as much as content does. So "make the assistant better" is usually
"write more documents" — and the expensive way to do that is to write a
hundred and discover half of them duplicated what was already there.

This measures instead, in **extractive mode with no LLM configured**, so a
miss is a missing document rather than a model having a bad day.

**It does NOT measure the `unanswered` intent, and that is the whole point.**
The first version of this script did, and reported CBE at 100% covered — which
was nonsense. `unanswered` fires only when retrieval returns *zero* documents,
and BM25 always returns something. Asked whether you can set up a standing
order, it scored a pass while returning the 50/30/20 budgeting document; asked
the cost of a replacement card, it passed on a page about card tiers that
names no fee; asked about opening an account for a child, it passed on CBE
Noor's Sharia governance. Retrieval returning *a* document is not the corpus
containing *the* answer, and a metric that cannot tell those apart reads as
coverage while measuring nothing.

So every question carries `expect` — terms any genuine answer would have to
contain, in the style of `golden_questions.json`. A reply missing all of them
is a gap even when retrieval was confident. The terms are deliberately loose
(a fee answer needs a number and the word fee, not a particular sentence) so
this measures whether the *fact* is in the corpus, not whether a document is
phrased the way the question was.

Output is grouped by category and sorted worst-first, which is the order the
documents should be written in.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

# Questions a customer actually asks, with the terms any genuine answer would
# have to contain. Deliberately plain-spoken and sometimes badly formed — that
# is how they arrive. English only: the corpus is English-dominant, so English
# questions isolate *content* coverage from *language* handling, which the
# phrasebook and the cross-language retrieval tests cover separately.
#
# `expect` is loose on purpose. A fee answer needs a number and the word fee,
# not a particular sentence; a dispute answer needs a route to take, not a
# specific SLA. Tight terms would measure phrasing, and phrasing is not what
# is missing.
QUESTIONS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "fees and charges": (
        ("How much do you charge for withdrawing from another bank's ATM?",
         ("birr", "free", "no charge")),
        ("What is the monthly service charge on a savings account?",
         ("birr", "free", "no charge", "no monthly")),
        ("Is there a fee to transfer money to another bank?",
         ("birr", "free", "no charge")),
        ("How much does a new ATM card cost if I lose mine?",
         ("birr", "free", "no charge")),
        ("What do you charge for a bank statement?",
         ("birr", "free", "no charge")),
        ("Are there charges if my account goes dormant?",
         ("birr", "dormant", "free", "no charge")),
    ),
    "disputes and problems": (
        ("The ATM took my money but did not give me cash. What do I do?",
         ("dispute", "claim", "report", "refund", "revers")),
        ("I sent money to the wrong account number. Can you reverse it?",
         ("revers", "dispute", "recall", "cannot be undone")),
        ("Someone withdrew money from my account without permission.",
         ("report", "block", "dispute", "unauthoris", "unauthoriz", "fraud")),
        ("My transfer failed but the money left my account.",
         ("revers", "refund", "dispute", "settle", "working days")),
        ("How do I make a complaint about a branch?",
         ("complain", "grievance", "ombuds", "customer service")),
        ("How long does it take to resolve a dispute?",
         ("days", "working day", "week")),
    ),
    "cards": (
        ("I lost my debit card, how do I block it?",
         ("block", "report", "lost", "call")),
        ("I forgot my ATM PIN, how do I reset it?",
         ("pin", "reset", "reissue", "branch")),
        ("Can I use my card outside Ethiopia?",
         ("international", "abroad", "outside ethiopia", "visa", "mastercard")),
        ("How much can I withdraw from an ATM per day?",
         ("birr", "limit", "per day", "daily")),
        ("My card is expiring, how do I renew it?",
         ("renew", "expir", "replace", "branch")),
        ("My card was swallowed by the machine.",
         ("retain", "swallow", "captur", "branch", "collect")),
    ),
    "account opening and KYC": (
        ("What documents do I need to open an account?",
         ("id", "identification", "passport", "photo", "kebele")),
        ("Can I open an account for my child?",
         ("child", "minor", "under 18", "guardian", "birth certificate")),
        ("Can two people share one account?",
         ("joint", "two people", "both signator")),
        ("What is the minimum age to open an account?",
         ("age", "18", "years old", "minor")),
        ("I do not have a kebele ID, can I still open an account?",
         ("passport", "driving licence", "driver", "fayda", "ፋይዳ", "id")),
        ("How do I open a business account for my company?",
         ("business", "current account", "trade licence", "tin", "company")),
    ),
    "account maintenance": (
        ("How do I close my account?",
         ("close", "closure", "branch")),
        ("My account is dormant, how do I reactivate it?",
         ("dormant", "reactivat", "branch", "id")),
        ("How do I change my phone number on my account?",
         ("update", "change", "branch", "phone number")),
        ("How do I get a cheque book?",
         ("cheque", "check book", "current account")),
        ("Can I set up a standing order to pay my rent every month?",
         ("standing order", "recurring", "scheduled", "direct debit")),
        ("How do I check my balance without going to a branch?",
         ("mobile banking", "ussd", "sms", "app", "internet banking")),
    ),
    "loans": (
        ("What collateral do you need for a business loan?",
         ("collateral", "security", "guarantor", "property")),
        ("Can I pay off my loan early?",
         ("early", "prepay", "settle", "penalt")),
        ("What happens if I miss a loan repayment?",
         ("default", "penalt", "late", "arrear", "overdue")),
        ("How long does a loan application take to approve?",
         ("days", "week", "approv")),
        ("Do you give loans to people without a salary?",
         ("salary", "income", "business", "self-employ")),
    ),
    "digital banking": (
        ("I forgot my mobile banking password.",
         ("reset", "forgot", "branch", "call")),
        ("How much can I transfer per day on the app?",
         ("birr", "limit", "per day", "daily")),
        ("The app says my account is locked.",
         ("lock", "unlock", "reset", "branch", "call")),
        ("Can I use mobile banking without internet?",
         ("ussd", "*", "sms", "without internet", "no data")),
        ("How do I register for internet banking?",
         ("internet banking", "register", "branch", "online")),
    ),
    "foreign exchange and diaspora": (
        ("How do I receive money from abroad?",
         ("remittance", "western union", "swift", "transfer", "diaspora")),
        ("What is today's dollar rate?",
         ("rate", "exchange", "usd", "dollar")),
        ("Can I keep foreign currency in my account?",
         ("foreign currency", "fcy", "diaspora", "usd", "retention")),
        ("How much foreign currency can I take when travelling?",
         ("allowance", "limit", "usd", "travel", "nbe")),
        ("What is your SWIFT code?",
         ("swift", "bic")),
    ),
    "interest-free banking": (
        ("Do you offer interest-free banking?",
         ("interest-free", "interest free", "sharia", "islamic", "noor")),
        ("How does Sharia-compliant financing work here?",
         ("murabaha", "mudaraba", "sharia", "profit", "interest-free")),
        ("Can I get a home purchase without interest?",
         ("murabaha", "ijara", "home", "sharia", "interest-free")),
    ),
    "branches and access": (
        ("Are you open on Saturday?",
         ("saturday", "weekend", "hours")),
        ("Where is your nearest branch?",
         ("branch", "locat", "find", "map")),
        ("What are your working hours during Ramadan?",
         ("ramadan", "hours")),
        ("Do you have agents in rural areas?",
         ("agent", "rural", "banking agent")),
    ),
}


UNANSWERED = "unanswered"
"""The product's own name for a content gap — see `agent.py`."""


def main(slugs: list[str]) -> int:
    # Extractive mode: no model, so an unanswered question is a missing
    # document rather than a model that declined.
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.setdefault("BANKASSIST_DATABASE_URL", "sqlite:///./corpus_gaps.db")

    from fastapi.testclient import TestClient

    from bankassist import config, db, index

    config.reset_settings()
    db.reset_engine()
    index.clear()

    from bankassist.api import app

    seeders = {
        "demo": "bankassist.seed",
        "cbe": "bankassist.seed_cbe",
        "dashen": "bankassist.seed_dashen",
        "awash": "bankassist.seed_awash",
    }
    wanted = slugs or list(seeders)

    total_gaps = 0
    with TestClient(app) as client:
        for slug in wanted:
            module = __import__(seeders[slug], fromlist=["seed"])
            module.seed()

            gaps: dict[str, list[str]] = defaultdict(list)
            asked = 0
            for category, questions in QUESTIONS.items():
                for question, expect in questions:
                    asked += 1
                    resp = client.post(f"/chat/{slug}", json={"message": question})
                    resp.raise_for_status()
                    body = resp.json()
                    reply = body["reply"].lower()
                    # A gap is a reply that names none of the things an answer
                    # would have to name — whether or not retrieval was
                    # confident enough to return a document.
                    if not any(term in reply for term in expect):
                        gaps[category].append(question)

            missing = sum(len(v) for v in gaps.values())
            total_gaps += missing
            covered = asked - missing
            print(f"\n{'=' * 66}")
            print(f"  {slug}  —  {covered}/{asked} answered, "
                  f"{missing} gaps ({100 * covered // asked}% covered)")
            print(f"{'=' * 66}")
            # Worst first: that is the order the documents should be written.
            for category, unanswered in sorted(
                gaps.items(), key=lambda kv: -len(kv[1])
            ):
                whole = len(unanswered) == len(QUESTIONS[category])
                flag = "  << no coverage at all" if whole else ""
                print(f"\n  {category}: {len(unanswered)}/"
                      f"{len(QUESTIONS[category])} unanswered{flag}")
                for question in unanswered:
                    print(f"      - {question}")
            if not gaps:
                print("\n  no gaps in this question bank")

    print(f"\n{'=' * 66}\n  {total_gaps} gaps across {len(wanted)} tenant(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
