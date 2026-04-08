from __future__ import annotations

import importlib.util
import pathlib
import unittest
from dataclasses import FrozenInstanceError

from backend.inference import (
    AtomicEventQueryResult,
    CliqueSummary,
    CompileResult,
    DEFAULT_ENGINE_CONFIG,
    EngineConfig,
    InferenceUnsupportedQueryError,
    MarginalQueryResult,
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


if __name__ == "__main__":
    unittest.main()
