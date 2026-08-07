from __future__ import annotations

from bankassist.retrieval import _score_corpus, chunk_text, expand_query, tokenize


def test_tokenize_handles_ethiopic_script() -> None:
    tokens = tokenize("የቁጠባ ሂሳብ መክፈት እፈልጋለሁ")
    assert "ሂሳብ" in tokens
    assert len(tokens) == 4


def test_tokenize_lowercases_latin() -> None:
    assert tokenize("Fixed DEPOSIT Rates") == ["fixed", "deposit", "rates"]


def test_chunk_text_splits_on_paragraphs_and_packs() -> None:
    paras = [f"Paragraph {i} " + ("x" * 300) for i in range(4)]
    chunks = chunk_text("\n\n".join(paras), max_chars=700)
    assert len(chunks) == 2
    assert chunks[0].startswith("Paragraph 0")
    assert "Paragraph 3" in chunks[1]


def test_chunk_text_single_short_document() -> None:
    assert chunk_text("Just one paragraph.") == ["Just one paragraph."]


def test_informative_excludes_term_in_exactly_half_the_corpus() -> None:
    # Regression: found via the Awash tenant, where "bank" sat in exactly
    # 11 of 22 chunks and slipped past the old "<=" boundary as
    # "informative" — the only reason a query like "Is CBE Bank better?"
    # (whose other terms never appear anywhere in Awash's corpus) matched
    # any document at all. A term in precisely half the corpus is not a
    # meaningful signal.
    corpus = [(f"c{i}", ["bank", "unique" + str(i)]) for i in range(11)] + [
        (f"c{i}", ["other" + str(i)]) for i in range(11, 22)
    ]
    scored = _score_corpus(corpus, expand_query(["bank"]))
    assert all(informative == 0 for _, _, informative in scored)


def test_informative_includes_term_below_half_the_corpus() -> None:
    corpus = [(f"c{i}", ["rare", "filler" + str(i)]) for i in range(10)] + [
        (f"c{i}", ["other" + str(i)]) for i in range(10, 22)
    ]
    scored = _score_corpus(corpus, expand_query(["rare"]))
    hits = [chunk_id for chunk_id, _, informative in scored if informative > 0]
    assert len(hits) == 10


def test_a_synonym_group_counts_once_toward_the_gate() -> None:
    """The property that makes query expansion safe rather than a loosening.

    A chunk carrying every word in a group must not look like a chunk that
    matched every word of the question. If expansion could inflate the
    informative count, adding a synonym would quietly lower the bar for
    "we found something" across the whole corpus — the exact failure the
    min-informative gate exists to prevent.
    """
    corpus = [("hit", ["fee", "charge", "cost", "tariff"])] + [
        (f"c{i}", ["unrelated" + str(i)]) for i in range(21)
    ]
    scored = {
        chunk_id: informative
        for chunk_id, _, informative in _score_corpus(corpus, expand_query(["fee"]))
    }
    assert scored["hit"] == 1, "four synonyms of one query word are still one match"


def test_expansion_never_grows_the_number_of_query_terms() -> None:
    """One group per token, always — this is what keeps min_informative honest."""
    tokens = tokenize("How much am I charged to send money?")
    assert len(expand_query(tokens)) == len(tokens)


def test_an_unlisted_word_expands_to_itself() -> None:
    assert expand_query(["diaspora"]) == [("diaspora",)]
