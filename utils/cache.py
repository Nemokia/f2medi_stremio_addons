"""Small thread-safe TTL + max-size cache.

Used to memoize resolver results so repeated stream requests for the
same item do not re-run discovery. Cache failures must never break the
caller, so every public method swallows unexpected errors.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional

logger = logging.getLogger("f2m.cache")


class TTLCache:
    """In-memory cache with per-entry TTL and an LRU eviction cap."""

    def __init__(self, ttl_seconds: float, max_entries: int = 128) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> Optional[Any]:
        """Return the cached value or ``None`` if missing/expired."""
        try:
            with self._lock:
                entry = self._data.get(key)
                if entry is None:
                    return None
                expires_at, value = entry
                if expires_at < time.monotonic():
                    del self._data[key]
                    return None
                self._data.move_to_end(key)
                return value
        except Exception as exc:  # cache must never break the resolver
            logger.debug("[CACHE] get failed: %s", exc)
            return None

    def set(self, key: Hashable, value: Any) -> None:
        """Store ``value`` under ``key``; evict oldest when full."""
        try:
            with self._lock:
                self._data[key] = (time.monotonic() + self._ttl, value)
                self._data.move_to_end(key)
                while len(self._data) > self._max_entries:
                    self._data.popitem(last=False)
        except Exception as exc:
            logger.debug("[CACHE] set failed: %s", exc)

    def get_or_set(self, key: Hashable, factory: Callable[[], Any]) -> Any:
        """Return cached value, otherwise compute via ``factory`` and store.

        The factory runs outside the lock so slow resolvers don't block
        other threads.
        """
        cached = self.get(key)
        if cached is not None:
            logger.debug("[CACHE] hit key=%s", key)
            return cached
        value = factory()
        if value is not None:
            self.set(key, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
