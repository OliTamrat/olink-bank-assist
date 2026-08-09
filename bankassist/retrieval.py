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

from sqlalchemy.orm import Session

from .models import Chunk, Document

_TOKEN = re.compile(r"\w+", re.UNICODE)

BM25_K1 = 1.5
BM25_B = 0.75

# Function words that must never count as "we found relevant knowledge".
# They still contribute to BM25 ranking; they just can't be the only match.
_STOPWORDS_EN = [
    "a", "an", "and", "are", "about", "at", "be", "by", "can", "do", "does",
    "for", "from", "how", "i", "in", "is", "it", "me", "my", "of", "on",
    "or", "our", "please", "tell", "that", "the", "this", "to", "we",
    "what", "when", "where", "which", "who", "why", "will", "with", "you",
    "your", "yes", "no", "not", "want", "wanted", "know", "need", "would",
    "could", "should", "there", "have", "has", "was", "were", "am",
    # "How much …" is the commonest way anyone asks about a price, and every
    # word of it was counting against the query. The min-informative bar
    # scales with content-word count, so untagged filler makes a question
    # *harder* to answer the more politely it is phrased: "How much is the
    # transfer fee to another bank?" needed 3 informative matches out of the
    # 2 real words it contains, and was refused. These carry no domain signal
    # in any of the five languages' worth of banking questions seen so far.
    "much", "many", "another", "get", "gets", "getting", "got", "if",
    "any", "just", "also", "than", "then", "so", "still", "even", "some",
]

# These lists exist because the stopword set was English-only, and that made
# the gate in retrieve() measurably harsher in every other language. The
# min-informative bar scales with a query's content-word count, so untagged
# function words inflate the denominator:
#
#   "I wanted to know about ATM"   -> 3 content words -> needs 1 match  (passes)
#   "ስለ ATM ማወቅ ፈልጌ ነበር"            -> 5 content words -> needs 3 matches (fails)
#
# Same question, same corpus, three times the burden of proof — on a product
# sold on native-language support. Found on the live Awash demo, where an
# Amharic ATM question handed off while a bare "ATM" answered fine.
#
# Conservative by design: only unambiguous function words (to-be forms,
# interrogatives, pronouns, postpositions, "about"/"want"/"know" verbs).
# Anything that could carry banking meaning is deliberately left out — a
# missing stopword only costs recall, a wrong one costs precision.
_STOPWORDS_AM = [
    "ስለ", "ነው", "ናቸው", "ነበር", "ናት", "ነኝ", "ነህ", "ነሽ", "እና", "ወይም",
    "ላይ", "ውስጥ", "ጋር", "ወደ", "ምን", "ምንድን", "ምንድነው", "እንዴት", "መቼ", "የት",
    "ማን", "ለምን", "የትኛው", "ይህ", "ያ", "እኔ", "እኛ", "አንተ", "አንቺ", "እርስዎ",
    "እባክዎ", "እባክህ", "እባክሽ", "አዎ", "ግን", "ደግሞ", "እንደ", "ማወቅ", "ፈልጌ",
    "እፈልጋለሁ", "ነገር", "አለ", "ይችላል", "እችላለሁ", "ማድረግ", "ብዬ", "ነኝ",
]
_STOPWORDS_OM = [
    "waa'ee", "waee", "waa", "ee", "akkam", "maal", "maali", "eessa", "yoom", "eenyu",
    "maaliif", "kana", "sana", "kan", "ani", "ati", "isin", "nu", "nuti",
    "fi", "ykn", "yookaan", "keessa", "irratti", "waliin", "gara", "irraa",
    "barbaada", "barbaade", "beekuu", "jira", "ture", "koo", "keessan",
    "isaa", "hin", "akka", "moo", "immoo", "garuu", "tokko", "maaloo",
]
_STOPWORDS_TI = [
    "ብዛዕባ", "እንታይ", "ከመይ", "መዓስ", "ኣበይ", "መን", "ስለምንታይ", "እዚ", "እቲ",
    "ኣነ", "ንሕና", "ንስኻ", "ንስኺ", "ንስኻትኩም", "እዩ", "እያ", "እዮም", "ነይሩ",
    "ግን", "ከምኡ", "ክፈልጥ", "እደሊ", "ምስ", "ኣብ", "ናብ", "ካብ", "ወይ", "እሞ",
]
_STOPWORDS_SO = [
    "saabsan", "maxay", "maxaa", "sidee", "goorma", "xagee", "yaa",
    "kan", "taas", "kani", "aniga", "adiga", "annaga", "iyaga",
    "iyo", "ama", "gudaha", "dul", "ku", "ka", "la", "ah", "waa",
    "ayaa", "oo", "in", "doonayaa", "rabaa", "ogaan", "waxaan", "waxa",
    "fadlan", "haa", "maya",
]

