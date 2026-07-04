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


def market_record(
    market_id: str,
    variable_id: str,
    *,
    title: str = "Seed Test Market",
    marginals: dict[str, float] | None = None,
    anchor: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
    ftm_implied: float | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "id": market_id,
        "title": title,
        "description": "Seed loader test fixture.",
        "variableId": variable_id,
        "status": "active",
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": marginals or {"yes": 0.4, "no": 0.6},
        "liquidity": 1000.0,
        "volume": 50.0,
        "created_at": "2026-07-04T00:00:00Z",
        "expires_at": "2030-01-01T00:00:00Z",
    }
    if anchor is not None:
        record["anchor"] = anchor
    if provenance is not None:
        record["provenance"] = provenance
    if ftm_implied is not None:
        record["ftmImplied"] = ftm_implied
    return record


class SeedLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = pathlib.Path(self.tmpdir.name)
        self.previous_seed_path = os.environ.get("BAYES_SEEDS_PATH")
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self.restore_seed_path)

    def restore_seed_path(self) -> None:
        if self.previous_seed_path is None:
            os.environ.pop("BAYES_SEEDS_PATH", None)
        else:
            os.environ["BAYES_SEEDS_PATH"] = self.previous_seed_path

    def write_seed_file(self, payload: dict[str, object] | str) -> pathlib.Path:
        seed_path = self.tmp_path / "seeds.json"
        if isinstance(payload, str):
            seed_path.write_text(payload)
        else:
            seed_path.write_text(json.dumps(payload))
        return seed_path

    def import_server(self, seed_path: pathlib.Path | None = None):
        if seed_path is None:
            os.environ.pop("BAYES_SEEDS_PATH", None)
        else:
            os.environ["BAYES_SEEDS_PATH"] = str(seed_path)
        module_name = f"bayes_market_server_seed_loading_test_{next(_IMPORT_COUNTER)}"
        spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None
        assert spec.loader is not None
        sys.modules[module_name] = module
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        spec.loader.exec_module(module)
        return module

    def seed_payload(self, markets: dict[str, dict[str, object]], conditionals: dict[str, object] | None = None) -> dict[str, object]:
        return {"version": "seeds-v1", "markets": markets, "conditionalMarginals": conditionals or {}}

    def test_merge_happy_path_keeps_external_metadata_and_conditionals(self):
        root = market_record(
            "seed_root",
            "seed_root_var",
            title="Seed Root Market",
            provenance={"source": "unit", "ref": "root", "method": "fixture", "fetchedAt": "2026-07-04T00:00:00Z"},
        )
        child = market_record("seed_child", "seed_child_var", title="Seed Child Market", marginals={"yes": 4.0, "no": 6.0})
        seed_path = self.write_seed_file(
            self.seed_payload(
                {"seed_root": root, "seed_child": child},
                {
                    "seed_child": {
                        "seed_root_var=yes": {"yes": 7.0, "no": 3.0},
                        "seed_root_var=no": {"yes": 2.0, "no": 8.0},
                    }
                },
            )
        )

        server = self.import_server(seed_path)

        self.assertIn("seed_root", server.INITIAL_MARKETS)
        self.assertIn("seed_child", server.MARKETS)
        self.assertIn("seed_child", server.INITIAL_CONDITIONAL_MARGINALS)
        self.assertAlmostEqual(server.INITIAL_MARKETS["seed_child"]["marginals"]["yes"], 0.4)
        detail_payload, status = server.route_request("GET", "/v1/markets/seed_root")
        self.assertEqual(status, 200)
        self.assertEqual(detail_payload["market"]["provenance"]["source"], "unit")
        server.CONDITIONAL_MARGINALS.clear()
        server.reset_state()
        self.assertIn("seed_child", server.CONDITIONAL_MARGINALS)

    def test_id_and_variable_id_collisions_are_skipped(self):
        colliding_id = market_record("m1", "seed_new_var", title="Colliding Id")
        colliding_variable = market_record(
            "seed_var_collision",
            "frontier_capability_breakthrough_2028",
            title="Colliding Variable",
        )
        seed_path = self.write_seed_file(
            self.seed_payload({"m1": colliding_id, "seed_var_collision": colliding_variable})
        )

        with self.assertLogs(level="WARNING") as logs:
            server = self.import_server(seed_path)

        self.assertNotEqual(server.INITIAL_MARKETS["m1"]["title"], "Colliding Id")
        self.assertNotIn("seed_var_collision", server.INITIAL_MARKETS)
        self.assertGreaterEqual(len(logs.output), 2)

    def test_malformed_seed_file_logs_warning_and_falls_back_to_inline_seeds(self):
        seed_path = self.write_seed_file("{")

        with self.assertLogs(level="WARNING") as logs:
            server = self.import_server(seed_path)

        self.assertEqual(len(logs.output), 1)
        self.assertIn("unable to load", logs.output[0])
        self.assertNotIn("seed_root", server.INITIAL_MARKETS)
        self.assertEqual(set(server.INITIAL_MARKETS), set(server.MARKETS))

    def test_seed_marginals_are_renormalized(self):
        seed_path = self.write_seed_file(
            self.seed_payload({"seed_norm": market_record("seed_norm", "seed_norm_var", marginals={"yes": 2.0, "no": 3.0})})
        )

        server = self.import_server(seed_path)
        marginals = server.INITIAL_MARKETS["seed_norm"]["marginals"]

        self.assertAlmostEqual(marginals["yes"], 0.4)
        self.assertAlmostEqual(marginals["no"], 0.6)
        self.assertAlmostEqual(sum(marginals.values()), 1.0)

    def test_graph_fields_projection_returns_compact_market_records(self):
        anchor = {"source": "unit", "ref": "graph", "url": "https://example.invalid/graph", "value": 0.61, "fetchedAt": "2026-07-04T00:00:00Z"}
        seed_path = self.write_seed_file(
            self.seed_payload(
                {
                    "seed_graph": market_record(
                        "seed_graph",
                        "seed_graph_var",
                        title="Graph Projection Seed",
                        anchor=anchor,
                        ftm_implied=0.61,
                    )
                }
            )
        )
        server = self.import_server(seed_path)

        payload, status = server.route_request("GET", "/v1/markets?fields=graph&q=Graph%20Projection")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            set(payload["markets"][0]),
            {"id", "variableId", "title", "marginals", "status", "anchor", "ftmImplied"},
        )
        self.assertNotIn("liquidity", payload["markets"][0])
        self.assertEqual(payload["markets"][0]["anchor"], anchor)
        self.assertEqual(payload["markets"][0]["ftmImplied"], 0.61)

    def test_market_list_limit_offset_adds_total_after_filter_sort(self):
        server = self.import_server()
        expected_ids = list(server.INITIAL_MARKETS)[1:3]

        payload, status = server.route_request("GET", "/v1/markets?limit=2&offset=1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["total"], len(server.INITIAL_MARKETS))
        self.assertEqual([market["id"] for market in payload["markets"]], expected_ids)


if __name__ == "__main__":
    unittest.main()
