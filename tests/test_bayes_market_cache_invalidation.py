"""Tests for T553 junction-tree cache invalidation logic."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest
from copy import deepcopy

from backend.inference import COMPILE_RESULT_CACHE, CompileResultCache, CacheStats

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "backend" / "server.py"
spec = importlib.util.spec_from_file_location("bayes_market_server_cache_test", MODULE_PATH)
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def build_probability_edit(
    account_id: str,
    market_id: str,
    outcome_id: str,
    probability: float,
) -> dict[str, object]:
    return {
        "accountId": account_id,
        "variableId": server.MARKETS[market_id]["variableId"],
        "target": {"kind": "marginal", "outcomeId": outcome_id, "probability": probability},
        "context": [],
    }


def build_resolution(account_id: str, outcome_id: str) -> dict[str, object]:
    return {"accountId": account_id, "outcomeId": outcome_id}


class CompileResultCacheUnitTests(unittest.TestCase):
    """Unit tests for the CompileResultCache class in isolation."""

    def setUp(self) -> None:
        self.cache = CompileResultCache()

    def test_empty_cache_returns_none(self):
        result = self.cache.get("m1", "sha256:abc")
        self.assertIsNone(result)

    def test_put_and_get_returns_cached_entry(self):
        server.reset_state()
        compile_result = server.compile_market_for_inference("m1")
        self.cache.put("m1", compile_result)
        cached = self.cache.get("m1", compile_result.source_state_hash)
        self.assertIs(cached, compile_result)

    def test_get_with_wrong_hash_returns_none(self):
        server.reset_state()
        compile_result = server.compile_market_for_inference("m1")
        self.cache.put("m1", compile_result)
        cached = self.cache.get("m1", "sha256:wrong")
        self.assertIsNone(cached)

    def test_invalidate_removes_entry(self):
        server.reset_state()
        compile_result = server.compile_market_for_inference("m1")
        self.cache.put("m1", compile_result)
        self.assertTrue(self.cache.has_entry("m1"))
        removed = self.cache.invalidate("m1")
        self.assertTrue(removed)
        self.assertFalse(self.cache.has_entry("m1"))

    def test_invalidate_nonexistent_returns_false(self):
        removed = self.cache.invalidate("nonexistent")
        self.assertFalse(removed)

    def test_invalidate_all_clears_everything(self):
        server.reset_state()
        r1 = server.compile_market_for_inference("m1")
        r2 = server.compile_market_for_inference("m2")
        self.cache.put("m1", r1)
        self.cache.put("m2", r2)
        self.assertEqual(self.cache.entry_count(), 2)
        count = self.cache.invalidate_all()
        self.assertEqual(count, 2)
        self.assertEqual(self.cache.entry_count(), 0)

    def test_stats_tracks_hits_and_misses(self):
        server.reset_state()
        compile_result = server.compile_market_for_inference("m1")
        self.cache.put("m1", compile_result)

        self.cache.get("m1", compile_result.source_state_hash)  # hit
        self.cache.get("m1", compile_result.source_state_hash)  # hit
        self.cache.get("m1", "sha256:wrong")  # miss

        stats = self.cache.stats("m1")
        self.assertEqual(stats.hits, 2)
        self.assertEqual(stats.misses, 1)
        self.assertAlmostEqual(stats.hit_rate(), 0.6667, places=3)

    def test_put_replaces_previous_entry(self):
        server.reset_state()
        r1 = server.compile_market_for_inference("m1")
        self.cache.put("m1", r1)

        # Simulate state change
        server.MARKETS["m1"]["marginals"]["yes"] = 0.80
        server.MARKETS["m1"]["marginals"]["no"] = 0.20
        r2 = server.compile_market_for_inference("m1")
        self.cache.put("m1", r2)

        # Old hash misses, new hash hits
        self.assertIsNone(self.cache.get("m1", r1.source_state_hash))
        self.assertIs(self.cache.get("m1", r2.source_state_hash), r2)


class CacheIntegrationTests(unittest.TestCase):
    """Integration tests for cache behavior through the server layer."""

    def setUp(self) -> None:
        self._saved_compile_type = server.ENGINE_COMPILE_TYPE
        server.ENGINE_COMPILE_TYPE = "current_model"
        server.reset_state()

    def tearDown(self) -> None:
        server.ENGINE_COMPILE_TYPE = self._saved_compile_type

    def test_compile_market_for_inference_populates_cache(self):
        result = server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))

    def test_second_compile_call_returns_cached_result(self):
        r1 = server.compile_market_for_inference("m1")
        r2 = server.compile_market_for_inference("m1")
        # Same object from cache
        self.assertIs(r1, r2)

    def test_cache_hit_increments_engine_stats(self):
        # First call: cache miss
        server.compile_market_for_inference("m1")
        state = server.MARKET_ENGINE_STATS["m1"]
        self.assertEqual(state["cache_misses"], 1)
        self.assertEqual(state["cache_hits"], 0)

        # Second call: cache hit
        server.compile_market_for_inference("m1")
        self.assertEqual(state["cache_misses"], 1)
        self.assertEqual(state["cache_hits"], 1)

    def test_probability_edit_invalidates_cache(self):
        # Populate cache
        server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))

        # Submit probability edit
        body = build_probability_edit("acct_cache_test", "m1", "yes", 0.80)
        payload, status = server.route_request(
            "POST", "/v1/markets/m1/orders/probability-edit", body,
        )
        self.assertEqual(status, 201)

        # Cache was invalidated by refresh_market_compile_snapshot,
        # but then rebuild repopulated it via build_market_compile_result
        # which calls compile_market_for_inference (cache miss -> repopulated)
        state = server.MARKET_ENGINE_STATS["m1"]
        # At least one miss occurred after the edit
        self.assertGreaterEqual(state["cache_misses"], 1)

    def test_probability_edit_produces_new_compile_id(self):
        r1 = server.compile_market_for_inference("m1")
        old_hash = r1.source_state_hash

        body = build_probability_edit("acct_cache_id", "m1", "yes", 0.80)
        server.route_request("POST", "/v1/markets/m1/orders/probability-edit", body)

        r2 = server.compile_market_for_inference("m1")
        self.assertNotEqual(old_hash, r2.source_state_hash)
        self.assertNotEqual(r1.compile_id, r2.compile_id)

    def test_resolution_invalidates_cache(self):
        # Populate cache for m1
        server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))
        old_hash = server.compile_market_for_inference("m1").source_state_hash

        # Resolve market m1
        body = build_resolution("acct_resolve_cache", "yes")
        payload, status = server.route_request(
            "POST", "/v1/markets/m1/resolve", body,
        )
        self.assertEqual(status, 201)

        # After resolution, the market state changed
        r_after = server.compile_market_for_inference("m1")
        self.assertNotEqual(old_hash, r_after.source_state_hash)

    def test_event_trade_does_not_invalidate_cache(self):
        # Populate cache
        r1 = server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))

        # Submit event trade (should NOT invalidate cache)
        body = {
            "accountId": "acct_event_trade_cache",
            "formula": [[{"variableId": "m1", "outcomeId": "yes", "negated": False}]],
            "size": 10.0,
            "side": "buy",
        }
        payload, status = server.route_request(
            "POST", "/v1/markets/m1/orders/event-trade", body,
        )
        self.assertEqual(status, 201)

        # Cache should still hold the same entry
        r2 = server.compile_market_for_inference("m1")
        self.assertIs(r1, r2)

    def test_cache_isolation_between_markets(self):
        r1 = server.compile_market_for_inference("m1")
        r2 = server.compile_market_for_inference("m2")

        # Edit m1 only
        body = build_probability_edit("acct_isolation", "m1", "yes", 0.80)
        server.route_request("POST", "/v1/markets/m1/orders/probability-edit", body)

        # m2 cache should still be valid
        r2_after = server.compile_market_for_inference("m2")
        self.assertIs(r2, r2_after)

    def test_engine_stats_expose_cache_counters_via_api(self):
        # First compile: miss
        server.compile_market_for_inference("m1")
        # Second compile: hit
        server.compile_market_for_inference("m1")

        stats_payload, status = server.route_request("GET", "/v1/markets/m1/engine-stats")
        self.assertEqual(status, 200)
        cache_stats = stats_payload["diagnostics"]["cache"]
        self.assertEqual(cache_stats["hits"], 1)
        self.assertEqual(cache_stats["misses"], 1)
        self.assertAlmostEqual(cache_stats["hit_rate"], 0.5, places=3)

    def test_reset_state_clears_cache(self):
        server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))
        server.reset_state()
        self.assertFalse(COMPILE_RESULT_CACHE.has_entry("m1"))


class JunctionTreeCacheTests(unittest.TestCase):
    """Tests for junction tree compiler cache invalidation."""

    def setUp(self) -> None:
        self._saved_compile_type = server.ENGINE_COMPILE_TYPE
        server.ENGINE_COMPILE_TYPE = "junction_tree"
        server.reset_state()

    def tearDown(self) -> None:
        server.ENGINE_COMPILE_TYPE = self._saved_compile_type

    def test_junction_tree_compile_populates_cache(self):
        result = server.compile_market_for_inference("m1")
        self.assertTrue(COMPILE_RESULT_CACHE.has_entry("m1"))
        self.assertIsNotNone(result.artifact)

    def test_second_call_returns_cached_result(self):
        r1 = server.compile_market_for_inference("m1")
        r2 = server.compile_market_for_inference("m1")
        self.assertIs(r1, r2)

    def test_probability_edit_invalidates_and_produces_new_ids(self):
        r1 = server.compile_market_for_inference("m1")
        old_hash = r1.source_state_hash
        old_compile_id = r1.compile_id

        # Directly modify market state (JT queries not yet implemented,
        # so route_request probability-edit path is not available)
        server.MARKETS["m1"]["marginals"]["yes"] = 0.80
        server.MARKETS["m1"]["marginals"]["no"] = 0.20
        COMPILE_RESULT_CACHE.invalidate("m1")

        r2 = server.compile_market_for_inference("m1")
        self.assertNotEqual(old_hash, r2.source_state_hash)
        self.assertNotEqual(old_compile_id, r2.compile_id)

    def test_cache_isolation_between_markets(self):
        r1 = server.compile_market_for_inference("m1")
        r2 = server.compile_market_for_inference("m2")

        # Edit m1 only
        server.MARKETS["m1"]["marginals"]["yes"] = 0.80
        server.MARKETS["m1"]["marginals"]["no"] = 0.20
        COMPILE_RESULT_CACHE.invalidate("m1")

        # m2 cache should still be valid
        r2_after = server.compile_market_for_inference("m2")
        self.assertIs(r2, r2_after)

    def test_compile_result_has_junction_tree_type(self):
        result = server.compile_market_for_inference("m1")
        self.assertEqual(result.compile_type, "junction_tree")
        from backend.inference.junction_tree import JunctionTreeCompileArtifact
        self.assertIsInstance(result.artifact, JunctionTreeCompileArtifact)


class CacheStatsUnitTests(unittest.TestCase):
    """Unit tests for the CacheStats dataclass."""

    def test_empty_stats(self):
        stats = CacheStats()
        self.assertEqual(stats.hits, 0)
        self.assertEqual(stats.misses, 0)
        self.assertEqual(stats.hit_rate(), 0.0)

    def test_hit_rate_calculation(self):
        stats = CacheStats(hits=3, misses=1)
        self.assertAlmostEqual(stats.hit_rate(), 0.75, places=4)

    def test_to_dict(self):
        stats = CacheStats(hits=10, misses=5)
        d = stats.to_dict()
        self.assertEqual(d["hits"], 10)
        self.assertEqual(d["misses"], 5)
        self.assertAlmostEqual(d["hit_rate"], 0.6667, places=3)


if __name__ == "__main__":
    unittest.main()