_STOPWORDS = frozenset(
    _STOPWORDS_EN + _STOPWORDS_AM + _STOPWORDS_OM + _STOPWORDS_TI + _STOPWORDS_SO
)


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN.findall(text)]


def content_signature(text: str, max_words: int = 8) -> str:
    """A grouping key built from a message's informative words.

    Used to collapse the same question asked in different words — "How do I
    use an ATM?", "how to use ATM", "ATM how to use" all reduce to "atm use".
    Reuses the retrieval stopword list rather than a second one, so a word
    that carries no signal for search carries none for grouping either.

    Deliberately word-order-independent and capped: a long rambling message
    should still group with the short version of the same question.
    """
    words = sorted({tok for tok in tokenize(text) if tok not in _STOPWORDS})
    return " ".join(words[:max_words])


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


@dataclass(frozen=True)
class Suggestion:
    """A topic the customer may have meant. Always a real document title from
    this bank's own knowledge base — never generated text, so offering one
    can't invent a product or a figure that doesn't exist."""

    document_id: str
    title: str


# Query-side vocabulary bridges.
#
# Customers ask in everyday words; the knowledge base is written in the bank's
# own. Someone asks what they are "charged" and the document says "fees"; they
# ask about "sending" money and it says "transfer". BM25 matches exact tokens,
# so those are misses — and the miss is silent in the worst way: suggest_topics
# still ranks the right document first and offers it as a chip, so the system
# demonstrably knew which document answered the question and declined to read
# it. "How much do I get charged if I sent from other banks" was reported from
# the live Awash demo; the answer was sitting in "Transfers to Other Banks and
# Wallets" the whole time.
#
# Applied to the QUERY ONLY, never to the corpus. A document has to keep saying
# exactly what the bank wrote — widening what a question may match cannot
# change what an answer says.
#
# Each group counts as ONE term for the informativeness gate (see
# _score_corpus). That is the property that makes this safe rather than a
# loosening: expansion helps a question find the right document, it does not
# lower the bar for deciding something was found. Handing a query more words
# can never, by itself, promote a weak match past the gate.
#
# Curated rather than stemmed. A stemmer would have to be right in five
# languages including two Ge'ez-script ones; a short list of banking words is
# auditable, and it cannot mangle a script it was never written for. Groups
# carry their own plurals and inflections for the same reason.
_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({
        "fee", "fees", "charge", "charges", "charged", "charging",
        "cost", "costs", "tariff", "tariffs", "commission", "commissions",
    }),
    frozenset({
        "transfer", "transfers", "transferred", "transferring",
        "send", "sending", "sent", "remit", "remittance", "remittances",
    }),
    frozenset({"withdraw", "withdraws", "withdrawal", "withdrawals"}),
    frozenset({"deposit", "deposits", "depositing", "deposited"}),
    frozenset({"loan", "loans", "borrow", "borrowing", "credit"}),
    frozenset({"interest", "rate", "rates"}),
    frozenset({"requirement", "requirements", "require", "requires", "required"}),
    frozenset({"document", "documents", "documentation", "paperwork"}),
    frozenset({"open", "opens", "opening", "apply", "applying", "application"}),
    frozenset({"branch", "branches", "office", "offices"}),
)

_FORM_TO_GROUP: dict[str, tuple[str, ...]] = {
    form: tuple(sorted(group)) for group in _SYNONYM_GROUPS for form in group
}


def expand_query(tokens: list[str]) -> list[tuple[str, ...]]:
    """One group per query token, in order.

    Emitting exactly one group per token — never more — is what keeps the
    informativeness gate's arithmetic identical to the unexpanded version.
    A token with no group becomes a group of one, so a corpus and a query
    that share no listed vocabulary behave exactly as they did before.
    """
    return [_FORM_TO_GROUP.get(tok, (tok,)) for tok in tokens]


