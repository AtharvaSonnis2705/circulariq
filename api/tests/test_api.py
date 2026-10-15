import json

from fastapi.testclient import TestClient

from circulariq import main
from circulariq.answer import NOT_FOUND_MESSAGE, build_messages, stream_answer
from circulariq.ratelimit import SlidingWindowLimiter
from circulariq.retrieval import RankedHit, Retrieval
from circulariq.search import Hit

client = TestClient(main.app)


def make_hit(content: str = "1. First rule.\n\n2. Second rule.") -> Hit:
    return Hit(
        chunk_id=1,
        title="Master Circular for Stock Brokers",
        doc_type="master_circular",
        issued_on="2026-06-01",
        pdf_url="https://www.sebi.gov.in/sebi_data/attachdocs/x.pdf",
        section="Chapter I › Paras 1–2",
        chapter="Chapter I: General",
        heading=None,
        page_start=12,
        page_end=13,
        content=content,
        vec_rank=1,
        kw_rank=2,
        score=0.03,
    )


def test_build_messages_sends_citable_search_results() -> None:
    retrieval = Retrieval("How often?", [RankedHit(make_hit(), 0.9)])
    [message] = build_messages(retrieval)
    result, question = message["content"]
    assert result["type"] == "search_result"
    assert result["source"].endswith("x.pdf#page=12")
    assert result["citations"] == {"enabled": True}
    # One block per paragraph, so citations point at a paragraph rather than the whole chunk.
    assert [b["text"] for b in result["content"]] == ["1. First rule.", "2. Second rule."]
    assert question == {"type": "text", "text": "How often?"}


def test_low_relevance_answers_not_found_without_calling_claude(monkeypatch) -> None:
    def no_claude():
        raise AssertionError("Claude must not be called for unanswerable questions")

    monkeypatch.setattr("circulariq.answer.get_client", no_claude)
    events = list(stream_answer(Retrieval("capital of France?", [RankedHit(make_hit(), 0.2)])))
    assert [e["type"] for e in events] == ["sources", "text", "done"]
    assert events[1]["text"] == NOT_FOUND_MESSAGE
    assert events[2]["answered"] is False


def test_ask_streams_server_sent_events(monkeypatch) -> None:
    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main, "connect", lambda: FakeConn())
    monkeypatch.setattr(main, "retrieve", lambda conn, q: Retrieval(q, []))
    monkeypatch.setattr(main, "limiter", SlidingWindowLimiter({"minute": (10, 60)}, 100))
    response = client.post("/ask", json={"question": "What is the capital of France?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert [e["type"] for e in events] == ["sources", "text", "done"]


def test_ask_validates_question_length() -> None:
    assert client.post("/ask", json={"question": "hi"}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422


def test_rate_limiter_per_client_and_global() -> None:
    limiter = SlidingWindowLimiter({"minute": (2, 60)}, global_daily=4)
    assert limiter.check("a", now=0) is None
    assert limiter.check("a", now=1) is None
    assert "Too many" in limiter.check("a", now=2)
    assert limiter.check("a", now=61) is None  # window slid
    assert limiter.check("b", now=62) is None
    assert "daily" in limiter.check("c", now=63)  # 4 allowed so far; rejected requests don't count


def test_budget_router_falls_back_after_daily_budget() -> None:
    from circulariq.router import BudgetRouter

    router = BudgetRouter("smart", "fast", smart_per_day=2)
    assert [router.pick(now=t) for t in (0, 1, 2)] == ["smart", "smart", "fast"]
    assert router.smart_remaining(now=3) == 0
    assert router.pick(now=86_401) == "smart"  # first use has aged out of the window
