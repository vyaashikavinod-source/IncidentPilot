import threading
import time
from collections import defaultdict, deque


class RateLimitExceeded(RuntimeError):
    pass


class LocalRateLimiter:
    """Bounded in-process sliding-window limiter for the local sandbox."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                raise RateLimitExceeded("local endpoint rate limit exceeded")
            events.append(now)
