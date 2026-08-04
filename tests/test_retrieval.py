from __future__ import annotations

from bankassist.retrieval import chunk_text, tokenize


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
