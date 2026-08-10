"""The index must be a speed change and nothing else.

Retrieval used to tokenize the whole corpus and recount document frequencies
on every customer message. Benchmarked, that is 1.7ms at the seeded corpus of
fifteen articles and 118ms at five hundred — perfectly linear, on local SQLite,
before the network cost of dragging every chunk row out of Supabase. The
assistant would have got slower in exact proportion to how useful it became,
and the plan for making it useful is to load each bank's real published
material.

Caching the corpus-shaped work is easy. Doing it without moving a single
ranking is the part that needs proving, because the ranking is load-bearing:
the informativeness gate is what stops the assistant answering confidently
from a weak match, and it is computed from corpus statistics. So the first
test here is a differential one against the unindexed implementation, and it
is the reason to trust the rest.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import index as index_module
from bankassist.models import Bank, Document
from bankassist.retrieval import (
    _score_corpus,
    corpus_stats,
    expand_query,
    reindex_document,
    retrieve,
    suggest_topics,
    tokenize,
)

QUERIES = [
    "How do I open a savings account?",
    "What is the daily ATM withdrawal limit?",
    "How do I block my lost card?",
    "Do you offer diaspora accounts?",
    "mobile banking activation",
    "transfer money to telebirr",
    "የቁጠባ ሂሳብ እንዴት እከፍታለሁ",
    "interest rate on a fixed deposit",
    "something entirely unrelated to banking like gardening",
    "fee",
    "",
]


def _unindexed(db: Any, bank_id: str, query: str, top_k: int = 4) -> list[Any]:
    """Retrieval exactly as it was before the index: every chunk, every time.

    Deliberately a copy rather than a call into the old code — the point is to
    have an independent implementation to disagree with.
    """
    import math

    from bankassist.models import Chunk
    from bankassist.retrieval import (
        _STOPWORDS,
        MIN_INFORMATIVE_RATIO,
        SHORT_QUERY_CONTENT_WORDS,
    )

    rows = db.execute(
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.bank_id == bank_id)
    ).all()
    if not rows:
        return []
    corpus = [(chunk.id, tokenize(chunk.text)) for chunk, _ in rows]
    query_tokens = tokenize(query)
    content = [t for t in query_tokens if t not in _STOPWORDS]
    if not content:
        min_informative = 0
    elif len(content) <= SHORT_QUERY_CONTENT_WORDS:
        min_informative = 1
    else:
        min_informative = math.ceil(len(content) * MIN_INFORMATIVE_RATIO)
    scored = _score_corpus(corpus, expand_query(query_tokens))
    hits = sorted(
        (i for i in scored if i[1] > 0 and i[2] >= max(1, min_informative)),
        key=lambda i: i[1],
        reverse=True,
    )[:top_k]
    return [(cid, round(score, 4)) for cid, score, _ in hits]


@pytest.mark.parametrize("query", QUERIES)
def test_the_index_returns_exactly_what_the_full_scan_returned(
    client: TestClient, demo_bank: Any, db_session: Any, query: str
) -> None:
    """The whole justification. Same chunks, same order, same scores."""
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    indexed = [(c.chunk_id, c.score) for c in retrieve(db_session, bank_id, query)]
    assert indexed == _unindexed(db_session, bank_id, query), query


def test_document_frequencies_come_from_the_whole_corpus_not_the_candidates(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The subtle way this optimisation goes wrong.

    Only the chunks sharing a term with the query are scored — the rest reach
    zero by arithmetic and are discarded anyway. But BM25's idf is a statement
    about how rare a term is ACROSS THE CORPUS, and recounting it over the
    handful of candidates inverts its meaning: a term present in every
    candidate looks generic, when the reason it is in every candidate is that
    it is the rare term that selected them.

    Asserted numerically rather than by reading the code: scoring the same
    candidates with candidate-derived statistics must produce a different
    answer, or this test is proving nothing.
    """
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    idx = index_module.get(db_session, bank_id)
    groups = expand_query(tokenize("diaspora account"))
    candidates = idx.candidates(groups)
    assert candidates, "precondition: the query has to match something"

    right = _score_corpus(candidates, groups, idx.stats)
    wrong = _score_corpus(candidates, groups, corpus_stats(candidates))
    assert right != wrong, (
        "if these agree the test cannot detect the bug it exists for"
    )

    # Scoring the candidates with corpus-wide statistics gives the same
    # numbers as scoring the entire corpus and discarding the zeros — which
    # is the equality that makes the narrowing safe rather than merely fast.
    full = [(c, s, i) for c, s, i in _score_corpus(idx.corpus, groups, idx.stats) if s > 0]
    assert sorted(right) == sorted([(c, s, i) for c, s, i in right if s > 0])
    assert sorted(x for x in right if x[1] > 0) == sorted(full)


# ----------------------------------------------------------- staying current


def _ask(db: Any, bank_id: str, query: str) -> str:
    hits = retrieve(db, bank_id, query)
    return " ".join(h.text for h in hits)


