"""Junction-tree LMSR maker: equivalence with the flat joint, cap, scale."""

from __future__ import annotations

import random
import time
import unittest

from backend.inference import JointMarket, JointMarketError
from backend.inference.factored_market import FactoredMarket
from backend.inference.network_model import BayesNetworkModel


def _root(var, yes=0.5, outcomes=("yes", "no")):
    prior = {o: (yes if o == "yes" else (1.0 - yes) / (len(outcomes) - 1)) for o in outcomes}
    return {
        "variable_id": var,
        "outcomes": tuple(outcomes),
        "parents": (),
        "rows": {frozenset(): prior},
    }


def _child(var, parents_outcomes, rows, outcomes=("yes", "no")):
    """parents_outcomes: {parent: its outcomes}; rows keyed by parent outcome tuple."""
    parents = tuple(sorted(parents_outcomes))
    parsed = {}
    for combo, row in rows.items():
        key = frozenset(zip(parents, combo))
        parsed[key] = row
    return {
        "variable_id": var,
        "outcomes": tuple(outcomes),
        "parents": parents,
        "rows": parsed,
    }


def _test_nodes():
    """7 vars: a,b roots; c|a,b (v-structure); ternary d|c; e|c; f|e; g isolated."""
    nodes = [
        _root("a", 0.62),
        _root("b", 0.35),
        _child(
            "c",
            {"a": ("yes", "no"), "b": ("yes", "no")},
            {
                ("yes", "yes"): {"yes": 0.9, "no": 0.1},
                ("yes", "no"): {"yes": 0.6, "no": 0.4},
                ("no", "yes"): {"yes": 0.45, "no": 0.55},
                ("no", "no"): {"yes": 0.08, "no": 0.92},
            },
        ),
        _child(
            "d",
            {"c": ("yes", "no")},
            {
                ("yes",): {"lo": 0.2, "mid": 0.5, "hi": 0.3},
                ("no",): {"lo": 0.6, "mid": 0.3, "hi": 0.1},
            },
            outcomes=("lo", "mid", "hi"),
        ),
        _child(
            "e",
            {"c": ("yes", "no")},
            {("yes",): {"yes": 0.7, "no": 0.3}, ("no",): {"yes": 0.25, "no": 0.75}},
        ),
        _child(
            "f",
            {"e": ("yes", "no")},
            {("yes",): {"yes": 0.55, "no": 0.45}, ("no",): {"yes": 0.15, "no": 0.85}},
        ),
        _root("g", 0.27),
    ]
    return nodes


def _build_pair(liquidity=300.0, max_width=8):
    nodes = _test_nodes()
    flat = JointMarket.from_network(BayesNetworkModel(nodes), liquidity)
    factored = FactoredMarket.from_nodes(nodes, liquidity, max_width)
    return flat, factored


_EVIDENCE_SETS = [
    None,
    {"a": "yes"},
    {"f": "yes"},                      # diagnostic, two hops
    {"d": "hi"},                       # diagnostic from ternary
    {"a": "no", "f": "yes"},           # mixed predictive + diagnostic
    {"b": "yes", "e": "no"},
    {"g": "yes"},                      # isolated component evidence
    {"a": "yes", "b": "no", "e": "yes", "g": "no"},
]


