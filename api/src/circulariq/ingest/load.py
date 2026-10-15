"""Embed parsed chunks and write documents + chunks to Postgres (idempotent, re-runnable)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import numpy as np
import psycopg

from circulariq.embed import Embedder
from circulariq.ingest.parse import embedding_text, parse_pdf
from circulariq.ingest.sources import ManifestEntry


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ingest_document(
    conn: psycopg.Connection,
    entry: ManifestEntry,
    data_dir: Path,
    embedder: Embedder,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> bool:
    """Parse, embed and store one document. Returns False if it was already up to date."""
    row = conn.execute(
        "SELECT d.pdf_sha256, count(c.id) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
        "WHERE d.page_url = %s GROUP BY d.id",
        (entry.page_url,),
    ).fetchone()
    if row and row[0] == entry.sha256 and row[1] > 0 and not force:
        return False

    parsed = parse_pdf(data_dir / entry.pdf_path)
    if not parsed.chunks:
        log(f"  - {entry.title[:70]}: no text layer (scanned PDF?), skipped")
        return False
    texts = [embedding_text(entry.title, c) for c in parsed.chunks]
    shas = [_sha256(t) for t in texts]

    # Reuse vectors for identical text already in the DB (e.g. a re-issued master circular).
    cached: dict[str, np.ndarray] = dict(
        conn.execute(
            "SELECT DISTINCT ON (content_sha256) content_sha256, embedding FROM chunks "
            "WHERE content_sha256 = ANY(%s)",
            (shas,),
        ).fetchall()
    )
    todo = [i for i, sha in enumerate(shas) if sha not in cached]
    fresh = embedder.embed_documents([texts[i] for i in todo]) if todo else []
    vectors: list[np.ndarray] = [cached.get(sha) for sha in shas]  # type: ignore[misc]
    for i, vec in zip(todo, fresh, strict=True):
        vectors[i] = np.asarray(vec, dtype=np.float32)

    with conn.transaction():
        doc_id = conn.execute(
            """
            INSERT INTO documents (doc_type, title, ref_no, issued_on, page_url, pdf_url, pdf_sha256, page_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (page_url) DO UPDATE SET
                doc_type = EXCLUDED.doc_type, title = EXCLUDED.title, ref_no = EXCLUDED.ref_no,
                issued_on = EXCLUDED.issued_on, pdf_url = EXCLUDED.pdf_url,
                pdf_sha256 = EXCLUDED.pdf_sha256, page_count = EXCLUDED.page_count, ingested_at = now()
            RETURNING id
            """,
            (
                entry.doc_type,
                entry.title,
                parsed.ref_no,
                entry.issued_on,
                entry.page_url,
                entry.pdf_url,
                entry.sha256,
                parsed.page_count,
            ),
        ).fetchone()[0]
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (document_id, chunk_index, section, chapter, heading, paras,
                                    page_start, page_end, content, content_sha256, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        doc_id,
                        c.chunk_index,
                        c.section,
                        c.chapter,
                        c.heading,
                        c.paras,
                        c.page_start,
                        c.page_end,
                        c.content,
                        sha,
                        vec,
                    )
                    for c, sha, vec in zip(parsed.chunks, shas, vectors, strict=True)
                ],
            )
    log(
        f"  ✓ {entry.title[:70]}: {len(parsed.chunks)} chunks "
        f"({len(todo)} embedded, {len(shas) - len(todo)} reused)"
    )
    return True
