"""Lexical BM25 retrieval over the bank's knowledge base.

Deliberately dependency-free: works offline, works for Ge'ez-script text
(Ethiopic characters are word characters under Unicode \\w), and is fast at
MVP scale. Swappable for embedding search in Phase 2 without touching the
agent — `retrieve()` is the only entry point.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Chunk, Document

_TOKEN = re.compile(r"\w+", re.UNICODE)

BM25_K1 = 1.5
BM25_B = 0.75

# Function words that must never count as "we found relevant knowledge".
# They still contribute to BM25 ranking; they just can't be the only match.
_STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "about", "at", "be", "by", "can", "do", "does",
        "for", "from", "how", "i", "in", "is", "it", "me", "my", "of", "on",
        "or", "our", "please", "tell", "that", "the", "this", "to", "we",
        "what", "when", "where", "which", "who", "why", "will", "with", "you",
        "your", "yes", "no", "not",
    ]
)


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN.findall(text)]


def chunk_text(content: str, max_chars: int = 700) -> list[str]:
    """Split a document into retrieval chunks on paragraph boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    text: str
    score: float


def _score_corpus(
    corpus: list[tuple[str, list[str]]], query_tokens: list[str]
) -> list[tuple[str, float, int]]:
    """Return (chunk_id, bm25_score, informative_matches) for every chunk."""
    n = len(corpus)
    if n == 0 or not query_tokens:
        return []
    df: Counter[str] = Counter()
    for _, tokens in corpus:
        for term in set(tokens):
            df[term] += 1
    avg_len = sum(len(tokens) for _, tokens in corpus) / n

    results: list[tuple[str, float, int]] = []
    for chunk_id, tokens in corpus:
        tf = Counter(tokens)
        score = 0.0
        informative = 0
        for term in query_tokens:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            term_df = df[term]
            # A stopword, or a term appearing in more than half the corpus,
            # carries no signal; it must not count toward "we actually found
            # something". max(1, …) keeps a single-chunk corpus retrievable.
            if term not in _STOPWORDS and term_df <= max(1.0, n / 2):
                informative += 1
            idf = math.log((n - term_df + 0.5) / (term_df + 0.5) + 1)
            denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * len(tokens) / avg_len)
            score += idf * freq * (BM25_K1 + 1) / denom
        results.append((chunk_id, score, informative))
    return results


def retrieve(db: Session, bank_id: str, query: str, top_k: int = 4) -> list[RetrievedChunk]:
    """Top-k chunks for this bank only. Empty list means: we do not know."""
    rows = db.execute(
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.bank_id == bank_id)
    ).all()
    if not rows:
        return []

    by_id = {chunk.id: (chunk, title) for chunk, title in rows}
    corpus = [(chunk.id, tokenize(chunk.text)) for chunk, _ in rows]
    scored = _score_corpus(corpus, tokenize(query))

    hits = sorted(
        (item for item in scored if item[1] > 0 and item[2] >= 1),
        key=lambda item: item[1],
        reverse=True,
    )[:top_k]

    results = []
    for chunk_id, score, _ in hits:
        chunk, title = by_id[chunk_id]
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                title=title,
                text=chunk.text,
                score=round(score, 4),
            )
        )
    return results


def reindex_document(db: Session, document: Document) -> int:
    """Rebuild the chunks for a document after create/update. Returns chunk count."""
    for stale in list(document.chunks):
        db.delete(stale)
    db.flush()
    pieces = chunk_text(document.content)
    for seq, text in enumerate(pieces):
        db.add(
            Chunk(bank_id=document.bank_id, document_id=document.id, seq=seq, text=text)
        )
    return len(pieces)