@dataclass(frozen=True)
class CorpusStats:
    """Everything BM25 needs about the corpus rather than about the query.

    Split out so it can be computed once and reused across queries. Nothing
    here depends on what was asked, and recomputing it per message is what
    made retrieval cost grow with the size of the knowledge base — see
    `index.py`.
    """

    n: int
    df: Counter[str]
    avg_len: float
    informative_df_ceiling: int


def corpus_stats(corpus: list[tuple[str, list[str]]]) -> CorpusStats:
    n = len(corpus)
    df: Counter[str] = Counter()
    for _, tokens in corpus:
        for term in set(tokens):
            df[term] += 1
    avg_len = sum(len(tokens) for _, tokens in corpus) / n if n else 0.0
    return CorpusStats(
        n=n, df=df, avg_len=avg_len,
        informative_df_ceiling=max(1, (n + 1) // 2 - 1),
    )


def _score_corpus(
    corpus: list[tuple[str, list[str]]],
    query_groups: list[tuple[str, ...]],
    stats: CorpusStats | None = None,
) -> list[tuple[str, float, int]]:
    """Return (chunk_id, bm25_score, informative_matches) for every chunk.

    A group scores through its single best-matching member rather than the sum
    of them, so a chunk saying both "fee" and "charge" does not out-rank one
    saying "fee" twice on the strength of the synonym list.

    `stats` MUST describe the whole corpus, not the subset in `corpus`. The
    index passes only the chunks that contain a query term — scoring the rest
    is arithmetic to reach zero — and BM25's idf would change meaning if the
    document frequencies were recounted over that subset.
    """
    if not corpus or not query_groups:
        return []
    if stats is None:
        stats = corpus_stats(corpus)
    n = stats.n
    if n == 0:
        return []
    df = stats.df
    avg_len = stats.avg_len
    # A stopword, or a term sitting in at least half the corpus, carries no
    # signal; it must not count toward "we actually found something". This
    # is ceil(n/2) - 1, floored at 1: strictly *below* half (not "at most
    # half" — a term in exactly half the corpus is exactly as generic as
    # one in 60% of it, and "<=" let a bank's own name ("bank", present in
    # precisely half of one bank's chunks) slip through as informative).
    # The floor of 1 preserves retrievability for tiny corpora — for a
    # single-chunk corpus this still allows df=1 to count.
    informative_df_ceiling = stats.informative_df_ceiling

    results: list[tuple[str, float, int]] = []
    for chunk_id, tokens in corpus:
        tf = Counter(tokens)
        score = 0.0
        informative = 0
        for group in query_groups:
            best_score = 0.0
            best_informative = False
            for term in group:
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                term_df = df[term]
                idf = math.log((n - term_df + 0.5) / (term_df + 0.5) + 1)
                denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * len(tokens) / avg_len)
                term_score = idf * freq * (BM25_K1 + 1) / denom
                if term_score > best_score:
                    best_score = term_score
                    best_informative = (
                        term not in _STOPWORDS and term_df <= informative_df_ceiling
                    )
            score += best_score
            if best_informative:
                informative += 1
        results.append((chunk_id, score, informative))
    return results


MIN_INFORMATIVE_RATIO = 0.5
SHORT_QUERY_CONTENT_WORDS = 3
"""A chunk only counts as "found" if a real fraction of the query's own
content words show up as non-generic matches in it — not just any single
incidental overlap. Without this, a question like "Are you officially
endorsed by CBE?" matches on one or two weak, unrelated terms and returns
an irrelevant document instead of the honest "I don't know" — a
wrong-looking answer erodes trust as much as a wrong one.

The ratio only applies once a query has more than SHORT_QUERY_CONTENT_WORDS
content words. Below that, a single informative match is enough. This is a
deliberate, tested asymmetry, not an oversight: false-positive risk (an
irrelevant chunk sneaking past the gate) grows with query length, because
longer queries have more surface area for coincidental overlap — that's
exactly the adversarial pattern this gate defends against, and every
adversarial case found in practice was 5+ content words. A short, specific
query like "How do I open a diaspora account?" (3 content words: open,
diaspora, account) has essentially no room for that kind of accident — if
"diaspora" matches at all, it's matching the right document. Provably no
single ratio can satisfy both constraints at once (the short diaspora query
needs ratio <= 1/3 to pass; the adversarial cases need ratio > 0.4 to be
rejected) — see tests/test_cbe_adversarial.py for the cases that pinned
this down."""


