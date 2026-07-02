"""Combinatorial LMSR market maker over the joint (joint_market)."""

from __future__ import annotations

import math
import unittest

from backend.inference import JointMarket, JointMarketError, build_market_network


def _market(market_id, variable_id, yes):
    return {
        "id": market_id,
        "variableId": variable_id,
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": {"yes": yes, "no": round(1.0 - yes, 6)},
    }


MARKETS = {
    "m1": _market("m1", "a", 0.5),
    "m2": _market("m2", "b", 0.5),  # b <- a
    "m3": _market("m3", "loner", 0.3),
}

CPTS = {
    "m2": {
        "a=yes": {"yes": 0.9, "no": 0.1},
        "a=no": {"yes": 0.2, "no": 0.8},
    },
}

B = 100.0


def make_market() -> JointMarket:
    return JointMarket.from_network(build_market_network(MARKETS, CPTS), liquidity=B)


class JointMarketTradeTests(unittest.TestCase):
    def test_initial_prices_match_the_network(self):
        jm = make_market()
        self.assertAlmostEqual(jm.marginal("b", {})["yes"], 0.55, places=9)
        self.assertAlmostEqual(jm.marginal("loner", {})["yes"], 0.3, places=9)

    def test_trade_moves_the_target_price_exactly(self):
        jm = make_market()
        fill = jm.trade_to_probability("a", "yes", 0.8)
        self.assertAlmostEqual(jm.marginal("a", {})["yes"], 0.8, places=9)
        self.assertAlmostEqual(fill["previousProbability"], 0.5, places=6)
        # LMSR closed forms at p=0.5 -> t=0.8
        self.assertAlmostEqual(fill["shares"], B * math.log(0.8 * 0.5 / (0.5 * 0.2)), places=4)
        self.assertAlmostEqual(fill["cost"], B * math.log(0.5 / 0.2), places=4)

    def test_trade_repricing_propagates_through_the_joint(self):
        jm = make_market()
        jm.trade_to_probability("a", "yes", 0.8)
        # P(b=yes) = 0.8*0.9 + 0.2*0.2 = 0.76 (CPT association preserved)
        self.assertAlmostEqual(jm.marginal("b", {})["yes"], 0.76, places=9)
        # Independent variables don't move
        self.assertAlmostEqual(jm.marginal("loner", {})["yes"], 0.3, places=9)

    def test_diagnostic_trade_moves_parents(self):
        jm = make_market()
        jm.trade_to_probability("b", "yes", 0.9)
        # Trading the child up must pull the parent up via Bayes
        self.assertGreater(jm.marginal("a", {})["yes"], 0.5)

    def test_selling_returns_negative_cost(self):
        jm = make_market()
        fill = jm.trade_to_probability("a", "yes", 0.3)
        self.assertLess(fill["shares"], 0)
        self.assertLess(fill["cost"], 0)
        self.assertAlmostEqual(jm.marginal("a", {})["yes"], 0.3, places=9)

    def test_round_trip_costs_net_to_zero(self):
        jm = make_market()
        up = jm.trade_to_probability("a", "yes", 0.8)
        down = jm.trade_to_probability("a", "yes", 0.5)
        self.assertAlmostEqual(up["cost"] + down["cost"], 0.0, places=6)

    def test_conditional_trade_is_a_called_off_bet(self):
        jm = make_market()
        before_context = jm.marginal("a", {})["yes"]
        jm.trade_to_probability("b", "yes", 0.99, context={"a": "yes"})
        # P(b|a=yes) moved...
        self.assertAlmostEqual(jm.marginal("b", {"a": "yes"})["yes"], 0.99, places=9)
        # ...the context's own probability did not
        self.assertAlmostEqual(jm.marginal("a", {})["yes"], before_context, places=9)
        # ...and the other slice is untouched
        self.assertAlmostEqual(jm.marginal("b", {"a": "no"})["yes"], 0.2, places=9)

    def test_condition_resolves_and_reprices(self):
        jm = make_market()
        jm.condition("a", "yes")
        self.assertAlmostEqual(jm.marginal("a", {})["yes"], 1.0, places=9)
        self.assertAlmostEqual(jm.marginal("b", {})["yes"], 0.9, places=9)

    def test_rejects_degenerate_targets_and_unknowns(self):
        jm = make_market()
        with self.assertRaises(JointMarketError):
            jm.trade_to_probability("a", "yes", 1.0)
        with self.assertRaises(JointMarketError):
            jm.trade_to_probability("zzz", "yes", 0.5)
        with self.assertRaises(JointMarketError):
            jm.trade_to_probability("a", "maybe", 0.5)
        with self.assertRaises(JointMarketError):
            jm.trade_to_probability("a", "yes", 0.6, context={"a": "no"})

    def test_joint_stays_normalized_across_many_trades(self):
        jm = make_market()
        for target in (0.8, 0.2, 0.65, 0.4, 0.9, 0.55):
            jm.trade_to_probability("a", "yes", target)
            jm.trade_to_probability("b", "yes", 1 - target, context={"a": "no"})
        total = sum(jm._probs)  # noqa: SLF001 - invariant check
        self.assertAlmostEqual(total, 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
