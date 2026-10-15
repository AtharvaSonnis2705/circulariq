from pathlib import Path

import pytest

from circulariq.ingest.parse import (
    Line,
    _plausible_next,
    build_blocks,
    embedding_text,
    extract_ref_no,
    pack_chunks,
    parse_pdf,
)


def lines(*texts: str, page: int = 1) -> list[Line]:
    return [Line(page, t) for t in texts]


def test_paragraph_numbers_must_follow_sequence() -> None:
    assert _plausible_next(None, (1,))
    assert _plausible_next((3, 1), (3, 2))
    assert _plausible_next((3, 1), (3, 1, 1))
    assert _plausible_next((3, 1, 2), (4,))
    assert _plausible_next((2,), (1,))  # restart in a new chapter/annex
    assert not _plausible_next((3, 1), (7, 4))  # e.g. "7.4 per cent" mid-text
    assert not _plausible_next(None, (15,))


def test_blocks_track_chapter_heading_and_numbering() -> None:
    blocks = build_blocks(
        lines(
            "Chapter I: Terms of Registration",
            "1. Online registration mechanism:",
            "1.1. All applications shall be filed online.",
            "a) the applicant shall upload documents;",
            "b) fees shall be paid electronically.",
            "1.2. The portal is available at all times.",
            "Chapter II: Due Diligence",
            "1. Appointment of Debenture Trustee:",
            "1.1. The issuer shall appoint a trustee before 2026 ends.",
        )
    )
    numbers = [(b.chapter.split(":")[0], b.number) for b in blocks]
    assert numbers == [
        ("Chapter I", "1"),
        ("Chapter I", "1.1"),
        ("Chapter I", "1.2"),
        ("Chapter II", "1"),
        ("Chapter II", "1.1"),
    ]
    assert blocks[1].heading == "Online registration mechanism"
    assert blocks[4].heading == "Appointment of Debenture Trustee"
    # Lettered sub-items stay inside their paragraph, each on its own line.
    assert blocks[1].text.splitlines()[1].startswith("a) the applicant")


def test_chapter_title_on_next_line_and_annex_title() -> None:
    blocks = build_blocks(
        lines(
            "CHAPTER - III",
            "MONITORING AND REPORTING",
            "1. Trustees shall report quarterly.",
            "Annex-IIIA",
            "Format of quarterly report",
            "Name of the trustee and registration number go here.",
        )
    )
    assert blocks[0].chapter == "Chapter III: MONITORING AND REPORTING"
    assert blocks[1].annex == "Annex IIIA: Format of quarterly report"
    assert blocks[1].number is None


def test_chunks_never_cross_chapters_and_carry_citations() -> None:
    body = " ".join(["word"] * 30)
    blocks = build_blocks(
        [
            Line(5, "Chapter I: Registration"),
            Line(5, f"1. {body}"),
            Line(6, f"2. {body}"),
            Line(7, "Chapter II: Due Diligence"),
            Line(7, f"1. {body}"),
        ]
    )
    chunks = pack_chunks(blocks, target=350)
    assert [c.section for c in chunks] == ["Chapter I › Paras 1–2", "Chapter II › Para 1"]
    assert (chunks[0].page_start, chunks[0].page_end) == (5, 6)
    assert chunks[1].chapter == "Chapter II: Due Diligence"


def test_long_paragraph_is_split_with_contd_marker() -> None:
    sentence = "The trustee shall verify every security interest created. "
    blocks = build_blocks(lines(f"1. {sentence * 120}"))
    chunks = pack_chunks(blocks, target=200, max_words=300)
    assert len(chunks) > 1
    assert all(c.word_count <= 260 for c in chunks)
    assert chunks[1].content.startswith("(contd.)")
    assert {c.section for c in chunks} == {"Cover letter › Para 1"}


def test_extract_ref_no() -> None:
    assert (
        extract_ref_no(lines("MASTER CIRCULAR", "HO/17/11/12(2)2026-DDHS-POD1/I/22420/2026"))
        == "HO/17/11/12(2)2026-DDHS-POD1/I/22420/2026"
    )
    assert extract_ref_no(lines("Circular No. SEBI/HO/MRD/POD-1/P/CIR/2025/12 dated")) == (
        "SEBI/HO/MRD/POD-1/P/CIR/2025/12"
    )


def test_embedding_text_includes_context() -> None:
    blocks = build_blocks(
        lines("Chapter V: Security Cover", "1. Cover certificate:", "1.1. " + "x " * 20)
    )
    chunk = pack_chunks(blocks)[0]
    text = embedding_text("Master Circular for Debenture Trustees", chunk)
    assert text.startswith(
        "Master Circular for Debenture Trustees | Chapter V: Security Cover | Cover certificate"
    )


SAMPLE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="no sample PDF fixture")
def test_real_pdf_smoke() -> None:
    doc = parse_pdf(SAMPLE_PDF)
    assert doc.chunks
    assert all(c.page_start <= c.page_end for c in doc.chunks)


def test_chapter_prefixed_numbering_is_detected() -> None:
    blocks = build_blocks(
        lines(
            "Chapter 11: Fees and Expenses",
            "11.1. Limits on fees and expenses charged to schemes:",
            "11.1.1. AMC may charge certain expenses to a scheme.",
            "11.1.2. The total expense ratio shall not exceed the limits below.",
            "11.2. Additional expenses:",
            "11.2.1. An additional 5 bps may be charged.",
        )
    )
    assert [b.number for b in blocks] == ["11.1", "11.1.1", "11.1.2", "11.2", "11.2.1"]
    assert blocks[2].heading == "Limits on fees and expenses charged to schemes"
    assert blocks[4].heading == "Additional expenses"
    chunk = pack_chunks(blocks)[0]
    assert chunk.section == "Chapter 11 › Paras 11.1–11.2.1"


def test_roman_chapter_numbers() -> None:
    from circulariq.ingest.parse import _chapter_number

    assert [_chapter_number(x) for x in ("I", "IV", "IX", "XIV", "XVII", "11")] == [
        1,
        4,
        9,
        14,
        17,
        11,
    ]
