"""In-memory sliding-window rate limiting for the public chat endpoint.

Per-process only — good for a single Cloud Run/ECS instance at MVP scale.
Phase 2 (multi-instance): swap the store for Redis behind the same `allow()`
interface; nothing else changes.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float = 60.0) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """True if the event is admitted; False if the key is over its limit.
        A max_events of 0 or less disables limiting entirely."""
        if self.max_events <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                bucket = deque()
                self._events[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_events:
                return False
            bucket.append(now)
            # Opportunistic purge so abandoned keys don't accumulate forever.
            if len(self._events) > 10_000:
                stale = [k for k, dq in self._events.items() if not dq or dq[-1] <= cutoff]
                for k in stale:
                    del self._events[k]
            return True
