"""What retrieval budget actually answers the most questions.

Run: `python scripts/topk_sweep.py`

`retrieve()` returns the top 4 chunks. That number was reasonable for a corpus
of fifteen documents and has never been measured against one. ADR-0033 found
out why it matters: adding a single well-sourced document to fill the largest
measured gap took the four tenants from 66 gaps to 70, because the new document
competed for the four slots and displaced answers that were already working.
So `top_k` is a corpus-size assumption, and corpus growth is blocked behind it.

This sweeps it, using `corpus_gaps.py`'s question bank as the score.

**Coverage is not the only axis, which is the whole reason to measure rather
than just raise it.** Every extra chunk is more text in the prompt — more
tokens per answer on a per-conversation cost model, and more chance of burying
a good match in adjacent prose. So this reports both: how many questions get
answered, and how much text it took to answer them. A budget that buys two
more answers for double the context is not obviously the right trade, and the
point of printing them side by side is that the trade becomes visible instead
of assumed.

The gate in `retrieve()` is untouched. This only changes how many chunks that
survive the gate are kept — a bigger budget cannot admit a match the
informativeness gate already refused, which is what keeps this safe to try.
"""

from __future__ import annotations

import os
from collections import defaultdict

BUDGETS = (2, 3, 4, 6, 8, 10, 12)


def main() -> int:
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.setdefault("BANKASSIST_DATABASE_URL", "sqlite:///./topk_sweep.db")
    # This asks the same endpoint ~1,500 times from one address. The chat rate
    # limiter is doing its job by refusing that; it is not what is being
    # measured here, so it is switched off for the sweep only.
    os.environ["BANKASSIST_CHAT_RATE_PER_IP"] = "0"
    os.environ["BANKASSIST_CHAT_RATE_PER_CONVERSATION"] = "0"

    from fastapi.testclient import TestClient

    from bankassist import config, db, index, retrieval

    config.reset_settings()
    db.reset_engine()
    index.clear()

    from corpus_gaps import QUESTIONS

    from bankassist.api import app

    seeders = {
        "demo": "bankassist.seed",
        "cbe": "bankassist.seed_cbe",
        "dashen": "bankassist.seed_dashen",
        "awash": "bankassist.seed_awash",
    }

    original = retrieval.retrieve
    asked = sum(len(v) for v in QUESTIONS.values())

    print(f"{asked} questions x {len(seeders)} tenants = {asked * len(seeders)} asks "
          f"per budget\n")
    print(f"{'top_k':>6}{'answered':>10}{'coverage':>10}{'chars/answer':>14}"
          f"{'vs k=4':>9}")
    print("-" * 49)

    baseline: tuple[int, float] | None = None
    rows: list[tuple[int, int, float]] = []

    with TestClient(app) as client:
        for module_name in seeders.values():
            __import__(module_name, fromlist=["seed"]).seed()

        for budget in BUDGETS:
            # Patch the default. The gate inside retrieve() is untouched —
            # this only changes how many surviving chunks are kept.
            def sized(
                db_: object, bank_id: str, query: str, top_k: int = budget
            ) -> object:
                return original(db_, bank_id, query, top_k)  # type: ignore[arg-type]

            retrieval.retrieve = sized  # type: ignore[assignment]
            import bankassist.agent as agent_module

            agent_module.retrieve = sized  # type: ignore[attr-defined,assignment]
            # The extractive answer is built from MAX_FALLBACK_CHUNKS, not from
            # top_k — so sweeping top_k alone measures nothing, which is how the
            # first run of this script produced an identical row seven times.
            # Both move together here: top_k is what the LLM path would see,
            # MAX_FALLBACK_CHUNKS is what the extractive text is made of.
            agent_module.MAX_FALLBACK_CHUNKS = budget
            index.clear()

            answered = 0
            reply_chars = 0
            per_tenant: dict[str, int] = defaultdict(int)
            for slug in seeders:
                for questions in QUESTIONS.values():
                    for question, expect in questions:
                        resp = client.post(
                            f"/chat/{slug}", json={"message": question}
                        )
                        resp.raise_for_status()
                        reply = resp.json()["reply"]
                        reply_chars += len(reply)
                        if any(term in reply.lower() for term in expect):
                            answered += 1
                            per_tenant[slug] += 1

            total = asked * len(seeders)
            coverage = 100 * answered / total
            per_answer = reply_chars / total
            rows.append((budget, answered, per_answer))
            if budget == 4:
                baseline = (answered, per_answer)
            delta = (
                f"{answered - baseline[0]:+d}" if baseline and budget != 4 else "—"
            )
            print(f"{budget:>6}{answered:>10}{coverage:>9.0f}%{per_answer:>14.0f}"
                  f"{delta:>9}")

    retrieval.retrieve = original

    if baseline:
        best = max(rows, key=lambda r: r[1])
        print(f"\n  best coverage at top_k={best[0]}: {best[1]} answered "
              f"({best[1] - baseline[0]:+d} vs k=4), "
              f"{best[2] / baseline[1]:.2f}x the reply text")
        print("  Read both columns. More answers for proportionally more text "
              "is\n  a cost decision, not a free win.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
