#!/usr/bin/env python3
"""Offline self-checks for relbot joint-marginal arithmetic."""

import unittest

from relbot import joint_marginal_gap, joint_probabilities


class JointMarginalTest(unittest.TestCase):
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
