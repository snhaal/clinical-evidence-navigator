"""
In-memory, fixed-window-ish rate limiter, keyed by client IP.

Documented limitation: this resets on process restart and does not
coordinate across multiple backend workers/instances. That's an accepted
trade-off for a $0-infrastructure, single-instance free-tier demo (Risk
register: "Free-tier LLM cost overrun on public demo" — mitigated here
by a hard per-IP cap, not by perfect distributed accuracy). If this ever
runs with >1 worker, move the counter into Postgres or Redis.
"""

import time
from collections import defaultdict
from threading import Lock


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 3600):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check_and_record(self, key: str) -> bool:
        """Returns True if the request is allowed (and records it); False if the caller is over the limit."""
        now = time.time()
        cutoff = now - self._window_seconds

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.pop(0)

            if len(hits) >= self._max_requests:
                return False

            hits.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.time()
        cutoff = now - self._window_seconds
        with self._lock:
            hits = [h for h in self._hits[key] if h >= cutoff]
            return max(0, self._max_requests - len(hits))


_limiter: InMemoryRateLimiter | None = None


def get_rate_limiter() -> InMemoryRateLimiter:
    global _limiter
    if _limiter is None:
        from app.config import get_settings

        settings = get_settings()
        _limiter = InMemoryRateLimiter(max_requests=settings.max_requests_per_ip_per_hour, window_seconds=3600)
    return _limiter
