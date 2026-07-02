"""Exact joint inference over the market network (network_model)."""

from __future__ import annotations

import unittest

from backend.inference import NetworkModelError, build_market_network


def _market(market_id, variable_id, yes):
    return {
        "id": market_id,
        "variableId": variable_id,
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": {"yes": yes, "no": round(1.0 - yes, 6)},
    }


MARKETS = {
    "m1": _market("m1", "a", 0.5),
    "m2": _market("m2", "b", 0.5),   # b <- a
    "m3": _market("m3", "c", 0.5),   # c <- b
    "m4": _market("m4", "loner", 0.3),
}

CPTS = {
    "m2": {
        "a=yes": {"yes": 0.9, "no": 0.1},
        "a=no": {"yes": 0.2, "no": 0.8},
    },
    "m3": {
        "b=yes": {"yes": 0.8, "no": 0.2},
        "b=no": {"yes": 0.1, "no": 0.9},
    },
}


class NetworkModelTests(unittest.TestCase):
    def setUp(self):
        self.model = build_market_network(MARKETS, CPTS)

    def test_prior_marginals_derive_from_the_joint(self):
        # P(b) = 0.5*0.9 + 0.5*0.2 = 0.55
        self.assertAlmostEqual(self.model.marginal("b", {})["yes"], 0.55, places=9)
        # P(c) = 0.55*0.8 + 0.45*0.1 = 0.485
        self.assertAlmostEqual(self.model.marginal("c", {})["yes"], 0.485, places=9)

    def test_predictive_evidence_flows_forward(self):
        # P(c | a=yes): P(b|a=yes)=0.9 -> 0.9*0.8 + 0.1*0.1 = 0.73
        result = self.model.marginal("c", {"a": "yes"})
        self.assertAlmostEqual(result["yes"], 0.73, places=9)

    def test_diagnostic_evidence_flows_backward(self):
        # P(a | b=yes) = 0.5*0.9 / 0.55 = 9/11
        result = self.model.marginal("a", {"b": "yes"})
        self.assertAlmostEqual(result["yes"], 9.0 / 11.0, places=9)

    def test_two_hop_diagnostic_evidence(self):
        # P(b | c=yes) = 0.55*0.8 / 0.485
        result = self.model.marginal("b", {"c": "yes"})
        self.assertAlmostEqual(result["yes"], 0.44 / 0.485, places=9)

    def test_isolated_variable_unmoved_by_evidence(self):
        result = self.model.marginal("loner", {"a": "yes", "c": "no"})
        self.assertAlmostEqual(result["yes"], 0.3, places=9)

    def test_evidence_on_target_is_point_mass(self):
        result = self.model.marginal("b", {"b": "no"})
        self.assertEqual(result, {"yes": 0.0, "no": 1.0})

    def test_unknown_evidence_variable_is_ignored(self):
        result = self.model.marginal("c", {"a": "yes", "zzz": "yes"})
        self.assertAlmostEqual(result["yes"], 0.73, places=9)

    def test_unknown_outcome_returns_none(self):
        self.assertIsNone(self.model.marginal("c", {"a": "maybe"}))

    def test_unknown_variable_returns_none(self):
        self.assertIsNone(self.model.marginal("zzz", {}))

    def test_cycle_raises(self):
        cyclic = {
            "m1": {"b=yes": {"yes": 0.5, "no": 0.5}, "b=no": {"yes": 0.5, "no": 0.5}},
            "m2": {"a=yes": {"yes": 0.5, "no": 0.5}, "a=no": {"yes": 0.5, "no": 0.5}},
        }
        with self.assertRaises(NetworkModelError):
            build_market_network({"m1": MARKETS["m1"], "m2": MARKETS["m2"]}, cyclic)

    def test_incomplete_cpt_falls_back_to_root(self):
        incomplete = {"m2": {"a=yes": {"yes": 0.9, "no": 0.1}}}  # missing a=no row
        model = build_market_network(MARKETS, incomplete)
        # b treated as root with its stored prior; evidence on a does nothing
        self.assertAlmostEqual(model.marginal("b", {"a": "no"})["yes"], 0.5, places=9)

    def test_unsorted_cpt_keys_are_canonicalized(self):
        markets = {
            "m1": _market("m1", "a", 0.5),
            "m2": _market("m2", "z_var", 0.5),
            "m3": _market("m3", "child", 0.5),
        }
        cpts = {
            "m3": {
                # keys deliberately not alphabetically ordered
                "z_var=yes|a=yes": {"yes": 1.0, "no": 0.0},
                "z_var=yes|a=no": {"yes": 0.0, "no": 1.0},
                "z_var=no|a=yes": {"yes": 0.0, "no": 1.0},
                "z_var=no|a=no": {"yes": 0.0, "no": 1.0},
            }
        }
        model = build_market_network(markets, cpts)
        result = model.marginal("child", {"a": "yes", "z_var": "yes"})
        self.assertAlmostEqual(result["yes"], 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