def retrieve(db: Session, bank_id: str, query: str, top_k: int = 4) -> list[RetrievedChunk]:
    """Top-k chunks for this bank only. Empty list means: we do not know."""
    from . import index as index_module

    idx = index_module.get(db, bank_id)
    if not idx.corpus:
        return []

    query_tokens = tokenize(query)
    content_tokens = [t for t in query_tokens if t not in _STOPWORDS]
    if not content_tokens:
        min_informative = 0
    elif len(content_tokens) <= SHORT_QUERY_CONTENT_WORDS:
        min_informative = 1
    else:
        min_informative = math.ceil(len(content_tokens) * MIN_INFORMATIVE_RATIO)
    # min_informative is counted from the customer's own words, before
    # expansion — synonyms widen what each word may match, they never change
    # how many matches are required.
    # Only the chunks that share a term with the query. The rest score exactly
    # zero and are dropped by the filter below either way, so this is a
    # narrowing of the work, not of the result.
    groups = expand_query(query_tokens)
    scored = _score_corpus(idx.candidates(groups), groups, idx.stats)

    hits = sorted(
        (item for item in scored if item[1] > 0 and item[2] >= max(1, min_informative)),
        key=lambda item: item[1],
        reverse=True,
    )[:top_k]

    results = []
    for chunk_id, score, _ in hits:
        payload = idx.payloads[chunk_id]
        results.append(
            RetrievedChunk(
                chunk_id=payload.chunk_id,
                document_id=payload.document_id,
                title=payload.title,
                text=payload.text,
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


def suggest_topics(
    db: Session, bank_id: str, query: str, limit: int = 3
) -> list[Suggestion]:
    """Topics to offer when `retrieve()` found nothing confident enough.

    The informativeness gate in `retrieve()` is what stops the assistant
    answering confidently from a weak, incidental match — it must not be
    loosened, because a plausible-looking wrong answer costs a bank deal.
    But failing that gate should not be *fatal*: the chunks that scored
    above zero and merely failed the gate are precisely the near misses a
    person would recognise as "yes, that one".

    So this returns the near misses' **document titles** rather than their
    text. Offering a real title is navigation, not guessing — it can never
    fabricate a product, rate or requirement, so the safety doctrine holds
    while a rephrase stops being a dead end.

    When nothing scores at all (gibberish, or a topic genuinely absent),
    falls back to the bank's broadest documents so the customer still gets
    a way forward instead of a closed door.

    Re-scores rather than sharing a result set with `retrieve()`, but over the
    same cached index: this only runs on the miss path, and keeping
    `retrieve()`'s signature untouched is worth more than threading state
    between them.
    """
    from . import index as index_module

    idx = index_module.get(db, bank_id)
    if not idx.corpus:
        return []

    groups = expand_query(tokenize(query))
    scored = _score_corpus(idx.candidates(groups), groups, idx.stats)

    # Best score per document, so one long document can't fill every slot.
    best: dict[str, tuple[float, str]] = {}
    for chunk_id, score, _informative in scored:
        if score <= 0:
            continue
        payload = idx.payloads[chunk_id]
        if score > best.get(payload.document_id, (0.0, ""))[0]:
            best[payload.document_id] = (score, payload.title)

    if best:
        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
        return [Suggestion(doc_id, title) for doc_id, (_s, title) in ranked[:limit]]

    # Nothing matched at all. Offer the documents with the most chunks — the
    # broadest topics this bank actually covers — as a stable starting point.
    breadth: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for payload in idx.payloads.values():
        breadth[payload.document_id] += 1
        titles[payload.document_id] = payload.title
    widest = sorted(breadth.items(), key=lambda kv: (-kv[1], titles[kv[0]]))
    return [Suggestion(doc_id, titles[doc_id]) for doc_id, _n in widest[:limit]]
