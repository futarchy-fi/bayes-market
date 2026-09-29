"""Offline tests for scripts/import/radiant_seeds.py (one recorded Radiant fixture, 2026-09-29)."""

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
sys.path.insert(0, str(ROOT / "scripts" / "import"))
import radiant_seeds as rs  # noqa: E402


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(project_id: str, **overrides):
    raw = json.loads((FIXTURES / f"{project_id}.json").read_text())
    raw["posts"] = {int(k): v for k, v in raw["posts"].items()}
    raw.update(overrides)
    return rs.build(project_id, raw["canvas"], raw["posts"], raw["sim"], NOW)


POLICY = "f43ae04f-f4b9-42ff-9149-1520124c96fd"   # 8 probability nodes + 3 Metaculus (1 multiple choice)
PID = "00000000-0000-0000-0000-000000000000"


def node(nid, node_type, **data):
    return {"id": nid, "node_type": node_type, "data": data}


def mq(post_id):
    return node("m", "metaculus-question-node", metaculus={"type": "binary", "post_id": post_id,
                                                           "url": f"https://www.metaculus.com/questions/{post_id}/"},
                forecasting={"ref": "q1"})


def post(status="open", close="2027-01-01T00:00:00Z", cp=0.4):
    return {1: {"id": 1, "status": status, "scheduled_close_time": close, "question": {
        "aggregations": {"recency_weighted": {"latest": {"centers": [cp]}}}}}}


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
        canvas = {"nodes": [node("f", "forecast-formula-node",
                                 forecasting={"ref": "f", "outputType": "probability"})]}
        seeds, _, _ = rs.build(PID, canvas, {}, {"status": "ok", "nodes": {"f": {"mean": 0.3}}}, NOW)
        self.assertEqual(seeds["markets"]["r00000000_f"]["marginals"]["yes"], 0.3)

    def test_failed_simulation_exits_without_seeds(self):
        canvas = {"nodes": [node("f", "forecast-formula-node",
                                 forecasting={"ref": "f", "outputType": "probability"})]}
        stub = type("Stub", (), {"call": lambda self, name, args: canvas if name == "read_canvas"
                                 else {"status": "compile_failed", "nodes": {}}})()
        with self.assertRaises(SystemExit):
            rs.fetch(stub, PID)

    def test_closed_or_past_metaculus_questions_are_skipped(self):
        for posts in (post(status="resolved"), post(status="closed"), post(close="2025-06-01T00:00:00Z")):
            seeds, _, listed = rs.build(PID, {"nodes": [mq(1)]}, posts, None, NOW)
            self.assertEqual((seeds["markets"], [x["reason"] for x in listed]), ({}, ["closed"]))
        seeds, _, _ = rs.build(PID, {"nodes": [mq(1)]}, post(), None, NOW)
        self.assertEqual(seeds["markets"]["r00000000_q1"]["expires_at"], "2027-01-01T00:00:00Z")

    def test_past_year_in_title_is_not_used_as_expiry(self):
        canvas = {"nodes": [node("a", "forecast-binary-probability-node", title="Share >= 2022 level",
                                 forecasting={"ref": "a", "probability": 0.5})]}
        seeds, _, _ = rs.build(PID, canvas, {}, None, NOW)
        self.assertEqual(seeds["markets"]["r00000000_a"]["expires_at"], "2031-12-31T23:59:59Z")

    def test_missing_cp_or_value_is_skipped_and_listed_never_filled(self):
        _, skipped, listed = run(POLICY, posts={})
        self.assertEqual(skipped["no_community_prediction"], 2)
        self.assertEqual({x["ref"] for x in listed}, {"q41193", "q44880"})
        canvas = {"nodes": [node("a", "forecast-binary-probability-node",
                                 forecasting={"ref": "a", "probability": None})]}
        _, _, listed = rs.build(PID, canvas, {}, None, NOW)
        self.assertEqual([x["reason"] for x in listed], ["no_probability"])

    def test_clamp_matches_external_importer(self):
        canvas = {"nodes": [{"id": "a", "node_type": "forecast-binary-probability-node",
                             "data": {"title": "A", "forecasting": {"ref": "a", "probability": 0.0}}},
                            {"id": "b", "node_type": "forecast-binary-probability-node",
                             "data": {"title": "B", "forecasting": {"ref": "b", "probability": 1}}}],
                  "edges": [{"source_node_id": "a", "target_node_id": "b", "data": {"arrow_direction": "backward"}}]}
        seeds, _, _ = rs.build(PID, canvas, {}, None, NOW)
        m = seeds["markets"]
        self.assertEqual(m["r00000000_a"]["marginals"], {"yes": 0.01, "no": 0.99})
        self.assertEqual(m["r00000000_b"]["marginals"], {"yes": 0.99, "no": 0.01})
        self.assertEqual(m["r00000000_a"]["provenance"]["parents"], ["r00000000_b"])  # backward edge
        self.assertEqual(m["r00000000_b"]["provenance"]["parents"], [])

    def test_client_refuses_write_tools_before_any_network(self):
        client = rs.Radiant("not-a-token")
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
