"""Graph-projection extras: CPT parents and whole-graph context conditioning."""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "backend" / "server.py"
_IMPORT_COUNTER = itertools.count()


def market_record(market_id: str, variable_id: str, *, marginals: dict[str, float]) -> dict[str, object]:
    return {
        "id": market_id,
        "title": f"Graph Context {market_id}",
        "description": "Graph context test fixture.",
        "variableId": variable_id,
        "status": "active",
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": marginals,
        "liquidity": 1000.0,
        "volume": 0.0,
        "created_at": "2026-07-04T00:00:00Z",
        "expires_at": "2035-01-01T00:00:00Z",
    }


class GraphContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.previous_seed_path = os.environ.get("BAYES_SEEDS_PATH")
        self.addCleanup(self.restore_seed_path)
        seed_path = pathlib.Path(self.tmpdir.name) / "seeds.json"
        seed_path.write_text(json.dumps({
            "version": "seeds-v1",
            "markets": {
                "gcx_a": market_record("gcx_a", "gcx_a_var", marginals={"yes": 0.6, "no": 0.4}),
                "gcx_b": market_record("gcx_b", "gcx_b_var", marginals={"yes": 0.62, "no": 0.38}),
            },
            "conditionalMarginals": {
                "gcx_b": {
                    "gcx_a_var=yes": {"yes": 0.9, "no": 0.1},
                    "gcx_a_var=no": {"yes": 0.2, "no": 0.8},
                },
            },
        }))
        os.environ["BAYES_SEEDS_PATH"] = str(seed_path)
        self.server = self.import_server()

    def restore_seed_path(self) -> None:
        if self.previous_seed_path is None:
            os.environ.pop("BAYES_SEEDS_PATH", None)
        else:
            os.environ["BAYES_SEEDS_PATH"] = self.previous_seed_path

    def import_server(self):
        module_name = f"bayes_market_server_graph_context_test_{next(_IMPORT_COUNTER)}"
        spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        spec.loader.exec_module(module)
        return module

    def graph_market(self, payload: dict, market_id: str) -> dict:
        by_id = {m["id"]: m for m in payload["markets"]}
        self.assertIn(market_id, by_id)
        return by_id[market_id]

    def test_graph_fields_include_cpt_parents(self):
        payload, status = self.server.route_request("GET", "/v1/markets?fields=graph")
        self.assertEqual(status, 200)
        self.assertEqual(self.graph_market(payload, "gcx_b")["parents"], ["gcx_a_var"])
        self.assertNotIn("parents", self.graph_market(payload, "gcx_a"))

    def test_context_returns_conditional_marginals_for_every_market(self):
        payload, status = self.server.route_request(
            "GET", "/v1/markets?fields=graph&context=gcx_a_var%3Dyes"
        )
        self.assertEqual(status, 200)
        evidence = self.graph_market(payload, "gcx_a")["conditionalMarginals"]
        self.assertAlmostEqual(evidence["yes"], 1.0, places=6)
        child = self.graph_market(payload, "gcx_b")["conditionalMarginals"]
        self.assertAlmostEqual(child["yes"], 0.9, places=4)
        # Unrelated markets are conditioned too (independent => unchanged price).
        other = next(
            m for m in payload["markets"] if m["id"] not in ("gcx_a", "gcx_b")
        )
        self.assertIn("conditionalMarginals", other)
        self.assertAlmostEqual(
            other["conditionalMarginals"]["yes"], other["marginals"]["yes"], places=4
        )

    def test_context_does_not_mutate_base_prices(self):
        self.server.route_request("GET", "/v1/markets?fields=graph&context=gcx_a_var%3Dyes")
        payload, status = self.server.route_request("GET", "/v1/markets?fields=graph")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(
            self.graph_market(payload, "gcx_b")["marginals"]["yes"], 0.62, places=4
        )
        self.assertNotIn("conditionalMarginals", self.graph_market(payload, "gcx_b"))

    def test_context_requires_graph_fields(self):
        with self.assertRaises(self.server.ApiError) as ctx:
            self.server.route_request("GET", "/v1/markets?context=gcx_a_var%3Dyes")
        self.assertEqual(ctx.exception.status, 400)

    def test_context_rejects_unknown_variable(self):
        with self.assertRaises(self.server.ApiError) as ctx:
            self.server.route_request(
                "GET", "/v1/markets?fields=graph&context=no_such_var%3Dyes"
            )
        self.assertEqual(ctx.exception.status, 400)

    def test_context_rejects_malformed_assignments(self):
        with self.assertRaises(self.server.ApiError) as ctx:
            self.server.route_request("GET", "/v1/markets?fields=graph&context=justavar")
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
