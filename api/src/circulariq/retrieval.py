"""Question → the few SEBI passages most likely to answer it.

1. Hybrid search (keyword + vector, RRF) casts a wide net: 30 candidates.
2. Voyage rerank-3 reads each candidate against the question and keeps the best few.
3. If even the best passage scores low, we say so instead of letting the model guess.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache

import psycopg
import voyageai

from circulariq.config import get_settings
from circulariq.embed import Embedder
from circulariq.search import Hit, hybrid_search

CANDIDATES = 30
TOP_K = 6
# Below this rerank score the passage is unlikely to answer the question. First calibration
# (2026-10-15): 8 on-topic SEBI questions scored 0.71–0.93; 6 off-topic ones 0.25–0.67
# (the 0.67 was "RBI KYC norms", near SEBI KYC content, so the prompt handles that case).
MIN_RELEVANCE = 0.60


@dataclass
class RankedHit:
    hit: Hit
    relevance: float


@dataclass
class Retrieval:
    query: str
    hits: list[RankedHit]
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def answerable(self) -> bool:
        return bool(self.hits) and self.hits[0].relevance >= MIN_RELEVANCE


@lru_cache
def _embedder() -> Embedder:
    return Embedder()


@lru_cache
def _voyage() -> voyageai.Client:
    return voyageai.Client(api_key=get_settings().voyage_api_key, max_retries=2)


def rerank_text(hit: Hit) -> str:
    header = " | ".join(p for p in (hit.title, hit.chapter, hit.heading) if p)
    return f"{header}\n{hit.content}"


def retrieve(conn: psycopg.Connection, query: str, top_k: int = TOP_K) -> Retrieval:
    timings: dict[str, float] = {}
    t = time.perf_counter()
    query_vec = _embedder().embed_query(query)
    timings["embed"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    candidates = hybrid_search(conn, query, query_vec, limit=CANDIDATES)
    timings["search"] = (time.perf_counter() - t) * 1000
    if not candidates:
        return Retrieval(query, [], timings)

    t = time.perf_counter()
    reranked = _voyage().rerank(
        query,
        [rerank_text(h) for h in candidates],
        model=get_settings().rerank_model,
        top_k=top_k,
    )
    timings["rerank"] = (time.perf_counter() - t) * 1000

    hits = [RankedHit(candidates[r.index], float(r.relevance_score)) for r in reranked.results]
    return Retrieval(query, hits, timings)