class FactoredMarketEquivalence(unittest.TestCase):
    def assert_all_marginals_match(self, flat, factored, places=9):
        for var in flat.variables():
            for evidence in _EVIDENCE_SETS:
                expected = flat.marginal(var, evidence)
                actual = factored.marginal(var, evidence)
                if expected is None:
                    self.assertIsNone(actual, (var, evidence))
                    continue
                self.assertIsNotNone(actual, (var, evidence))
                for outcome, value in expected.items():
                    self.assertAlmostEqual(
                        actual[outcome], value, places=places, msg=(var, evidence, outcome)
                    )

    def test_calibration_matches_flat_joint(self):
        flat, factored = _build_pair()
        self.assert_all_marginals_match(flat, factored)

    def test_trade_parity_marginal_and_in_family(self):
        flat, factored = _build_pair()
        trades = [
            ("a", "yes", 0.8, None),
            ("c", "yes", 0.5, {"a": "yes", "b": "no"}),   # within family
            ("d", "hi", 0.4, {"c": "yes"}),               # ternary, within family
            ("f", "yes", 0.6, None),
        ]
        for var, outcome, target, context in trades:
            fill_flat = flat.trade_to_probability(var, outcome, target, context)
            fill_fact = factored.trade_to_probability(var, outcome, target, context)
            for key in ("previousProbability", "newProbability", "shares", "cost"):
                self.assertAlmostEqual(
                    fill_fact[key], fill_flat[key], places=6, msg=(var, key)
                )
        self.assert_all_marginals_match(flat, factored)

    def test_trade_parity_cross_clique_restructures(self):
        flat, factored = _build_pair()
        # b and f share no clique in the seeded tree; this forces an exact
        # re-triangulation with (b, f) as a forced scope.
        fill_flat = flat.trade_to_probability("f", "yes", 0.7, {"b": "yes"})
        fill_fact = factored.trade_to_probability("f", "yes", 0.7, {"b": "yes"})
        for key in ("previousProbability", "newProbability", "shares", "cost"):
            self.assertAlmostEqual(fill_fact[key], fill_flat[key], places=6, msg=key)
        self.assert_all_marginals_match(flat, factored)
        # And a trade whose context lives in a different component entirely.
        fill_flat = flat.trade_to_probability("a", "yes", 0.5, {"g": "yes"})
        fill_fact = factored.trade_to_probability("a", "yes", 0.5, {"g": "yes"})
        self.assertAlmostEqual(
            fill_fact["previousProbability"], fill_flat["previousProbability"], places=6
        )
        self.assert_all_marginals_match(flat, factored, places=8)

    def test_called_off_bet_leaves_context_probability_unchanged(self):
        _, factored = _build_pair()
        before = factored.marginal("b", None)["yes"]
        factored.trade_to_probability("f", "yes", 0.7, {"b": "yes"})
        after = factored.marginal("b", None)["yes"]
        self.assertAlmostEqual(after, before, places=9)

    def test_resolution_parity(self):
        flat, factored = _build_pair()
        flat.trade_to_probability("e", "yes", 0.6)
        factored.trade_to_probability("e", "yes", 0.6)
        flat.condition("c", "yes")
        factored.condition("c", "yes")
        self.assert_all_marginals_match(flat, factored)
        point = factored.marginal("c", None)
        self.assertAlmostEqual(point["yes"], 1.0, places=9)

    def test_snapshot_roundtrip_including_trade_scopes(self):
        flat, factored = _build_pair()
        flat.trade_to_probability("f", "yes", 0.7, {"b": "yes"})
        factored.trade_to_probability("f", "yes", 0.7, {"b": "yes"})
        restored = FactoredMarket.from_snapshot(factored.snapshot())
        self.assert_all_marginals_match(flat, restored)
        # The restored maker keeps trading identically.
        fill_flat = flat.trade_to_probability("f", "no", 0.5, {"b": "yes"})
        fill_rest = restored.trade_to_probability("f", "no", 0.5, {"b": "yes"})
        self.assertAlmostEqual(fill_rest["cost"], fill_flat["cost"], places=6)

    def test_absorb_flat_projects_traded_prices(self):
        flat, factored = _build_pair()
        flat.trade_to_probability("a", "yes", 0.8)
        flat.trade_to_probability("c", "yes", 0.5, {"a": "yes", "b": "no"})
        snap = flat.snapshot()
        factored.absorb_flat(snap["order"], snap["outcomes"], snap["probabilities"])
        self.assert_all_marginals_match(flat, factored)

    def test_entropy_matches_flat(self):
        flat, factored = _build_pair()
        flat.trade_to_probability("a", "yes", 0.8)
        factored.trade_to_probability("a", "yes", 0.8)
        self.assertAlmostEqual(
            factored.stats()["entropyNats"], flat.stats()["entropyNats"], places=5
        )
        self.assertEqual(factored.stats()["states"], flat.stats()["states"])

    def test_error_parity(self):
        _, factored = _build_pair()
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("nope", "yes", 0.5)
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("a", "maybe", 0.5)
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("a", "yes", 1.0)
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("a", "yes", 0.5, {"a": "yes"})
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("a", "yes", 0.5, {"b": "maybe"})
        factored.condition("c", "yes")
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability("c", "yes", 0.5)


