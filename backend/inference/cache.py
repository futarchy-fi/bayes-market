"""Per-market CompileResult cache with invalidate-on-write semantics."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .contracts import CompileResult


@dataclass
class CacheStats:
    """Track hit/miss counters for the compile result cache."""

    hits: int = 0
    misses: int = 0

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate(),
        }


class CompileResultCache:
    """In-memory per-market cache for compiled inference artifacts.

    Each market stores at most one CompileResult, keyed by source_state_hash.
    Invalidation is explicit via invalidate(market_id) -- no TTL or LRU.
    """

    def __init__(self) -> None:
        self._entries: dict[str, CompileResult] = {}
        self._stats: dict[str, CacheStats] = {}
        self._lock = threading.Lock()

    def _ensure_stats(self, market_id: str) -> CacheStats:
        stats = self._stats.get(market_id)
        if stats is None:
            stats = CacheStats()
            self._stats[market_id] = stats
        return stats

    def get(self, market_id: str, source_state_hash: str) -> CompileResult | None:
        """Return cached CompileResult if hash matches, else None."""
        with self._lock:
            stats = self._ensure_stats(market_id)
            entry = self._entries.get(market_id)
            if entry is not None and entry.source_state_hash == source_state_hash:
                stats.hits += 1
                return entry
            stats.misses += 1
            return None

    def put(self, market_id: str, compile_result: CompileResult) -> None:
        """Store a CompileResult for a market, replacing any previous entry."""
        with self._lock:
            self._entries[market_id] = compile_result

    def invalidate(self, market_id: str) -> bool:
        """Remove the cached entry for a market. Returns True if an entry was removed."""
        with self._lock:
            return self._entries.pop(market_id, None) is not None

    def invalidate_all(self) -> int:
        """Remove all cached entries. Returns the count of entries removed."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def stats(self, market_id: str) -> CacheStats:
        """Return cache stats for a market."""
        with self._lock:
            return self._ensure_stats(market_id)

    def has_entry(self, market_id: str) -> bool:
        """Check if a cache entry exists for a market."""
        with self._lock:
            return market_id in self._entries

    def entry_count(self) -> int:
        """Return the number of cached entries."""
        with self._lock:
            return len(self._entries)


# Module-level singleton cache instance
COMPILE_RESULT_CACHE = CompileResultCache()


__all__ = [
    "COMPILE_RESULT_CACHE",
    "CacheStats",
    "CompileResultCache",
]
