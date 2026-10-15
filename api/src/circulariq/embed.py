"""Voyage embeddings with batching, a tokens-per-minute throttle, and retry on rate limits."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

import voyageai
import voyageai.error

from circulariq.config import get_settings

MAX_TEXTS_PER_REQUEST = 128
MAX_TOKENS_PER_REQUEST = 100_000  # well under voyage-4's 320K per-request cap


def estimate_tokens(text: str) -> int:
    """Rough count (≈1.3 tokens per word for English legal text); only used for batching."""
    return int(len(text.split()) * 1.3) + 8


class Embedder:
    def __init__(
        self, tpm: int | None = None, rpm: int | None = None, log: Callable[[str], None] = print
    ) -> None:
        settings = get_settings()
        if not settings.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY is not set. Add it to .env")
        self._client = voyageai.Client(api_key=settings.voyage_api_key)
        self._model = settings.embed_model
        self._dim = settings.embed_dim
        self._tpm = settings.voyage_tpm if tpm is None else tpm
        self._rpm = settings.voyage_rpm if rpm is None else rpm
        self._window: deque[tuple[float, int]] = deque()  # (sent_at, tokens) in the last 60 s
        self._log = log
        self.tokens_used = 0

    def _batches(self, texts: list[str]) -> list[list[int]]:
        budget = MAX_TOKENS_PER_REQUEST
        if self._tpm:
            # Our token estimate is rough, so leave headroom under the real limit.
            budget = min(budget, int(self._tpm * 0.8))
        batches: list[list[int]] = [[]]
        tokens = 0
        for i, text in enumerate(texts):
            t = estimate_tokens(text)
            if batches[-1] and (tokens + t > budget or len(batches[-1]) >= MAX_TEXTS_PER_REQUEST):
                batches.append([])
                tokens = 0
            batches[-1].append(i)
            tokens += t
        return [b for b in batches if b]

    def _throttle(self, tokens: int) -> None:
        """Block until sending `tokens` keeps us under both the token and request limits."""
        if not (self._tpm or self._rpm):
            return
        while True:
            now = time.monotonic()
            while self._window and now - self._window[0][0] > 60:
                self._window.popleft()
            used = sum(t for _, t in self._window)
            tokens_ok = not self._tpm or not self._window or used + tokens <= self._tpm * 0.8
            requests_ok = not self._rpm or len(self._window) < self._rpm
            if tokens_ok and requests_ok:
                return
            wait = 60 - (now - self._window[0][0]) + 0.5
            self._log(f"    throttling {wait:.0f}s (Voyage free-tier limits)")
            time.sleep(wait)

    def _embed_batch(self, texts: list[str], input_type: str) -> list[list[float]]:
        estimate = sum(estimate_tokens(t) for t in texts)
        attempts = 8
        for attempt in range(attempts):
            self._throttle(estimate)
            self._window.append((time.monotonic(), estimate))
            try:
                result = self._client.embed(
                    texts, model=self._model, input_type=input_type, output_dimension=self._dim
                )
            except (
                voyageai.error.RateLimitError,
                voyageai.error.ServiceUnavailableError,
                voyageai.error.ServerError,
                voyageai.error.APIConnectionError,
                voyageai.error.Timeout,
                voyageai.error.TryAgain,
            ):
                if attempt == attempts - 1:
                    raise
                wait = min(120, 10 * 2**attempt)
                self._log(f"    Voyage busy/rate-limited; retrying in {wait}s")
                time.sleep(wait)
                continue
            self._window[-1] = (self._window[-1][0], result.total_tokens)
            self.tokens_used += result.total_tokens
            return result.embeddings
        raise AssertionError("unreachable")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = [[] for _ in texts]
        for batch in self._batches(texts):
            batch_texts = [texts[i] for i in batch]
            for i, vector in zip(batch, self._embed_batch(batch_texts, "document"), strict=True):
                out[i] = vector
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], "query")[0]
