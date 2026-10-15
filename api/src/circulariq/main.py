import json
from collections.abc import Iterator

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from circulariq.answer import stream_answer
from circulariq.config import get_settings
from circulariq.db import connect
from circulariq.ratelimit import SlidingWindowLimiter
from circulariq.retrieval import retrieve
from circulariq.router import BudgetRouter

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Caps that keep a public demo from running up a bill. Worst case per day: 50 Sonnet answers
# (~$1.1) + 450 Haiku answers (~$0.6) + Voyage (free tier).
limiter = SlidingWindowLimiter({"minute": (6, 60), "day": (40, 86_400)}, global_daily=500)
router = BudgetRouter(settings.model_smart, settings.model_fast, settings.smart_answers_per_day)


def client_id(request: Request) -> str:
    # Render terminates TLS and forwards the visitor's IP in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/health")
def health() -> dict[str, str]:
    """Used by the frontend wake-up loader and by Render's health check. Never touches the DB."""
    return {"status": "ok", "service": settings.app_name}


@app.get("/stats")
def stats() -> dict[str, object]:
    """What's indexed: in-force document counts by type, pages and chunks."""
    try:
        with connect() as conn:
            docs = conn.execute(
                "SELECT doc_type, count(*) FROM documents WHERE superseded_by IS NULL "
                "GROUP BY doc_type"
            ).fetchall()
            pages = conn.execute(
                "SELECT coalesce(sum(page_count), 0) FROM documents WHERE superseded_by IS NULL"
            ).fetchone()[0]
            chunks = conn.execute(
                "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE d.superseded_by IS NULL"
            ).fetchone()[0]
    except (RuntimeError, psycopg.Error) as e:
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    return {"documents": dict(docs), "pages": pages, "chunks": chunks}


@app.get("/search")
def search(request: Request, q: str = Query(min_length=3, max_length=500)) -> dict[str, object]:
    """Retrieval only, no answer: the passages /ask would use, with scores. Used by evals."""
    if message := limiter.check(client_id(request)):
        raise HTTPException(status_code=429, detail=message)
    try:
        with connect() as conn:
            result = retrieve(conn, q)
    except (RuntimeError, psycopg.Error) as e:
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    return {
        "query": q,
        "answerable": result.answerable,
        "timings_ms": result.timings_ms,
        "hits": [
            {
                "title": r.hit.title,
                "section": r.hit.section,
                "page": r.hit.page_start,
                "url": r.hit.citation_url,
                "relevance": round(r.relevance, 3),
                "content": r.hit.content,
            }
            for r in result.hits
        ],
    }


def _sse(events: Iterator[dict[str, object]]) -> Iterator[str]:
    for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/ask")
def ask(body: AskRequest, request: Request) -> StreamingResponse:
    """Stream a cited answer as Server-Sent Events: sources → text/citation… → done."""
    if message := limiter.check(client_id(request)):
        raise HTTPException(status_code=429, detail=message)
    question = body.question.strip()
    try:
        with connect() as conn:
            result = retrieve(conn, question)
    except (RuntimeError, psycopg.Error) as e:
        raise HTTPException(status_code=503, detail="Database unavailable") from e
    model = router.pick() if result.answerable else settings.model_fast
    return StreamingResponse(
        _sse(stream_answer(result, model=model)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
