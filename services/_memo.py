"""Tiny thread-safe TTL memo for raw service helpers.

st.cache_data is main-thread only; raw helpers called from worker threads use
this instead so parallel batches don't repeat identical HTTP requests
(e.g. the same ESPN scoreboard for every match of one league/day).
"""
import time
import threading


class TTLMemo:
    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()

    def get_or_set(self, key, ttl: float, fn):
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[1] < ttl:
                return hit[0]
        value = fn()
        with self._lock:
            self._data[key] = (value, now)
        return value