def test_an_edited_document_is_searchable_immediately(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A cache that serves yesterday's article is worse than no cache. An
    operator who corrects a fee and watches the assistant keep quoting the old
    one stops trusting the panel."""
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    assert "quetzalcoatl" not in _ask(db_session, bank_id, "quetzalcoatl").lower()

    doc = db_session.execute(
        select(Document).where(
            Document.bank_id == bank_id, Document.title == "Savings Accounts"
        )
    ).scalar_one()
    doc.content = doc.content + "\n\nOur mascot is a quetzalcoatl."
    db_session.flush()
    reindex_document(db_session, doc)
    db_session.commit()

    assert "quetzalcoatl" in _ask(db_session, bank_id, "quetzalcoatl").lower()


def test_a_new_document_is_searchable_immediately(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    retrieve(db_session, bank_id, "anything")  # warm the cache first

    doc = Document(
        bank_id=bank_id, title="Beekeeping Loans", category="loans", language="en",
        content="We offer a specialised loan for beekeeping cooperatives.",
    )
    db_session.add(doc)
    db_session.flush()
    reindex_document(db_session, doc)
    db_session.commit()

    assert "beekeeping" in _ask(db_session, bank_id, "beekeeping loan").lower()


def test_a_deleted_document_stops_being_searchable(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The direction that matters legally as well as practically: a bank that
    withdraws an article has withdrawn it."""
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    assert _ask(db_session, bank_id, "diaspora account")

    for doc in db_session.execute(
        select(Document).where(
            Document.bank_id == bank_id, Document.title.like("%Diaspora%")
        )
    ).scalars().all():
        db_session.delete(doc)
    db_session.commit()

    assert "diaspora" not in _ask(db_session, bank_id, "diaspora account").lower()


def test_two_tenants_never_share_an_index(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any
) -> None:
    """The cache is keyed by bank id, and a bug here would be the worst kind
    this product can have — one bank's material answering another bank's
    customer. Asserted on content, not on cache internals."""
    demo_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    cbe_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "cbe")
    ).scalar_one()

    doc = Document(
        bank_id=demo_id, title="Demo Only Product", category="general",
        language="en", content="The demo-only zeppelin financing facility.",
    )
    db_session.add(doc)
    db_session.flush()
    reindex_document(db_session, doc)
    db_session.commit()

    assert "zeppelin" in _ask(db_session, demo_id, "zeppelin financing").lower()
    assert "zeppelin" not in _ask(db_session, cbe_id, "zeppelin financing").lower()


def test_evicting_a_tenant_costs_a_rebuild_and_nothing_else(
    client: TestClient, demo_bank: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is bounded, so a busy instance evicts. Correctness must not
    depend on being cached — only speed."""
    monkeypatch.setattr(index_module, "MAX_TENANTS", 1)
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    before = [(c.chunk_id, c.score) for c in retrieve(db_session, bank_id, "savings")]

    index_module.get(db_session, "some-other-tenant-id")  # evicts demo
    after = [(c.chunk_id, c.score) for c in retrieve(db_session, bank_id, "savings")]
    assert before == after and before


def test_suggested_topics_survive_the_same_change(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """`suggest_topics` reads the same index. It runs only on the miss path,
    which is exactly where nobody would notice it going stale."""
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    assert suggest_topics(db_session, bank_id, "savings account")

    doc = Document(
        bank_id=bank_id, title="Ostrich Insurance", category="general",
        language="en", content="Cover for commercial ostrich farming.",
    )
    db_session.add(doc)
    db_session.flush()
    reindex_document(db_session, doc)
    db_session.commit()

    titles = [s.title for s in suggest_topics(db_session, bank_id, "ostrich farming")]
    assert "Ostrich Insurance" in titles


def test_the_cache_is_keyed_by_tenant_and_not_merely_disambiguated_by_version(
    client: TestClient, demo_bank: Any, cbe_bank: Any, db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worst bug this product could have, pinned properly.

    The obvious version of this test — ask two tenants for their own content —
    passes even with the cache keyed globally, because two banks almost never
    share a chunk count and the version check quietly rebuilds. That is real
    defence in depth, and it is also exactly why the test was worthless: it
    was passing on an accident rather than on the key.

    So the version stamps are forced to collide. What is left is the key
    itself, and nothing else, standing between one bank's customer and another
    bank's material.
    """
    monkeypatch.setattr(index_module, "_version", lambda db, bank_id: (0, 0, ""))
    index_module.clear()

    demo_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    cbe_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "cbe")
    ).scalar_one()

    demo_docs = {p.title for p in index_module.get(db_session, demo_id).payloads.values()}
    cbe_docs = {p.title for p in index_module.get(db_session, cbe_id).payloads.values()}
    assert demo_docs and cbe_docs
    assert "Why Choose CBE" in cbe_docs
    assert "Why Choose CBE" not in demo_docs
    # And back again — the second lookup must not have overwritten the first.
    assert {
        p.title for p in index_module.get(db_session, demo_id).payloads.values()
    } == demo_docs


def test_candidates_keep_corpus_order(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Ranking sorts by score, and equal scores fall back to list order. If
    candidates came out of a set, that fallback would depend on string hashing
    — which Python randomises per process — so two Cloud Run instances would
    rank identical content differently and a refresh would reshuffle the
    sources under an answer."""
    bank_id = db_session.execute(
        select(Bank.id).where(Bank.slug == "demo")
    ).scalar_one()
    idx = index_module.get(db_session, bank_id)
    groups = expand_query(tokenize("account savings transfer card loan"))
    candidates = [cid for cid, _ in idx.candidates(groups)]
    assert len(candidates) > 2, "precondition: needs several matching chunks"

    order = [cid for cid, _ in idx.corpus]
    assert candidates == [cid for cid in order if cid in set(candidates)]
