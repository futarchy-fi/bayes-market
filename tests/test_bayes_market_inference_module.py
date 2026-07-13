from __future__ import annotations

import importlib.util
import pathlib
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

from backend.inference import (
    AtomicEventQueryResult,
    CURRENT_MODEL_COMPILER,
    CURRENT_MODEL_QUERY_BACKEND,
    CURRENT_MODEL_EXACT_ELIGIBILITY_REASON,
    CacheInvalidationManager,
    CliqueSummary,
    CompileResult,
    CurrentModelCompileArtifact,
    CurrentModelCompiler,
    DEFAULT_ENGINE_CONFIG,
    EngineConfig,
    InferenceQueryError,
    InferenceUnsupportedQueryError,
    InvalidationResult,
    MarginalQueryResult,
    compile_current_market_artifact,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "backend" / "server.py"

server_spec = importlib.util.spec_from_file_location("bayes_market_server_for_inference_module_test", SERVER_PATH)
server = importlib.util.module_from_spec(server_spec)
assert server_spec is not None
assert server_spec.loader is not None
server_spec.loader.exec_module(server)


class BayesMarketInferenceModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def build_compile_result(
        self,
        market_id: str = "m1",
        *,
        conditional_marginals: dict[str, dict[str, float]] | None = None,
    ) -> CompileResult:
        return CURRENT_MODEL_COMPILER.compile_result(
            market_snapshot=deepcopy(server.MARKETS[market_id]),
            conditional_marginals=conditional_marginals,
            last_updated="2026-04-08T00:00:00Z",
        )

    def test_default_engine_config_matches_public_identity(self):
        self.assertIsInstance(DEFAULT_ENGINE_CONFIG, EngineConfig)
        self.assertEqual(DEFAULT_ENGINE_CONFIG.mode, "EXACT")
        self.assertEqual(DEFAULT_ENGINE_CONFIG.backend, "junction_tree")
        self.assertEqual(DEFAULT_ENGINE_CONFIG.version, "0.1.0")
        self.assertEqual(DEFAULT_ENGINE_CONFIG.precision, "float64")
        self.assertEqual(DEFAULT_ENGINE_CONFIG.compile_type, "junction_tree")
        self.assertEqual(DEFAULT_ENGINE_CONFIG.inference_sample_limit, 100)

        with self.assertRaises(FrozenInstanceError):
            DEFAULT_ENGINE_CONFIG.mode = "APPROX"  # type: ignore[misc]

    def test_compile_and_query_contracts_are_immutable_and_normalized(self):
        clique = CliqueSummary(id="m1-c1", nodes=["beta", "alpha"], size=2, states=6)
        compile_result = CompileResult(
            compile_id="comp-123456789abc",
            compile_type="junction_tree",
            source_state_hash="sha256:abc",
            cliques=[clique],
            compile_time_ms=1.25,
            memory_bytes=320,
            last_updated="2026-04-08T00:00:00Z",
        )
        marginal_result = MarginalQueryResult(
            marginals={"yes": 0.6, "no": 0.4},
            runtime_ms=0.5,
            cache_hit=True,
            compile_id=compile_result.compile_id,
            metadata={"source": "test"},
        )
        event_result = AtomicEventQueryResult(
            variable_id="m1",
            outcome_id="yes",
            probability=0.6,
            runtime_ms=0.25,
            cache_hit=False,
            compile_id=compile_result.compile_id,
        )

        self.assertEqual(clique.nodes, ("beta", "alpha"))
        self.assertEqual(clique.to_dict(), {"id": "m1-c1", "nodes": ["beta", "alpha"], "size": 2, "states": 6})
        self.assertEqual(compile_result.cliques, (clique,))
        self.assertEqual(marginal_result.marginals, {"yes": 0.6, "no": 0.4})
        self.assertEqual(marginal_result.metadata, {"source": "test"})
        self.assertEqual(event_result.variable_id, "m1")
        self.assertEqual(event_result.outcome_id, "yes")
        self.assertEqual(event_result.probability, 0.6)

        with self.assertRaises(FrozenInstanceError):
            compile_result.memory_bytes = 0  # type: ignore[misc]

    def test_inference_errors_expose_internal_metadata(self):
        error = InferenceUnsupportedQueryError(
            "Only atomic literals are supported",
            details={"supportedShape": "single_clause_single_literal_non_negated"},
        )

        self.assertEqual(error.code, "inference_unsupported_query")
        self.assertEqual(error.message, "Only atomic literals are supported")
        self.assertEqual(error.details, {"supportedShape": "single_clause_single_literal_non_negated"})

    def test_server_can_import_inference_package_from_file_path(self):
        self.assertEqual(server.ENGINE_CONFIG, DEFAULT_ENGINE_CONFIG)
        self.assertEqual(server.ENGINE_MODE, DEFAULT_ENGINE_CONFIG.mode)
        self.assertEqual(server.ENGINE_BACKEND, DEFAULT_ENGINE_CONFIG.backend)

        payload, status = server.route_request("GET", "/v1/markets/m1/engine-stats")

        self.assertEqual(status, 200)
        self.assertEqual(payload["engine"]["mode"], DEFAULT_ENGINE_CONFIG.mode)
        self.assertEqual(payload["engine"]["backend"], DEFAULT_ENGINE_CONFIG.backend)
        self.assertEqual(payload["engine"]["version"], DEFAULT_ENGINE_CONFIG.version)
        self.assertEqual(payload["engine"]["precision"], DEFAULT_ENGINE_CONFIG.precision)

    def test_record_market_engine_request_discards_samples_when_limit_is_zero(self):
        original_config = server.ENGINE_CONFIG
        server.ENGINE_CONFIG = EngineConfig(
            mode=original_config.mode,
            backend=original_config.backend,
            version=original_config.version,
            precision=original_config.precision,
            compile_type=original_config.compile_type,
            inference_sample_limit=0,
        )

        try:
            server.record_market_engine_request("m1", 1.234, error=False)
            server.record_market_engine_request("m1", 5.678, error=True)

            state = server.MARKET_ENGINE_STATS["m1"]
            self.assertEqual(state["request_count"], 2)
            self.assertEqual(state["error_count"], 1)
            self.assertEqual(state["inference_samples_ms"], [])
        finally:
            server.ENGINE_CONFIG = original_config
            server.reset_state()

    def test_current_model_compiler_builds_truthful_singleton_artifact(self):
        market_snapshot = deepcopy(server.MARKETS["m1"])
        conditional_marginals = {
            "autonomous_ai_coding_deployment_2028=yes": {
                "yes": 0.7,
                "no": 0.3,
            }
        }

        artifact = compile_current_market_artifact(
            market_snapshot=market_snapshot,
            conditional_marginals=conditional_marginals,
        )

        self.assertIsInstance(artifact, CurrentModelCompileArtifact)
        self.assertEqual(artifact.market_id, "m1")
        self.assertEqual(artifact.variable_id, server.MARKETS["m1"]["variableId"])
        self.assertEqual(
            artifact.source_state_hash,
            server.canonical_json_hash(
                {
                    "market": market_snapshot,
                    "conditionalMarginals": conditional_marginals,
                }
            ),
        )
        self.assertEqual(artifact.compile_id, f"comp-{artifact.source_state_hash.split(':', 1)[-1][:12]}")
        self.assertEqual(artifact.compile_type, DEFAULT_ENGINE_CONFIG.compile_type)
        self.assertEqual(
            artifact.cliques,
            (
                CliqueSummary(
                    id="m1-c1",
                    nodes=(server.MARKETS["m1"]["variableId"],),
                    size=1,
                    states=len(server.MARKETS["m1"]["outcomes"]),
                ),
            ),
        )
        self.assertEqual(artifact.junction_tree_width, 0)
        self.assertTrue(artifact.exact_eligible)
        self.assertEqual(artifact.eligibility_reason, CURRENT_MODEL_EXACT_ELIGIBILITY_REASON)
        self.assertEqual(artifact.memory_bytes, 128)
        self.assertEqual(artifact.source_state_payload()["conditionalMarginals"], conditional_marginals)
        self.assertEqual(
            dict(artifact.conditional_marginals["autonomous_ai_coding_deployment_2028=yes"]),
            {"yes": 0.7, "no": 0.3},
        )

    def test_current_model_compiler_is_deterministic_for_equal_snapshots(self):
        market_snapshot = deepcopy(server.MARKETS["m2"])
        conditional_marginals = {
            "frontier_capability_breakthrough_2028=yes": {
                "yes": 0.2,
                "no": 0.8,
            }
        }

        first = compile_current_market_artifact(
            market_snapshot=market_snapshot,
            conditional_marginals=conditional_marginals,
        )
        second = compile_current_market_artifact(
            market_snapshot=deepcopy(server.MARKETS["m2"]),
            conditional_marginals=deepcopy(conditional_marginals),
        )

        self.assertEqual(first, second)

    def test_current_model_compiler_changes_hash_when_source_state_changes(self):
        baseline_market = deepcopy(server.MARKETS["m1"])
        updated_market = deepcopy(server.MARKETS["m1"])
        updated_market["marginals"] = {"yes": 0.55, "no": 0.45}

        baseline = compile_current_market_artifact(market_snapshot=baseline_market)
        updated = compile_current_market_artifact(market_snapshot=updated_market)

        self.assertNotEqual(baseline.source_state_hash, updated.source_state_hash)
        self.assertNotEqual(baseline.compile_id, updated.compile_id)

    def test_current_model_compiler_freezes_nested_state(self):
        artifact = compile_current_market_artifact(market_snapshot=deepcopy(server.MARKETS["m1"]))

        with self.assertRaises(TypeError):
            artifact.marginals["yes"] = 0.4  # type: ignore[index]

        with self.assertRaises(TypeError):
            artifact.source_state_inputs["market"]["marginals"]["yes"] = 0.4  # type: ignore[index]

        with self.assertRaises(TypeError):
            artifact.outcomes[0]["id"] = "maybe"  # type: ignore[index]

        with self.assertRaises(FrozenInstanceError):
            artifact.market_id = "m2"  # type: ignore[misc]

    def test_current_model_compiler_can_emit_compile_result_with_artifact(self):
        compiler = CurrentModelCompiler()
        compile_result = compiler.compile_result(
            market_snapshot=deepcopy(server.MARKETS["m1"]),
            compile_time_ms=1.25,
            last_updated="2026-04-08T00:00:00Z",
        )

        self.assertIsInstance(compile_result, CompileResult)
        self.assertIsInstance(compile_result.artifact, CurrentModelCompileArtifact)
        self.assertEqual(compile_result.compile_id, compile_result.artifact.compile_id)
        self.assertEqual(compile_result.compile_type, compile_result.artifact.compile_type)
        self.assertEqual(compile_result.source_state_hash, compile_result.artifact.source_state_hash)
        self.assertEqual(compile_result.cliques, compile_result.artifact.cliques)
        self.assertEqual(compile_result.memory_bytes, compile_result.artifact.memory_bytes)
        self.assertEqual(compile_result.compile_time_ms, 1.25)
        self.assertEqual(compile_result.last_updated, "2026-04-08T00:00:00Z")

    def test_current_model_query_backend_returns_unconditional_marginals(self):
        compile_result = self.build_compile_result()

        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(compile_result)

        self.assertEqual(result.marginals, dict(server.MARKETS["m1"]["marginals"]))
        self.assertEqual(result.compile_id, compile_result.compile_id)
        self.assertFalse(result.cache_hit)
        self.assertEqual(result.metadata["contextKey"], "")
        self.assertEqual(result.metadata["resolutionSource"], "unconditional")
        self.assertEqual(result.metadata["eligibilityReason"], CURRENT_MODEL_EXACT_ELIGIBILITY_REASON)

    def test_current_model_query_backend_canonicalizes_context_keys_for_conditionals(self):
        conditional_marginals = {
            "autonomous_ai_coding_deployment_2028=yes|frontier_ai_governance_regime_2030=no": {
                "yes": 0.7,
                "no": 0.3,
            }
        }
        compile_result = self.build_compile_result(conditional_marginals=conditional_marginals)

        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_result,
            context={
                "frontier_ai_governance_regime_2030": "no",
                "autonomous_ai_coding_deployment_2028": "yes",
            },
        )

        self.assertEqual(
            result.marginals,
            conditional_marginals["autonomous_ai_coding_deployment_2028=yes|frontier_ai_governance_regime_2030=no"],
        )
        self.assertEqual(result.metadata["contextKey"], "autonomous_ai_coding_deployment_2028=yes|frontier_ai_governance_regime_2030=no")
        self.assertEqual(result.metadata["resolutionSource"], "conditional")

    def test_current_model_query_backend_falls_back_to_unconditional_marginals_for_unknown_context(self):
        conditional_marginals = {
            "autonomous_ai_coding_deployment_2028=yes": {
                "yes": 0.7,
                "no": 0.3,
            }
        }
        compile_result = self.build_compile_result(conditional_marginals=conditional_marginals)

        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_result,
            context={"autonomous_ai_coding_deployment_2028": "no"},
        )

        self.assertEqual(result.marginals, dict(server.MARKETS["m1"]["marginals"]))
        self.assertEqual(result.metadata["contextKey"], "autonomous_ai_coding_deployment_2028=no")
        self.assertEqual(result.metadata["resolutionSource"], "unconditional")

    def test_current_model_query_backend_returns_atomic_event_probability(self):
        compile_result = self.build_compile_result()

        result = CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(
            compile_result,
            variable_id=server.MARKETS["m1"]["variableId"],
            outcome_id="yes",
        )

        self.assertEqual(result.variable_id, server.MARKETS["m1"]["variableId"])
        self.assertEqual(result.outcome_id, "yes")
        self.assertEqual(result.probability, server.MARKETS["m1"]["marginals"]["yes"])
        self.assertEqual(result.compile_id, compile_result.compile_id)
        self.assertFalse(result.cache_hit)
        self.assertEqual(result.metadata["resolutionSource"], "unconditional")

    def test_current_model_query_backend_rejects_other_variable_ids(self):
        compile_result = self.build_compile_result()

        with self.assertRaises(InferenceUnsupportedQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(
                compile_result,
                variable_id=server.MARKETS["m2"]["variableId"],
                outcome_id="yes",
            )

    def test_current_model_query_backend_rejects_unknown_outcome_ids(self):
        compile_result = self.build_compile_result()

        with self.assertRaises(InferenceQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(
                compile_result,
                variable_id=server.MARKETS["m1"]["variableId"],
                outcome_id="maybe",
            )

    def test_current_model_query_backend_rejects_negated_atomic_event_queries(self):
        compile_result = self.build_compile_result()

        with self.assertRaises(InferenceUnsupportedQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(
                compile_result,
                variable_id=server.MARKETS["m1"]["variableId"],
                outcome_id="yes",
                negated=True,
            )

    def test_current_model_query_backend_requires_current_model_artifact(self):
        compile_result = replace(self.build_compile_result(), artifact=None)

        with self.assertRaises(InferenceQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_marginals(compile_result)

    def test_current_model_query_backend_rejects_mismatched_compile_result_metadata(self):
        compile_result = replace(self.build_compile_result(), compile_id="comp-mismatch")

        with self.assertRaises(InferenceQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_marginals(compile_result)

    def test_current_model_query_backend_rejects_ineligible_artifacts(self):
        compile_result = self.build_compile_result()
        ineligible_artifact = replace(
            compile_result.artifact,
            exact_eligible=False,
            eligibility_reason="approximate_only",
        )

        with self.assertRaises(InferenceUnsupportedQueryError):
            CURRENT_MODEL_QUERY_BACKEND.query_marginals(
                replace(compile_result, artifact=ineligible_artifact),
            )

    def test_current_model_compiler_rejects_malformed_market_snapshots(self):
        missing_variable_id = deepcopy(server.MARKETS["m1"])
        del missing_variable_id["variableId"]

        missing_outcome_probability = deepcopy(server.MARKETS["m1"])
        missing_outcome_probability["marginals"] = {"yes": 1.0}

        with self.assertRaises(server.InferenceCompileError):
            compile_current_market_artifact(market_snapshot=missing_variable_id)

        with self.assertRaises(server.InferenceCompileError):
            compile_current_market_artifact(market_snapshot=missing_outcome_probability)


class CacheInvalidationManagerTests(unittest.TestCase):
    def test_hash_match_returns_cache_hit_and_skips_recompile(self):
        manager = CacheInvalidationManager()
        # First call is always a miss (no previous hash).
        manager.check("m1", "sha256:aaa")
        result = manager.check("m1", "sha256:aaa")

        self.assertIsInstance(result, InvalidationResult)
        self.assertFalse(result.needs_recompile)
        self.assertFalse(result.clear_conditional_marginals)
        self.assertEqual(result.previous_hash, "sha256:aaa")
        self.assertEqual(result.current_hash, "sha256:aaa")

    def test_hash_mismatch_returns_cache_miss_and_triggers_recompile(self):
        manager = CacheInvalidationManager()
        result = manager.check("m1", "sha256:aaa")

        self.assertTrue(result.needs_recompile)
        self.assertTrue(result.clear_conditional_marginals)
        self.assertIsNone(result.previous_hash)
        self.assertEqual(result.current_hash, "sha256:aaa")

        result2 = manager.check("m1", "sha256:bbb")
        self.assertTrue(result2.needs_recompile)
        self.assertTrue(result2.clear_conditional_marginals)
        self.assertEqual(result2.previous_hash, "sha256:aaa")
        self.assertEqual(result2.current_hash, "sha256:bbb")

    def test_conditional_marginals_flagged_for_clearing_on_state_change(self):
        manager = CacheInvalidationManager()
        manager.check("m1", "sha256:before")
        result = manager.check("m1", "sha256:after")

        self.assertTrue(result.clear_conditional_marginals)
        self.assertTrue(result.needs_recompile)

    def test_counter_tracking_across_multiple_invalidation_calls(self):
        manager = CacheInvalidationManager()

        # First call — miss (no previous hash)
        manager.check("m1", "sha256:aaa")
        self.assertEqual(manager.cache_hits, 0)
        self.assertEqual(manager.cache_misses, 1)

        # Same hash — hit
        manager.check("m1", "sha256:aaa")
        self.assertEqual(manager.cache_hits, 1)
        self.assertEqual(manager.cache_misses, 1)

        # Different hash — miss
        manager.check("m1", "sha256:bbb")
        self.assertEqual(manager.cache_hits, 1)
        self.assertEqual(manager.cache_misses, 2)

        # Same hash again — hit
        manager.check("m1", "sha256:bbb")
        self.assertEqual(manager.cache_hits, 2)
        self.assertEqual(manager.cache_misses, 2)

        # Different market — miss (no previous for m2)
        manager.check("m2", "sha256:xxx")
        self.assertEqual(manager.cache_hits, 2)
        self.assertEqual(manager.cache_misses, 3)

    def test_reset_clears_hashes_and_counters(self):
        manager = CacheInvalidationManager()
        manager.check("m1", "sha256:aaa")
        manager.check("m1", "sha256:aaa")
        self.assertEqual(manager.cache_hits, 1)
        self.assertEqual(manager.cache_misses, 1)

        manager.reset()
        self.assertEqual(manager.cache_hits, 0)
        self.assertEqual(manager.cache_misses, 0)

        # After reset, same hash is a miss (no stored hash).
        result = manager.check("m1", "sha256:aaa")
        self.assertTrue(result.needs_recompile)
        self.assertEqual(manager.cache_misses, 1)


if __name__ == "__main__":
    unittest.main()
