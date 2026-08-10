"""A per-tenant search index, built once and reused until the content changes.

Retrieval used to pull every chunk this bank owns out of the database, tokenize
all of it, and recount document frequencies — on every customer message. At the
MVP corpus of fifteen articles that is 1.7ms and invisible. Measured against a
realistic knowledge base it is not:

    24 chunks      1.7 ms/query
    364 chunks    19.9 ms/query
    1964 chunks  118.5 ms/query

Perfectly linear, and that is SQLite on local disk. In production the same
query drags roughly a megabyte of chunk rows across the network from Supabase
before any scoring happens. The consequence is the awkward one: **the assistant
would get slower in exact proportion to how useful it became**, and the whole
plan for making it useful is to load each bank's real published material.

So the corpus-shaped work happens once per version of the content:

- tokenizing every chunk
- counting document frequencies and the average length
- the informative-df ceiling derived from both

and a query then scores only the chunks that contain one of its terms. Chunks
sharing no term with the query score exactly zero, and both callers already
discard zero-scoring chunks, so skipping them is not an approximation — the
output is identical, which `tests/test_retrieval_index.py` asserts directly
against the unindexed implementation.

Measured again at 1,964 chunks, the same benchmark:

    118.5 ms  before
     15.0 ms  after, worst case — a corpus where every article reuses the same
              small vocabulary, so three quarters of it is a candidate anyway
      6.9 ms  after, with articles that are about different things, which is
              what a real bank's material looks like

Most of what remains is the query's own function words: "how", "do", "i" sit
in nearly every chunk, so they pull nearly every chunk into the candidate set.
They cannot simply be dropped — they carry a small BM25 score, and a chunk
that scores at all is one `suggest_topics` may legitimately offer as a near
miss. Narrowing further would change what the assistant says, which is not
what a performance change is allowed to do.

**What this deliberately does not do is change any arithmetic.** Scoring still
runs through `retrieval._score_corpus`, unchanged, with the same corpus
statistics it would have computed for itself. A faster retriever that ranked
differently would be a new product decision wearing a performance change, and
the ranking here is load-bearing: the informativeness gate is what stops the
assistant answering confidently from a weak match.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Chunk, Document
from .retrieval import CorpusStats, corpus_stats, tokenize

# How many tenants' indexes one process keeps. Small on purpose: a Cloud Run
# instance serves whichever banks happen to route to it, and an unbounded cache
# is a memory leak with a slow fuse. Evicting the least recently used tenant
# costs that tenant one rebuild.
MAX_TENANTS = 8


@dataclass(frozen=True)
class Payload:
    """What a hit needs to become an answer, without going back to the DB."""

    chunk_id: str
    document_id: str
    title: str
    text: str


@dataclass(frozen=True)
class Index:
    """One tenant's corpus, tokenized and counted.

    Frozen, and every field is finished before it is published to the cache.
    Readers therefore need no lock: a request either sees the whole old index
    or the whole new one, never a half-built one.
    """

    version: tuple[int, int, str]
    corpus: list[tuple[str, list[str]]]
    stats: CorpusStats
    payloads: dict[str, Payload]
    # term -> the POSITIONS in `corpus` of the chunks containing it. Positions
    # rather than ids so a query can jump straight to its candidates; holding
    # ids would mean a scan of the whole corpus to filter, which is the cost
    # this module exists to remove and would have quietly survived the
    # rewrite — the first version of it did.
    by_term: dict[str, list[int]] = field(default_factory=dict)

    def candidates(self, query_groups: list[tuple[str, ...]]) -> list[tuple[str, list[str]]]:
        """The chunks worth scoring for this query, in stable corpus order.

        Order matters even though the caller sorts by score: equal scores fall
        back to list order, and a set-ordered candidate list would depend on
        string hashing — which Python randomises per process — so two Cloud
        Run instances would rank identical content differently.
        """
        wanted: set[int] = set()
        for group in query_groups:
            for term in group:
                wanted.update(self.by_term.get(term, ()))
        if not wanted:
            return []
        return [self.corpus[i] for i in sorted(wanted)]


def _version(db: Session, bank_id: str) -> tuple[int, int, str]:
    """A cheap stamp that changes whenever this bank's content changes.

    Three parts, because one is not enough:

    - chunk count catches a document added, deleted, or re-chunked;
    - document count catches an empty document added or removed, which can
      leave the chunk count untouched;
    - the latest `updated_at` catches an edit that happens to produce exactly
      as many chunks as before — the commonest edit there is, a typo fix.

    One aggregate query per message, against indexed columns, instead of the
    whole corpus. That is the trade this module exists to make.
    """
    row = db.execute(
        select(
            func.count(Chunk.id),
            select(func.count(Document.id))
            .where(Document.bank_id == bank_id)
            .scalar_subquery(),
            select(func.max(Document.updated_at))
            .where(Document.bank_id == bank_id)
            .scalar_subquery(),
        ).where(Chunk.bank_id == bank_id)
    ).one()
    chunks, documents, latest = row
    return int(chunks or 0), int(documents or 0), str(latest or "")


def _build(db: Session, bank_id: str, version: tuple[int, int, str]) -> Index:
    rows = db.execute(
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.bank_id == bank_id)
        .order_by(Chunk.document_id, Chunk.seq)
    ).all()
    corpus: list[tuple[str, list[str]]] = []
    payloads: dict[str, Payload] = {}
    by_term: defaultdict[str, list[int]] = defaultdict(list)
    for position, (chunk, title) in enumerate(rows):
        tokens = tokenize(chunk.text)
        corpus.append((chunk.id, tokens))
        payloads[chunk.id] = Payload(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            title=title,
            text=chunk.text,
        )
        for term in set(tokens):
            by_term[term].append(position)
    return Index(
        version=version,
        corpus=corpus,
        stats=corpus_stats(corpus),
        payloads=payloads,
        by_term=dict(by_term),
    )


# Guards the dict itself, never the scoring. Held only for the microseconds it
# takes to read or replace a reference, so a slow rebuild never blocks another
# tenant's request — two requests racing to rebuild the same tenant both
# succeed and the last one published wins, which is correct because they build
# from the same version.
_lock = threading.Lock()
_cache: dict[str, Index] = {}
_order: list[str] = []


def get(db: Session, bank_id: str) -> Index:
    """This bank's index, rebuilt if its content has changed since last time."""
    version = _version(db, bank_id)
    with _lock:
        cached = _cache.get(bank_id)
        if cached is not None and cached.version == version:
            _touch(bank_id)
            return cached
    built = _build(db, bank_id, version)
    with _lock:
        _cache[bank_id] = built
        _touch(bank_id)
        while len(_order) > MAX_TENANTS:
            _cache.pop(_order.pop(0), None)
    return built


def _touch(bank_id: str) -> None:
    """Move a tenant to the most-recently-used end. Caller holds the lock."""
    if bank_id in _order:
        _order.remove(bank_id)
    _order.append(bank_id)


def clear() -> None:
    """Drop every cached index.

    For tests, which build a fresh database per test and would otherwise see
    another test's tenant under the same id. Production never needs it: the
    version stamp is what keeps an index honest, not manual invalidation.
    """
    with _lock:
        _cache.clear()
        _order.clear()
