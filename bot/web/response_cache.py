"""
Per-process TTL JSON payload cache for read-only API endpoints.

This cache is per-process (per Flask worker).  Multiple Gunicorn workers or
separate containers do not share a single cache; for cross-worker caching,
use Redis or redesign endpoints to use SSE/push.

Typical usage in a Flask route::

    cache = _get_response_cache()  # from route_helpers or app.extensions
    payload = cache.get_or_set("mykey", ttl=1.5, producer=my_service.get_status)
    return jsonify(payload)
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

logger: Any = None  # imported lazily to avoid circular imports


class _CacheEntry:
    """A single cached payload with an absolute expiration time."""

    __slots__ = ("payload", "expires_at")

    def __init__(self, payload: Any, expires_at: float) -> None:
        self.payload = payload
        self.expires_at = expires_at


class ResponseCache:
    """Thread-safe TTL cache for JSON-serializable API payloads.

    Each key has its own lock so simultaneous misses for different keys
    do not contend.  Expired entries are purged opportunistically on
    insertion.  A maximum entry count prevents unbounded growth.

    Args:
        max_entries: Hard limit on stored entries before pruning begins.
        _time_func: Callable returning the current monotonic time.  Exposed
            as a parameter for test injection (default *time.monotonic*).
    """

    def __init__(
        self,
        max_entries: int = 256,
        _time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._time_func = _time_func
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_set(
        self,
        key: str,
        ttl: float,
        producer: Callable[[], Any],
    ) -> Any:
        """Return cached payload or produce and cache it.

        Uses double-checked locking per key so that concurrent callers for
        the same key do not all run *producer* simultaneously.

        Args:
            key: Unique cache key.
            ttl: Time-to-live in seconds.
            producer: Zero-argument callable returning the JSON-serializable
                payload.  Called at most once per TTL window when concurrent
                callers share the same key.  If *producer* raises, the
                exception propagates and nothing is cached.

        Returns:
            The cached or freshly produced payload.

        Raises:
            Exception: Re-raises any exception from *producer*.
        """
        now = self._time_func()
        entry = self._entries.get(key)
        if entry is not None and now < entry.expires_at:
            return entry.payload

        key_lock = self._get_key_lock(key)
        with key_lock:
            # Double-check after acquiring the per-key lock.
            entry = self._entries.get(key)
            if entry is not None and now < entry.expires_at:
                return entry.payload

            payload = producer()
            expires_at = now + ttl
            self._entries[key] = _CacheEntry(payload, expires_at)
            self._maybe_prune(now)
            return payload

    def invalidate(self, key: str | None = None) -> None:
        """Remove one key or clear the entire cache."""
        if key is not None:
            self._entries.pop(key, None)
        else:
            self._entries.clear()

    @property
    def size(self) -> int:
        """Return the current number of cached entries."""
        return len(self._entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_key_lock(self, key: str) -> threading.Lock:
        with self._key_locks_lock:
            if key not in self._key_locks:
                self._key_locks[key] = threading.Lock()
            return self._key_locks[key]

    def _maybe_prune(self, now: float) -> None:
        if len(self._entries) <= self._max_entries:
            return

        # Remove expired entries first.
        expired = [k for k, e in self._entries.items() if now >= e.expires_at]
        for k in expired:
            del self._entries[k]

        # If still over the limit, remove the oldest entries.
        over = len(self._entries) - self._max_entries
        if over > 0:
            sorted_keys = sorted(
                self._entries.keys(),
                key=lambda k: self._entries[k].expires_at,
            )
            # Remove at least *over* entries, but at least a quarter of the
            # current size so a single prune is not trivially wasted.
            remove_count = max(over, len(self._entries) // 4)
            for k in sorted_keys[:remove_count]:
                del self._entries[k]
