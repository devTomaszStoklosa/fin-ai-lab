from fin_ai_lab.filings_rag.ingest.chunking import chunk_text


def test_chunk_text_keeps_short_text_as_one_chunk() -> None:
    text = "Paragraph one.\n\nParagraph two."

    chunks = chunk_text(text, chunk_size=1000, overlap=50)

    assert chunks == [text]


def test_chunk_text_splits_on_paragraph_boundaries_when_over_size() -> None:
    paragraphs = [f"Paragraph {i} " + "x" * 40 for i in range(5)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, chunk_size=100, overlap=10)

    assert len(chunks) > 1
    assert all(len(c) <= 100 + 10 + 2 for c in chunks)  # overlap + separator slack


def test_chunk_text_overlap_carries_tail_of_previous_chunk() -> None:
    paragraphs = [f"Paragraph {i} " + "x" * 40 for i in range(4)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, chunk_size=80, overlap=20)

    assert len(chunks) >= 2
    tail_of_first = chunks[0][-20:]
    assert tail_of_first in chunks[1]


def test_chunk_text_hard_splits_a_single_oversized_paragraph() -> None:
    text = "x" * 3000

    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) == 3
    assert all(len(c) == 1000 for c in chunks)


def test_chunk_text_returns_empty_list_for_blank_input() -> None:
    assert chunk_text("   \n\n  ") == []