class FactoredMarketWidthCap(unittest.TestCase):
    def test_build_rejects_family_over_budget(self):
        # c has two parents: the moralized family clique has 8 states > 2^2.
        with self.assertRaises(JointMarketError):
            FactoredMarket.from_nodes(_test_nodes(), 300.0, max_width=1)

    def test_trade_beyond_budget_is_rejected_and_state_intact(self):
        factored = FactoredMarket.from_nodes(_test_nodes(), 300.0, max_width=2)
        before = {
            var: factored.marginal(var, None) for var in factored.variables()
        }
        # Scope {a, b, d, f} plus fill-in cannot fit any 3-variable cluster.
        with self.assertRaises(JointMarketError):
            factored.trade_to_probability(
                "f", "yes", 0.9, {"a": "yes", "b": "yes", "d": "hi"}
            )
        for var, expected in before.items():
            actual = factored.marginal(var, None)
            for outcome, value in expected.items():
                self.assertAlmostEqual(actual[outcome], value, places=12)


class FactoredMarketScale(unittest.TestCase):
    N = 1000

    def _scale_nodes(self):
        rng = random.Random(7)
        nodes = [_root("x0000", 0.5)]
        for i in range(1, self.N):
            var = f"x{i:04d}"
            lo = max(0, i - 20)
            p1 = f"x{rng.randrange(lo, i):04d}"
            if i % 100 == 0 and i >= 2:
                p2 = f"x{rng.randrange(lo, i):04d}"
                while p2 == p1:
                    p2 = f"x{rng.randrange(lo, i):04d}"
                parents = {p1: ("yes", "no"), p2: ("yes", "no")}
                rows = {
                    ("yes", "yes"): {"yes": 0.85, "no": 0.15},
                    ("yes", "no"): {"yes": 0.6, "no": 0.4},
                    ("no", "yes"): {"yes": 0.4, "no": 0.6},
                    ("no", "no"): {"yes": 0.1, "no": 0.9},
                }
            else:
                parents = {p1: ("yes", "no")}
                rows = {
                    ("yes",): {"yes": 0.6 + 0.3 * rng.random(), "no": 0.0},
                    ("no",): {"yes": 0.4 * rng.random(), "no": 0.0},
                }
                for row in rows.values():
                    row["no"] = round(1.0 - row["yes"], 9)
            nodes.append(_child(var, parents, rows))
        return nodes

    def test_thousand_variable_network_trades_exactly(self):
        started = time.monotonic()
        market = FactoredMarket.from_nodes(self._scale_nodes(), 300.0, max_width=8)
        build_seconds = time.monotonic() - started

        stats = market.stats()
        self.assertEqual(stats["statesLog2"], float(self.N))
        self.assertGreater(stats["states"], 0.0)
        self.assertLessEqual(stats["treewidth"], 8.0)

        rng = random.Random(11)
        started = time.monotonic()
        n_trades = 25
        for _ in range(n_trades):
            var = f"x{rng.randrange(self.N):04d}"
            target = 0.05 + 0.9 * rng.random()
            fill = market.trade_to_probability(var, "yes", target)
            self.assertAlmostEqual(fill["newProbability"], round(target, 6), places=6)
            self.assertAlmostEqual(market.marginal(var, None)["yes"], target, places=6)
        trade_seconds = (time.monotonic() - started) / n_trades

        # A conditional trade far across the chain forces a re-triangulation.
        fill = market.trade_to_probability("x0900", "yes", 0.75, {"x0050": "yes"})
        self.assertAlmostEqual(
            market.marginal("x0900", {"x0050": "yes"})["yes"], 0.75, places=6
        )
        self.assertGreater(abs(fill["shares"]), 0.0)

        # Diagnostic evidence query across the network.
        result = market.marginal("x0010", {"x0990": "yes"})
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)

        print(
            f"\n[scale] n={self.N} build={build_seconds:.2f}s "
            f"trade={trade_seconds*1000:.0f}ms/trade "
            f"treewidth={stats['treewidth']:.0f} cliques={stats['cliqueCount']:.0f}"
        )
        self.assertLess(build_seconds, 60.0)
        self.assertLess(trade_seconds, 5.0)


if __name__ == "__main__":
    unittest.main()
