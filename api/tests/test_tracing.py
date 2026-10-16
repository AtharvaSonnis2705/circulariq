from typing import Any

from circulariq import tracing
from circulariq.retrieval import Retrieval

EVENTS = [
    {"type": "sources", "sources": []},
    {"type": "text", "block": 0, "text": "Within 60 days."},
    {
        "type": "done",
        "answered": True,
        "model": "claude-sonnet-5-5",
        "timings_ms": {"generate": 900},
        "usage": {"input_tokens": 4000, "output_tokens": 300},
    },
]


class FakeObservation:
    def __init__(self, log: list[tuple[str, Any]], name: str) -> None:
        self.log, self.name = log, name

    def start_observation(self, *, name: str, **kwargs: Any) -> "FakeObservation":
        self.log.append(("start", name))
        return FakeObservation(self.log, name)

    def update(self, **kwargs: Any) -> None:
        self.log.append((f"update:{self.name}", kwargs))

    def end(self) -> None:
        self.log.append(("end", self.name))


def test_disabled_tracing_passes_events_through(monkeypatch):
    monkeypatch.setattr(tracing, "get_langfuse", lambda: None)
    trace = tracing.AskTrace("q")
    trace.start_retrieval()
    trace.end_retrieval(Retrieval("q", []))
    assert list(trace.wrap(iter(EVENTS), "claude-sonnet-5-5")) == EVENTS


def test_trace_records_usage_and_cost(monkeypatch):
    log: list[tuple[str, Any]] = []
    monkeypatch.setattr(tracing, "get_langfuse", lambda: FakeObservation(log, "client"))
    trace = tracing.AskTrace("q")
    assert list(trace.wrap(iter(EVENTS), "claude-sonnet-5-5")) == EVENTS
    gen = next(kw for kind, kw in log if kind == "update:answer")
    assert gen["usage_details"] == {"input": 4000, "output": 300}
    assert gen["cost_details"]["total"] == round((4000 * 2 + 300 * 10) / 1e6, 6)
    assert ("end", "ask") in log


def test_gate_refusal_records_no_generation(monkeypatch):
    log: list[tuple[str, Any]] = []
    monkeypatch.setattr(tracing, "get_langfuse", lambda: FakeObservation(log, "client"))
    refused = [
        {"type": "text", "block": 0, "text": "not found"},
        {"type": "done", "answered": False},
    ]
    list(tracing.AskTrace("q").wrap(iter(refused), "claude-haiku-5-5", calls_model=False))
    assert ("start", "answer") not in log


def test_tracing_errors_never_break_the_answer(monkeypatch):
    class Broken:
        def start_observation(self, **kwargs: Any) -> None:
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "get_langfuse", lambda: Broken())
    assert list(tracing.AskTrace("q").wrap(iter(EVENTS), "claude-sonnet-5-5")) == EVENTS
