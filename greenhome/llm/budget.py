"""One time budget per answer (P5 request): every LLM call in an explain()/chat() shares one deadline.

`LLM_TIMEOUT_S` caps a single call; `answer_budget_s` caps the whole answer. When the budget is spent
the caller returns the template answer at once.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def call_timeout(self, cap_s: float) -> float:
        """Timeout for the next LLM call: the per-call cap or what is left, whichever is smaller."""
        return min(cap_s, self.remaining())

    def can_call(self, min_s: float) -> bool:
        """Worth starting another LLM call? Not if it can't finish in a useful time."""
        return self.remaining() >= min_s
