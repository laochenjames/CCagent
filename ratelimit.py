import threading
import time


class TokenBucketLimiter:
    """In-memory per-key token bucket rate limiter."""

    def __init__(self, rate_per_min=120, capacity=120):
        self.rate_per_sec = float(rate_per_min) / 60.0
        self.capacity = float(capacity)
        self._buckets = {}
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        t = now if now is not None else time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, t))
            elapsed = max(0.0, t - last)
            tokens = min(self.capacity, tokens + elapsed * self.rate_per_sec)
            if tokens < 1.0:
                self._buckets[key] = (tokens, t)
                return False
            self._buckets[key] = (tokens - 1.0, t)
            if len(self._buckets) > 10000:
                cutoff = t - 600.0
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] >= cutoff}
            return True

