"""Turn a SEBI circular PDF into structure-aware chunks that can be cited precisely.

SEBI documents are organised as chapters ("Chapter III: Title"), numbered paragraphs ("3.", "3.1.")
with lettered sub-items ("a)"), and annexures ("Annex-IIA"). We split on those boundaries, never let
a chunk cross a chapter or annexure, and keep page numbers so the UI can open the PDF at the
cited paragraph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

PAGE_HEADER = re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.I)
TOC_LEADER = re.compile(r"\.{5,}\s*\d*\s*$")
CHAPTER = re.compile(r"^\s*chapter\s*[-–:]?\s*([ivxlc]+|\d{1,2})\b\s*(?:[:\-–.]\s*(.*))?$", re.I)
ANNEX = re.compile(r"^\s*(annex(?:ure)?)\s*[-–:]?\s*([a-z0-9]{0,8})\s*$", re.I)
PARA = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,4})\.\s+(\S.*)$")
PARA_NODOT = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){1,4})\s+(\S.*)$")
LIST_ITEM = re.compile(r"^\s*(?:\(?[a-z]{1,2}\)|\(?[ivx]{1,5}\)|[•▪●\-–])\s")
# Old style "SEBI/HO/MRD/POD-1/P/CIR/2025/12", new style "HO/17/11/12(2)2026-DDHS-POD1/I/22420/2026"
REF_NO = re.compile(r"((?:SEBI/)?HO/[\w\-()/.]*\d)")

TARGET_WORDS = 350
MAX_WORDS = 550
MIN_WORDS = 8


@dataclass
class Line:
    page: int
    text: str


@dataclass
class Block:
    number: str | None
    chapter: str | None
    annex: str | None
    heading: str | None
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        out = ""
        for line in self.lines:
            sep = "\n" if out and LIST_ITEM.match(line) else " "
            out = f"{out}{sep}{line}" if out else line
        return out.strip()


@dataclass
class Chunk:
    chunk_index: int
    section: str
    chapter: str | None
    heading: str | None
    page_start: int
    page_end: int
    content: str
    paras: list[str]

    @property
    def word_count(self) -> int:
        return len(self.content.split())


@dataclass
class ParsedDocument:
    page_count: int
    ref_no: str | None
    chunks: list[Chunk]


def extract_lines(pdf_path: Path) -> tuple[int, list[Line]]:
    """Text lines per page, without page headers, table-of-contents leaders or blank lines."""
    lines: list[Line] = []
    with pymupdf.open(pdf_path) as doc:
        for page_no, page in enumerate(doc, start=1):
            for raw in page.get_text().splitlines():
                text = re.sub(r"\s+", " ", raw).strip()
                if not text or PAGE_HEADER.match(text) or TOC_LEADER.search(text):
                    continue
                lines.append(Line(page_no, text))
        return doc.page_count, lines


def extract_ref_no(lines: list[Line]) -> str | None:
    for line in lines:
        if line.page > 2:
            break
        if m := REF_NO.search(line.text):
            return m.group(1)
    return None


def _as_tuple(number: str) -> tuple[int, ...]:
    return tuple(int(p) for p in number.split("."))


def _chapter_number(label: str) -> int | None:
    """ "III" → 3, "11" → 11."""
    if label.isdigit():
        return int(label)
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = 0
    for ch, nxt in zip(label, label[1:] + " ", strict=True):
        v = values.get(ch)
        if v is None:
            return None
        total += -v if values.get(nxt, 0) > v else v
    return total


def _plausible_next(
    prev: tuple[int, ...] | None, cand: tuple[int, ...], chapter_no: int | None = None
) -> bool:
    """Is `cand` a believable next paragraph number after `prev`?

    Rejects numbers that appear mid-text or in tables ("2.5 times", "15. ..." out of nowhere).
    Allows restarting at 1, descending one level (3.1 → 3.1.1), or stepping a level forward by
    one or two (3.1 → 3.2, 3.1 → 4).
    """
    if cand == (1,):
        return True
    # Some master circulars number paragraphs within each chapter: Chapter 11 → 11.1, 11.1.1…
    if prev is None and chapter_no is not None and cand in ((chapter_no,), (chapter_no, 1)):
        return True
    if prev is None:
        return len(cand) == 1 and cand[0] <= 3
    if cand == prev + (1,):
        return True
    for depth in range(len(prev)):
        for step in (1, 2):
            if cand == prev[:depth] + (prev[depth] + step,):
                return True
    return False


def _heading_from(rest: str) -> str | None:
    """Paragraph titles in SEBI documents are short and end with a colon."""
    rest = rest.strip()
    if rest.endswith(":") and len(rest.split()) <= 16:
        return rest.rstrip(":").strip()
    return None


def build_blocks(lines: list[Line]) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None
    chapter: str | None = None
    annex: str | None = None
    top_heading: str | None = None
    prev_num: tuple[int, ...] | None = None
    chapter_no: int | None = None
    pending_title: str | None = None  # "chapter" or "annex" waiting for its title line

    def close() -> None:
        nonlocal current
        if current is not None and current.lines:
            blocks.append(current)
        current = None

    for line in lines:
        text = line.text

        if pending_title is not None:
            kind, pending_title = pending_title, None
            if not PARA.match(text) and len(text) <= 160:
                if kind == "chapter":
                    chapter = f"{chapter}: {text.rstrip(':')}"
                else:
                    annex = f"{annex}: {text.rstrip(':')}"
                continue

        if m := CHAPTER.match(text):
            close()
            chapter = f"Chapter {m.group(1).upper()}"
            chapter_no = _chapter_number(m.group(1).upper())
            if title := (m.group(2) or "").strip():
                chapter = f"{chapter}: {title}"
            else:
                pending_title = "chapter"
            annex, top_heading, prev_num = None, None, None
            continue

        if m := ANNEX.match(text):
            close()
            annex = f"Annex {m.group(2).upper()}".strip()
            pending_title = "annex"
            top_heading, prev_num, chapter_no = None, None, None
            continue

        m = PARA.match(text) or PARA_NODOT.match(text)
        if m and _plausible_next(prev_num, _as_tuple(m.group(1)), chapter_no):
            close()
            number, rest = m.group(1), m.group(2)
            prev_num = _as_tuple(number)
            # A paragraph's title comes from its top level: "3." normally, "11.1." when the
            # chapter prefixes its numbering.
            top_level = 2 if chapter_no is not None and prev_num[0] == chapter_no else 1
            if len(prev_num) <= top_level:
                top_heading = _heading_from(rest) or (top_heading if len(prev_num) > 1 else None)
            current = Block(number, chapter, annex, top_heading, line.page, line.page, [text])
            continue

        if current is None:
            current = Block(None, chapter, annex, top_heading, line.page, line.page)
        current.lines.append(text)
        current.page_end = line.page

    close()
    return blocks


def _section_label(chapter: str | None, annex: str | None, paras: list[str]) -> str:
    parts: list[str] = []
    if annex:
        parts.append(annex.split(":")[0])
    elif chapter:
        parts.append(chapter.split(":")[0])
    if paras:
        parts.append(f"Para {paras[0]}" if len(paras) == 1 else f"Paras {paras[0]}–{paras[-1]}")
    if not (annex or chapter):
        parts.insert(0, "Cover letter")
    return " › ".join(parts)


def _split_long(text: str, target: int) -> list[str]:
    sentences = re.split(r"(?<=[.;:]) +", text)  # spaces only, so list-item newlines survive
    pieces: list[str] = []
    buf: list[str] = []
    for sentence in sentences:
        if buf and len(" ".join(buf + [sentence]).split()) > target:
            pieces.append(" ".join(buf))
            buf = []
        buf.append(sentence)
    if buf:
        pieces.append(" ".join(buf))
    # Tables and run-on text may have no sentence breaks at all; cap by words as a last resort.
    capped: list[str] = []
    for piece in pieces:
        words = piece.split(" ")
        capped.extend(" ".join(words[i : i + target]) for i in range(0, len(words), target))
    return capped


def pack_chunks(
    blocks: list[Block], target: int = TARGET_WORDS, max_words: int = MAX_WORDS
) -> list[Chunk]:
    """Greedily pack consecutive blocks into ~target-word chunks within one chapter/annex."""
    chunks: list[Chunk] = []
    buf: list[Block] = []

    def emit(content: str, group: list[Block]) -> None:
        if len(content.split()) < MIN_WORDS:
            return
        first = group[0]
        paras = [b.number for b in group if b.number]
        chunks.append(
            Chunk(
                chunk_index=len(chunks),
                section=_section_label(first.chapter, first.annex, paras),
                chapter=first.annex or first.chapter,
                heading=next((b.heading for b in group if b.heading), None),
                page_start=min(b.page_start for b in group),
                page_end=max(b.page_end for b in group),
                content=content,
                paras=paras,
            )
        )

    def flush() -> None:
        if buf:
            emit("\n\n".join(b.text for b in buf), list(buf))
            buf.clear()

    for block in blocks:
        if buf and (block.chapter, block.annex) != (buf[0].chapter, buf[0].annex):
            flush()
        words = len(block.text.split())
        if words > max_words:
            flush()
            for i, piece in enumerate(_split_long(block.text, target)):
                emit(piece if i == 0 else f"(contd.) {piece}", [block])
            continue
        if buf and sum(len(b.text.split()) for b in buf) + words > target:
            flush()
        buf.append(block)
    flush()
    return chunks


def parse_pdf(pdf_path: Path) -> ParsedDocument:
    page_count, lines = extract_lines(pdf_path)
    return ParsedDocument(page_count, extract_ref_no(lines), pack_chunks(build_blocks(lines)))


def embedding_text(doc_title: str, chunk: Chunk) -> str:
    """What we embed: the chunk plus its document/chapter/heading context, so that a chunk that
    says "the Debenture Trustee shall..." is still findable by the topic it sits under."""
    header = " | ".join(p for p in (doc_title, chunk.chapter, chunk.heading) if p)
    return f"{header}\n\n{chunk.content}"
