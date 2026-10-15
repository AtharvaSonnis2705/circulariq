"""In-memory rate limits for the public demo.

One Render instance serves the API, so process memory is a fine place for counters: a restart
resets them, which is acceptable for a demo. If we ever run several instances, move this to Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limits: dict[str, tuple[int, float]], global_daily: int) -> None:
        """`limits` maps a name to (max requests, window seconds) applied per client."""
        self._limits = limits
        self._global_daily = global_daily
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, client: str, now: float | None = None) -> str | None:
        """Record a request. Returns None if allowed, else a message saying which limit hit."""
        now = time.time() if now is None else now
        with self._lock:
            self._trim(self._global, now, 86_400)
            if len(self._global) >= self._global_daily:
                return "The demo has reached its daily question limit. Please try again tomorrow."
            for name, (max_requests, window) in self._limits.items():
                q = self._hits[(client, name)]
                self._trim(q, now, window)
                if len(q) >= max_requests:
                    return f"Too many questions ({max_requests} per {name}). Please wait a bit."
            for name in self._limits:
                self._hits[(client, name)].append(now)
            self._global.append(now)
            return None

    @staticmethod
    def _trim(q: deque[float], now: float, window: float) -> None:
        while q and now - q[0] > window:
            q.popleft()
