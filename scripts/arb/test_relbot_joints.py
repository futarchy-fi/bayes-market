#!/usr/bin/env python3
"""Offline self-checks for relbot joint-marginal arithmetic."""

import unittest
from unittest.mock import patch

from relbot import bayes_markets, joint_marginal_gap, joint_probabilities


class JointMarginalTest(unittest.TestCase):
    @patch("relbot.fetch_json")
    def test_exchange_market_marginal_fixture(self, fetch):
        fetch.return_value = {"markets": [
            {"id": "market-1", "status": "open",
             "marginals": {"yes": 0.63, "no": 0.37}},
            {"id": "market-2", "status": "active",
             "marginals": {"yes": 0.4, "no": 0.6}},
            {"id": "market-3", "status": "resolved",
             "marginals": {"yes": 1.0, "no": 0.0}},
        ]}

        markets = bayes_markets("http://exchange")

        fetch.assert_called_once_with(
            "http://exchange/v1/net/markets?fields=graph"
        )
        self.assertEqual([market["id"] for market in markets], ["market-1", "market-2"])
        self.assertEqual(markets[0]["marginals"]["yes"], 0.63)

    def test_cell_sums_and_gap(self):
        truth_table = {
            "a_yes_b_yes": "AGI // Python 4",
            "a_yes_b_no": "AGI // No Python 4",
            "a_no_b_yes": "No AGI // Python 4",
            "a_no_b_no": "No AGI // No Python 4",
        }
        market = {"answers": [
            {"text": "AGI // Python 4", "probability": 0.095},
            {"text": "AGI // No Python 4", "probability": 0.058},
            {"text": "No AGI // Python 4", "probability": 0.006},
            {"text": "No AGI // No Python 4", "probability": 0.841},
        ]}

        prob_a, prob_b = joint_probabilities(market, truth_table)

        self.assertAlmostEqual(prob_a, 0.153)
        self.assertAlmostEqual(prob_b, 0.101)
        self.assertEqual(joint_marginal_gap(prob_a, 0.165), -0.012)


if __name__ == "__main__":
    unittest.main()
