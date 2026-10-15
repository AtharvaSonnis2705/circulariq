"""Turn retrieved SEBI passages into a streamed, cited answer.

Passages go to Claude as `search_result` blocks with citations enabled, so every claim in the
answer comes back attached to the exact passage that supports it. Citations are produced by
the API, not written by the model as free text, so the UI can always link them to a real page.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import anthropic

from circulariq.config import get_settings
from circulariq.llm import get_client
from circulariq.retrieval import Retrieval

# Haiku 5.5 thinks before answering and thinking counts toward max_tokens, so leave headroom
# beyond the ~250-word answer itself.
MAX_ANSWER_TOKENS = 3000

SYSTEM_PROMPT = """You are CircularIQ, an assistant that answers questions about Indian securities \
regulation using SEBI master circulars and circulars.

How to answer:
- Use only the search results provided with the question. They are excerpts from SEBI documents \
currently in force. Do not rely on outside knowledge of SEBI rules, which may be outdated.
- Lead with the direct answer in one or two sentences, then give the specific conditions, \
limits, timelines or exceptions that matter, as short bullet points when there are several.
- Every statement of a rule, number or condition must come from a specific excerpt so that it \
carries a citation. If you can't tie a statement to an excerpt, leave it out.
- Write in your own plain words. Each point is cited to the passage it comes from, so don't \
repeat the passage after paraphrasing it. Quote only short phrases where the exact wording \
matters: numbers, deadlines, thresholds and defined terms, exactly as the excerpts state them.
- If the excerpts only partly answer the question, answer that part and say plainly what they \
don't cover. If they don't answer it at all, say you couldn't find it in the indexed SEBI \
documents. Never fill gaps with guesses.
- Mention which document a rule comes from by name (e.g. "the Master Circular for Stock \
Brokers") when it helps the reader. Don't add bracketed reference numbers yourself; citations \
are attached automatically.
- You provide information, not legal advice. Don't add a disclaimer to every answer; the \
interface already shows one.
- Keep answers under about 250 words unless the question needs more."""

NOT_FOUND_MESSAGE = (
    "I couldn't find this in the indexed SEBI master circulars and circulars. "
    "Try rephrasing with the specific intermediary or term (for example, "
    '"stock broker", "mutual fund", "debenture trustee").'
)


@dataclass
class Source:
    index: int
    title: str
    section: str
    page: int
    url: str
    doc_type: str
    issued_on: str
    relevance: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def sources_for(retrieval: Retrieval) -> list[Source]:
    return [
        Source(
            index=i,
            title=r.hit.title,
            section=r.hit.section,
            page=r.hit.page_start,
            url=r.hit.citation_url,
            doc_type=r.hit.doc_type,
            issued_on=r.hit.issued_on,
            relevance=round(r.relevance, 3),
        )
        for i, r in enumerate(retrieval.hits)
    ]


def build_messages(retrieval: Retrieval) -> list[dict[str, Any]]:
    """One user turn: every passage as a citable search result, then the question."""
    content: list[dict[str, Any]] = []
    for r in retrieval.hits:
        h = r.hit
        # Each paragraph is its own block, so citations point at the paragraph, not the chunk.
        paragraphs = [p.strip() for p in h.content.split("\n\n") if p.strip()]
        content.append(
            {
                "type": "search_result",
                "source": h.citation_url,
                "title": f"{h.title} — {h.section} (p. {h.page_start}, issued {h.issued_on})",
                "content": [{"type": "text", "text": p} for p in paragraphs],
                "citations": {"enabled": True},
            }
        )
    content.append({"type": "text", "text": retrieval.query})
    return [{"role": "user", "content": content}]


# Models that support server-side refusal fallbacks ("default" form). Haiku has no fallback.
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}


def _open_stream(model: str, effort: str, messages: list[dict[str, Any]]):
    common = {
        "model": model,
        "max_tokens": MAX_ANSWER_TOKENS,
        "system": SYSTEM_PROMPT,
        # Retrieval already did the hard part; low effort keeps answers fast and cheap.
        "output_config": {"effort": effort},
        "messages": messages,
    }
    if model in FALLBACK_MODELS:
        # If the model declines, the API re-runs the request on Anthropic's recommended
        # fallback model inside the same call instead of returning a refusal.
        return get_client().beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **common
        )
    return get_client().messages.stream(**common)


def stream_answer(
    retrieval: Retrieval, model: str | None = None, effort: str = "low"
) -> Iterator[dict[str, Any]]:
    """Yield UI events: `sources`, then `text`/`citation` as Claude writes, then `done`.

    `text` and `citation` events carry the index of the answer block they belong to, so the
    client can place each citation marker right after the sentence it supports.
    """
    settings = get_settings()
    sources = sources_for(retrieval)
    yield {"type": "sources", "sources": [s.to_dict() for s in sources]}

    if not retrieval.answerable:
        yield {"type": "text", "block": 0, "text": NOT_FOUND_MESSAGE}
        yield {"type": "done", "answered": False, "timings_ms": retrieval.timings_ms}
        return

    started = time.perf_counter()
    first_token_ms: float | None = None
    block = -1
    try:
        with _open_stream(
            model or settings.model_fast, effort, build_messages(retrieval)
        ) as stream:
            for event in stream:
                if event.type == "content_block_start" and event.content_block.type == "text":
                    block += 1
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - started) * 1000
                        yield {"type": "text", "block": block, "text": delta.text}
                    elif delta.type == "citations_delta":
                        citation = delta.citation
                        if citation.type == "search_result_location":
                            yield {
                                "type": "citation",
                                "block": block,
                                "source": citation.search_result_index,
                                "cited_text": citation.cited_text,
                            }
            final = stream.get_final_message()
    except anthropic.APIError as e:
        yield {"type": "error", "message": "The answer service is unavailable. Please retry."}
        print(f"anthropic error: {type(e).__name__}: {e}")
        return

    if final.stop_reason == "refusal":
        yield {"type": "error", "message": "This question can't be answered here."}
        return

    usage = final.usage
    yield {
        "type": "done",
        "answered": True,
        "truncated": final.stop_reason == "max_tokens",
        "model": final.model,
        "timings_ms": {
            **retrieval.timings_ms,
            "first_token": round(first_token_ms or 0),
            "generate": round((time.perf_counter() - started) * 1000),
        },
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    }
