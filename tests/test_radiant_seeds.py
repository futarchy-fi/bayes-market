"""Offline tests for scripts/import/radiant_seeds.py on recorded Radiant fixtures (2026-09-29)."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "radiant"
NOW = "2026-09-29T00:00:00Z"


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rs = load(ROOT / "scripts" / "import" / "radiant_seeds.py", "radiant_seeds_under_test")


def run(project_id: str, **overrides):
    raw = json.loads((FIXTURES / f"{project_id}.json").read_text())
    raw["posts"] = {int(k): v for k, v in raw["posts"].items()}
    raw.update(overrides)
    return rs.build(project_id, raw["canvas"], raw["posts"], raw["sim"], NOW)


POLICY = "f43ae04f-f4b9-42ff-9149-1520124c96fd"   # 8 probability nodes + 3 Metaculus (1 multiple choice)
SENATE = "e4005932-f900-4834-8835-45c73bfe605f"   # 23 probability formulas + simulation
RESOLVED = "4a103e26-bbf8-44ae-bd87-599741be15be"  # one resolved binary Metaculus question
NULLPROB = "ddcbcf9a-3663-4016-b031-396d87ceb29c"  # one binary node with probability null


class RadiantSeedsTests(unittest.TestCase):
    def test_policy_canvas_maps_probability_and_metaculus_nodes(self):
        seeds, skipped, listed = run(POLICY)
        m = seeds["markets"]
        self.assertEqual(len(m), 10)
        self.assertEqual(listed, [])
        self.assertEqual(skipped["metaculus:multiple_choice"], 1)
        q = m["rf43ae04f_q41193"]
        self.assertEqual(q["marginals"], {"yes": 0.15, "no": 0.85})  # live CP, not cached canvas value
        self.assertEqual(q["anchor"]["ref"], "41193")
        self.assertEqual(q["anchor"]["source"], "metaculus")
        self.assertEqual(q["provenance"]["method"], "radiant-import-v1")
        self.assertEqual(m["rf43ae04f_bounded_coalition_dec24"]["marginals"]["yes"], 0.5)
        self.assertNotIn("anchor", m["rf43ae04f_bounded_coalition_dec24"])
        self.assertEqual(m["rf43ae04f_scaling_plateau_dec24"]["marginals"]["yes"], 0.02)

    def test_formula_probabilities_use_simulation_mean(self):
        raw = json.loads((FIXTURES / f"{SENATE}.json").read_text())
        seeds, _, listed = run(SENATE)
        self.assertEqual(len(seeds["markets"]), 23)
        self.assertEqual(listed, [])
        c = seeds["markets"]["re4005932_c_blk"]
        self.assertAlmostEqual(c["marginals"]["yes"], raw["sim"]["nodes"]["c_blk"]["mean"], places=6)

    def test_missing_cp_or_value_is_skipped_and_listed_never_filled(self):
        _, skipped, listed = run(POLICY, posts={})
        self.assertEqual(skipped["no_community_prediction"], 2)
        self.assertEqual({x["ref"] for x in listed}, {"q41193", "q44880"})
        _, _, listed = run(NULLPROB)
        self.assertEqual([x["reason"] for x in listed], ["no_probability"])
        _, _, listed = run(RESOLVED)
        self.assertEqual([x["reason"] for x in listed], ["resolved"])
        seeds, skipped, _ = run(SENATE, sim={"status": "compile_failed", "nodes": {}})
        self.assertEqual((len(seeds["markets"]), skipped["no_simulation_mean"]), (0, 23))

    def test_clamp_matches_external_importer(self):
        canvas = {"nodes": [{"id": "a", "node_type": "forecast-binary-probability-node",
                             "data": {"title": "A", "forecasting": {"ref": "a", "probability": 0.0}}},
                            {"id": "b", "node_type": "forecast-binary-probability-node",
                             "data": {"title": "B", "forecasting": {"ref": "b", "probability": 1}}}],
                  "edges": [{"source_node_id": "a", "target_node_id": "b", "data": {"arrow_direction": "backward"}}]}
        seeds, _, _ = rs.build("00000000-0000-0000-0000-000000000000", canvas, {}, None, NOW)
        m = seeds["markets"]
        self.assertEqual(m["r00000000_a"]["marginals"], {"yes": 0.01, "no": 0.99})
        self.assertEqual(m["r00000000_b"]["marginals"], {"yes": 0.99, "no": 0.01})
        self.assertEqual(m["r00000000_a"]["provenance"]["parents"], ["r00000000_b"])  # backward edge
        self.assertEqual(m["r00000000_b"]["provenance"]["parents"], [])

    def test_client_refuses_write_tools_before_any_network(self):
        client = rs.Radiant("not-a-token", url="http://127.0.0.1:9/unreachable")
        for tool in ("create_project", "import_metaculus_posts_to_canvas", "start_metaculus_ai_forecast"):
            with self.assertRaises(PermissionError):
                client.call(tool, {})

    def test_seed_loader_accepts_every_market(self):
        seeds, _, _ = run(POLICY)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "seeds.json"
            path.write_text(json.dumps(seeds))
            old = os.environ.get("BAYES_SEEDS_PATH")
            os.environ["BAYES_SEEDS_PATH"] = str(path)
            try:
                server = load(ROOT / "backend" / "server.py", "bayes_market_server_radiant_test")
            finally:
                sys.modules.pop("bayes_market_server_radiant_test", None)
                if old is None:
                    os.environ.pop("BAYES_SEEDS_PATH")
                else:
                    os.environ["BAYES_SEEDS_PATH"] = old
        for mid, market in seeds["markets"].items():
            self.assertAlmostEqual(server.INITIAL_MARKETS[mid]["marginals"]["yes"], market["marginals"]["yes"])


if __name__ == "__main__":
    unittest.main()
