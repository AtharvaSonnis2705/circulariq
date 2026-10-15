"""Cost-aware model choice for answers.

Sonnet 5.5 writes better-cited answers (86% of answer text cited vs 44% for Haiku 5.5 in our
first comparison) and starts streaming sooner, but costs ~17× more per question. We use Sonnet
for the first N answers in any 24-hour window, then fall back to Haiku, so a traffic spike can
never cost more than a known amount.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class BudgetRouter:
    def __init__(self, smart_model: str, fast_model: str, smart_per_day: int) -> None:
        self.smart_model = smart_model
        self.fast_model = fast_model
        self.smart_per_day = smart_per_day
        self._smart_uses: deque[float] = deque()
        self._lock = threading.Lock()

    def pick(self, now: float | None = None) -> str:
        """Choose a model for one answer, counting it against the daily smart budget."""
        now = time.time() if now is None else now
        with self._lock:
            while self._smart_uses and now - self._smart_uses[0] > 86_400:
                self._smart_uses.popleft()
            if len(self._smart_uses) < self.smart_per_day:
                self._smart_uses.append(now)
                return self.smart_model
            return self.fast_model

    def smart_remaining(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            recent = sum(1 for t in self._smart_uses if now - t <= 86_400)
        return max(0, self.smart_per_day - recent)
