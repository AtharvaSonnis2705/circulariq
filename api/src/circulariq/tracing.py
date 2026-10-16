"""Optional Langfuse tracing: one trace per question, with a retrieve step and an answer step.

Each trace records what retrieval returned (and how long embed/search/rerank took) and, for the
answer, the model that actually served it, tokens, cost, time to first token and whether it was
refused. Tracing is off unless both Langfuse keys are set, and a tracing failure is logged and
ignored: it must never break an answer.

The Langfuse SDK sends spans from a background thread in small batches, so a trace reaches
Langfuse within seconds; `shutdown()` flushes the rest when the server stops.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from langfuse import Langfuse

from circulariq.config import get_settings
from circulariq.pricing import cost_usd
from circulariq.retrieval import Retrieval

log = logging.getLogger(__name__)


@lru_cache
def get_langfuse() -> Langfuse | None:
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return None
    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
        environment=s.environment,
    )


def shutdown() -> None:
    if (lf := get_langfuse()) is not None:
        lf.shutdown()


class AskTrace:
    """Wraps one question's retrieval and answer stream. Every method is safe to call when
    tracing is disabled (it does nothing)."""

    def __init__(self, question: str, source: str = "api") -> None:
        self._root: Any = None
        self._retrieval: Any = None
        try:
            if (lf := get_langfuse()) is not None:
                self._root = lf.start_observation(
                    name="ask", input={"question": question}, metadata={"source": source}
                )
        except Exception:
            log.exception("langfuse: could not start trace")

    def start_retrieval(self) -> None:
        if self._root is None:
            return
        try:
            self._retrieval = self._root.start_observation(name="retrieve", as_type="retriever")
        except Exception:
            log.exception("langfuse: could not start retrieval span")

    def end_retrieval(self, retrieval: Retrieval) -> None:
        if self._root is None:
            return
        try:
            span = self._retrieval or self._root.start_observation(
                name="retrieve", as_type="retriever"
            )
            span.update(
                input={"query": retrieval.query},
                output=[
                    {
                        "title": r.hit.title,
                        "section": r.hit.section,
                        "page": r.hit.page_start,
                        "relevance": round(r.relevance, 3),
                    }
                    for r in retrieval.hits
                ],
                metadata={"timings_ms": retrieval.timings_ms, "answerable": retrieval.answerable},
            )
            span.end()
        except Exception:
            log.exception("langfuse: could not record retrieval")

    def wrap(
        self, events: Iterator[dict[str, Any]], model: str, calls_model: bool = True
    ) -> Iterator[dict[str, Any]]:
        """Pass the answer events through unchanged, recording the answer as a generation.

        `calls_model=False` when the relevance gate will refuse: no generation is recorded."""
        if self._root is None:
            yield from events
            return
        generation: Any = None
        text: list[str] = []
        first_token: datetime | None = None
        outcome: dict[str, Any] = {}
        if calls_model:
            try:
                generation = self._root.start_observation(
                    name="answer", as_type="generation", model=model
                )
            except Exception:
                log.exception("langfuse: could not start generation")
        try:
            for event in events:
                if event["type"] == "text":
                    first_token = first_token or datetime.now(UTC)
                    text.append(event["text"])
                elif event["type"] in ("done", "error"):
                    outcome = event
                yield event
        finally:
            self._finish(generation, "".join(text), first_token, outcome, model)

    def _finish(
        self,
        generation: Any,
        text: str,
        first_token: datetime | None,
        outcome: dict[str, Any],
        model: str,
    ) -> None:
        try:
            failed = outcome.get("type") == "error"
            answered = bool(outcome.get("answered"))
            if generation is not None:
                update: dict[str, Any] = {"output": text, "completion_start_time": first_token}
                if usage := outcome.get("usage"):
                    served_by = outcome.get("model", model)
                    cost = cost_usd(served_by, usage["input_tokens"], usage["output_tokens"])
                    update.update(
                        model=served_by,
                        usage_details={
                            "input": usage["input_tokens"],
                            "output": usage["output_tokens"],
                        },
                        cost_details={"total": round(cost, 6)},
                    )
                if failed:
                    update.update(level="ERROR", status_message=outcome.get("message"))
                generation.update(**update)
                generation.end()
            self._root.update(
                output={
                    "answer": text,
                    "answered": answered,
                    "timings_ms": outcome.get("timings_ms"),
                },
                level="ERROR" if failed else "DEFAULT",
            )
            self._root.end()
        except Exception:
            log.exception("langfuse: could not finish trace")
