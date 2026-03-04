from dataclasses import dataclass
from time import time
from typing import Dict, Tuple

@dataclass
class Bucket:
    reset_at: float
    count: int

class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: Dict[Tuple[str,str], Bucket] = {}

    def hit(self, key: str, action: str, limit: int, window_seconds: int = 60) -> bool:
        now = time()
        k = (key, action)
        b = self._buckets.get(k)
        if not b or now >= b.reset_at:
            self._buckets[k] = Bucket(reset_at=now + window_seconds, count=1)
            return True
        if b.count >= limit:
            return False
        b.count += 1
        return True

rate_limiter = InMemoryRateLimiter()
