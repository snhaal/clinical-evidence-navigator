"""
A real, RPM-respecting rate limiter for outbound LLM calls.

This is different from app/rate_limit.py, which throttles incoming HTTP
requests per client IP. This one throttles OUTBOUND calls to the LLM
provider, process-wide, because provider RPM quotas (Gemini's free tier
in particular) are enforced per-project — not per-request, not per-IP —
so every coroutine in the process that calls the LLM must share one
counter, not get its own.

Unlike a semaphore (which limits CONCURRENCY), this limits RATE: it
tracks how many calls happened in the trailing 60 seconds and makes the
caller `await` (sleep) until there's room, rather than firing everything
at once and letting the provider reject the excess with a 429.
"""

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    def __init__(self, max_per_minute: int):
        if max_per_minute < 1:
            raise ValueError("max_per_minute must be at least 1")
        self._max_per_minute = max_per_minute
        self._call_timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Blocks (via asyncio.sleep, not a busy loop) until a call is safe
        to make without exceeding max_per_minute within any trailing
        60-second window. Safe to call from many coroutines concurrently
        — the internal lock serializes the check-and-reserve step, so two
        callers can never both think they got the "last" slot.
        """
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._call_timestamps and self._call_timestamps[0] < cutoff:
                    self._call_timestamps.popleft()

                if len(self._call_timestamps) < self._max_per_minute:
                    self._call_timestamps.append(now)
                    return

                # Oldest call in the window is what we're waiting to age out.
                wait_seconds = self._call_timestamps[0] + 60.0 - now

            # Sleep OUTSIDE the lock so other coroutines can still check in
            # (and possibly find room, if their wait is shorter) while we wait.
            await asyncio.sleep(max(wait_seconds, 0.05))

    @property
    def max_per_minute(self) -> int:
        return self._max_per_minute


_llm_rate_limiter: AsyncRateLimiter | None = None


def get_llm_rate_limiter() -> AsyncRateLimiter:
    """
    Process-wide singleton. Every LLMAdapter instance shares this same
    limiter — creating a new LLMAdapter() per trial (as app/api/routes.py
    does) must NOT reset the budget, since the provider's RPM quota is
    tracked at the project level, not per adapter instance.
    """
    global _llm_rate_limiter
    if _llm_rate_limiter is None:
        from app.config import get_settings

        settings = get_settings()
        _llm_rate_limiter = AsyncRateLimiter(
            max_per_minute=settings.llm_max_requests_per_minute
        )
    return _llm_rate_limiter
