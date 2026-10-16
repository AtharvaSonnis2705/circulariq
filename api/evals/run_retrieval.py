"""Retrieval eval: does the right passage come back, and how high?

For every golden question this runs one hybrid SQL query (which also yields the vector-only
and keyword-only rankings) and reranks each ranking with Voyage, so all six variants
(keyword / vector / hybrid, each with and without rerank) are scored on the same candidates.
It also sweeps the "not found" cutoff: how many answerable questions would be wrongly refused,
and how many unanswerable ones would wrongly reach the model.

Costs nothing: Voyage embed + rerank come from the free token allowance; no Claude calls.

    uv run python -m evals.run_retrieval           # full run, writes results/latest.json
    uv run python -m evals.run_retrieval --gate    # CI: production config only, fail on regression
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from circulariq.config import get_settings
from circulariq.db import connect
from circulariq.retrieval import CANDIDATES, MIN_RELEVANCE, TOP_K, _embedder, _voyage, rerank_text
from circulariq.search import Hit, hybrid_search
from evals.common import GoldenQuestion, load_golden, matches
from evals.results import load_latest, save_section

KS = (1, 5, 10)
THRESHOLDS = [round(0.40 + 0.05 * i, 2) for i in range(9)]  # 0.40 … 0.80
# CI fails when recall@5 drops more than this below the committed baseline (~3 of 53 questions).
GATE_MARGIN = 0.05
PRODUCTION = "hybrid+rerank"


@dataclass
class Ranked:
    hits: list[Hit]
    scores: list[float] | None = None  # rerank relevance, when reranked


def candidate_lists(conn, question: str) -> dict[str, list[Hit]]:
    """Top-30 candidates per search mode, from one query (vector pool 50 ∪ keyword pool 50)."""
    vec = _embedder().embed_query(question)
    rows = hybrid_search(conn, question, vec, limit=100)
    by_vec = sorted((h for h in rows if h.vec_rank), key=lambda h: h.vec_rank)
    by_kw = sorted((h for h in rows if h.kw_rank), key=lambda h: h.kw_rank)
    return {
        "keyword": by_kw[:CANDIDATES],
        "vector": by_vec[:CANDIDATES],
        "hybrid": rows[:CANDIDATES],  # rows are ordered by RRF score: same as production
    }


def rerank(question: str, hits: list[Hit]) -> Ranked:
    if not hits:
        return Ranked([], [])
    result = _voyage().rerank(
        question,
        [rerank_text(h) for h in hits],
        model=get_settings().rerank_model,
        top_k=len(hits),
    )
    return Ranked(
        [hits[r.index] for r in result.results],
        [float(r.relevance_score) for r in result.results],
    )


def expected_ranks(q: GoldenQuestion, hits: list[Hit]) -> list[int | None]:
    """1-based rank of the first chunk matching each expected passage (None if absent)."""
    ranks: list[int | None] = []
    for e in q.expected:
        rank = next((i for i, h in enumerate(hits, 1) if matches(e, h.title, h.content)), None)
        ranks.append(rank)
    return ranks


def score_variant(per_question: list[list[int | None]]) -> dict[str, float]:
    """recall@k = share of expected passages found in the top k, averaged over questions."""
    n = len(per_question)
    out: dict[str, float] = {}
    for k in KS:
        out[f"recall@{k}"] = (
            sum(sum(1 for r in ranks if r and r <= k) / len(ranks) for ranks in per_question) / n
        )
    out["mrr"] = (
        sum(1 / min((r for r in ranks if r), default=float("inf")) for ranks in per_question) / n
    )
    return {key: round(v, 4) for key, v in out.items()}


def sweep(top_answerable: list[float], top_unanswerable: list[float]) -> list[dict]:
    rows = []
    for t in THRESHOLDS:
        rows.append(
            {
                "threshold": t,
                "false_refusals": sum(1 for s in top_answerable if s < t),
                "false_answers": sum(1 for s in top_unanswerable if s >= t),
                "production": t == MIN_RELEVANCE,
            }
        )
    return rows


def run(gate: bool) -> dict:
    golden = load_golden()
    answerable = [q for q in golden if q.answerable]
    unanswerable = [q for q in golden if not q.answerable]
    variants = [PRODUCTION] if gate else [
        "keyword", "vector", "hybrid", "keyword+rerank", "vector+rerank", PRODUCTION
    ]  # fmt: skip
    ranks: dict[str, list[list[int | None]]] = {v: [] for v in variants}
    details, top_ans, top_unans = [], [], []

    started = time.perf_counter()
    with connect() as conn:
        for i, q in enumerate(golden, 1):
            lists = candidate_lists(conn, q.question)
            ranked: dict[str, Ranked] = {}
            for v in variants:
                mode, _, rr = v.partition("+")
                ranked[v] = rerank(q.question, lists[mode]) if rr else Ranked(lists[mode])
            prod = ranked[PRODUCTION]
            top = prod.scores[0] if prod.scores else 0.0
            if q.answerable:
                for v in variants:
                    ranks[v].append(expected_ranks(q, ranked[v].hits))
                top_ans.append(top)
            else:
                top_unans.append(top)
            details.append(
                {
                    "id": q.id,
                    "type": q.type,
                    "hard": q.hard,
                    "question": q.question,
                    "expected_ranks": expected_ranks(q, prod.hits) if q.answerable else [],
                    "top_score": round(top, 3),
                    "passes_gate": top >= MIN_RELEVANCE,
                    "top_hits": [
                        {
                            "title": h.title,
                            "section": h.section,
                            "page": h.page_start,
                            "score": round(s, 3),
                        }
                        for h, s in zip(prod.hits[:3], prod.scores or [], strict=False)
                    ],
                }
            )
            print(f"[{i}/{len(golden)}] {q.id} top={top:.2f} ranks={details[-1]['expected_ranks']}")

    prod_metrics = score_variant(ranks[PRODUCTION])
    hard_idx = [i for i, q in enumerate(answerable) if q.hard]
    return {
        "config": {
            "candidates": CANDIDATES,
            "context_passages": TOP_K,
            "min_relevance": MIN_RELEVANCE,
            "rerank_model": get_settings().rerank_model,
            "embed_model": get_settings().embed_model,
        },
        "counts": {"answerable": len(answerable), "unanswerable": len(unanswerable)},
        "headline": {
            **prod_metrics,
            f"context_recall@{TOP_K}": round(
                sum(sum(1 for r in rs if r and r <= TOP_K) / len(rs) for rs in ranks[PRODUCTION])
                / len(answerable),
                4,
            ),
            "hard_recall@5": score_variant([ranks[PRODUCTION][i] for i in hard_idx])["recall@5"]
            if hard_idx
            else None,
            "false_refusals": sum(1 for s in top_ans if s < MIN_RELEVANCE),
            "false_answers": sum(1 for s in top_unans if s >= MIN_RELEVANCE),
        },
        "ablations": {v: score_variant(ranks[v]) for v in variants},
        "threshold_sweep": sweep(top_ans, top_unans),
        "questions": details,
        "seconds": round(time.perf_counter() - started, 1),
    }


def check_gate(result: dict) -> int:
    baseline = (load_latest().get("retrieval") or {}).get("headline")
    if not baseline:
        print("No committed baseline in results/latest.json; nothing to compare against.")
        return 0
    now, base = result["headline"], baseline
    failures = []
    if now["recall@5"] < base["recall@5"] - GATE_MARGIN:
        failures.append(
            f"recall@5 {now['recall@5']:.3f} < baseline {base['recall@5']:.3f} - {GATE_MARGIN}"
        )
    if now["false_answers"] > base["false_answers"] + 1:
        failures.append(
            f"false answers {now['false_answers']} > baseline {base['false_answers']} + 1"
        )
    print(
        f"recall@5 {now['recall@5']:.3f} (baseline {base['recall@5']:.3f}), "
        f"MRR {now['mrr']:.3f}, false answers {now['false_answers']} "
        f"(baseline {base['false_answers']})"
    )
    for f in failures:
        print(f"FAIL: {f}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--gate", action="store_true", help="CI mode: compare, don't write")
    args = parser.parse_args()
    result = run(gate=args.gate)
    if args.gate:
        sys.exit(check_gate(result))
    save_section("retrieval", result)
    h = result["headline"]
    print(
        f"\nrecall@1 {h['recall@1']:.3f}  recall@5 {h['recall@5']:.3f}  recall@10 {h['recall@10']:.3f}  MRR {h['mrr']:.3f}"
    )
    for name, m in result["ablations"].items():
        print(
            f"  {name:16} R@1 {m['recall@1']:.3f}  R@5 {m['recall@5']:.3f}  R@10 {m['recall@10']:.3f}  MRR {m['mrr']:.3f}"
        )


if __name__ == "__main__":
    main()
