"""Hybrid retrieval: Postgres full-text (BM25-like) + pgvector cosine, fused with RRF.

Keyword search catches exact terms ("Regulation 54", "REF", ISIN); vector search catches
paraphrases ("money set aside for recovery"). Reciprocal Rank Fusion merges the two rankings
without having to calibrate their scores against each other.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import psycopg

RRF_K = 60  # standard constant from the RRF paper; dampens the weight of top ranks

HYBRID_SQL = """
WITH live AS (
    SELECT c.id, c.embedding, c.tsv
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE d.superseded_by IS NULL
),
vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(qvec)s) AS rank
    FROM live
    ORDER BY embedding <=> %(qvec)s
    LIMIT %(pool)s
),
-- OR the query's terms: questions like "how often must a broker settle..." rarely contain every
-- word of the answer. ts_rank_cd still rewards chunks that cover more of them.
q AS (
    SELECT replace(plainto_tsquery('english', %(qtext)s)::text, ' & ', ' | ')::tsquery AS q
),
kw AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q.q) DESC) AS rank
    FROM live, q
    WHERE tsv @@ q.q
    ORDER BY ts_rank_cd(tsv, q.q) DESC
    LIMIT %(pool)s
)
SELECT c.id, d.title, d.doc_type, d.issued_on, d.pdf_url, c.section, c.chapter, c.heading,
       c.page_start, c.page_end, c.content,
       vec.rank AS vec_rank, kw.rank AS kw_rank,
       coalesce(1.0 / (%(k)s + vec.rank), 0) + coalesce(1.0 / (%(k)s + kw.rank), 0) AS score
FROM (SELECT id FROM vec UNION SELECT id FROM kw) AS hits
JOIN chunks c ON c.id = hits.id
JOIN documents d ON d.id = c.document_id
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw ON kw.id = c.id
ORDER BY score DESC
LIMIT %(limit)s
"""


@dataclass
class Hit:
    chunk_id: int
    title: str
    doc_type: str
    issued_on: str
    pdf_url: str
    section: str
    chapter: str | None
    heading: str | None
    page_start: int
    page_end: int
    content: str
    vec_rank: int | None
    kw_rank: int | None
    score: float

    @property
    def citation_url(self) -> str:
        """Opens the PDF at the cited page in any browser's built-in viewer."""
        return f"{self.pdf_url}#page={self.page_start}"


def hybrid_search(
    conn: psycopg.Connection, query: str, query_vec: list[float], limit: int = 20, pool: int = 50
) -> list[Hit]:
    rows = conn.execute(
        HYBRID_SQL,
        {
            "qvec": np.asarray(query_vec, dtype=np.float32),
            "qtext": query,
            "pool": pool,
            "k": RRF_K,
            "limit": limit,
        },
    ).fetchall()
    return [
        Hit(
            chunk_id=r[0],
            title=r[1],
            doc_type=r[2],
            issued_on=str(r[3]),
            pdf_url=r[4],
            section=r[5],
            chapter=r[6],
            heading=r[7],
            page_start=r[8],
            page_end=r[9],
            content=r[10],
            vec_rank=r[11],
            kw_rank=r[12],
            score=float(r[13]),
        )
        for r in rows
    ]


if __name__ == "__main__":
    import sys

    from circulariq.db import connect
    from circulariq.embed import Embedder

    question = " ".join(sys.argv[1:]) or "What is the security cover requirement for debentures?"
    with connect() as conn:
        hits = hybrid_search(conn, question, Embedder().embed_query(question), limit=5)
    print(f"Q: {question}\n")
    for i, h in enumerate(hits, 1):
        print(f"{i}. [{h.score:.4f} vec#{h.vec_rank} kw#{h.kw_rank}] {h.title[:60]}")
        print(f"   {h.section} · p.{h.page_start} · {h.citation_url}")
        print(f"   {h.content[:220]!r}\n")
