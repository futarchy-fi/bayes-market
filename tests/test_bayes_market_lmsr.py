from __future__ import annotations

import importlib.util
import math
import pathlib
import unittest
from copy import deepcopy

ROOT = pathlib.Path(__file__).resolve().parents[1]
LMSR_PATH = ROOT / "backend" / "lmsr.py"
SERVER_PATH = ROOT / "backend" / "server.py"

lmsr_spec = importlib.util.spec_from_file_location("bayes_market_lmsr_test", LMSR_PATH)
lmsr = importlib.util.module_from_spec(lmsr_spec)
assert lmsr_spec is not None
assert lmsr_spec.loader is not None
lmsr_spec.loader.exec_module(lmsr)

server_spec = importlib.util.spec_from_file_location("bayes_market_server_for_lmsr_test", SERVER_PATH)
server = importlib.util.module_from_spec(server_spec)
assert server_spec is not None
assert server_spec.loader is not None
server_spec.loader.exec_module(server)


class BayesMarketLmsrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binary_previous = deepcopy(server.INITIAL_MARKETS["m1"]["marginals"])
        self.multi_previous = deepcopy(server.INITIAL_MARKETS["m2"]["marginals"])
        self.binary_liquidity = float(server.INITIAL_MARKETS["m1"]["liquidity"])
        self.multi_liquidity = float(server.INITIAL_MARKETS["m2"]["liquidity"])

    def test_rescale_probability_edit_reaches_exact_binary_target(self):
        updated = lmsr.rescale_probability_edit(self.binary_previous, "yes", 0.8)

        self.assertAlmostEqual(updated["yes"], 0.8, delta=1e-12)
        self.assertAlmostEqual(updated["no"], 0.2, delta=1e-12)
        self.assertAlmostEqual(sum(updated.values()), 1.0, delta=1e-12)

    def test_rescale_probability_edit_preserves_non_target_relative_mass(self):
        updated = lmsr.rescale_probability_edit(self.multi_previous, "yes", 0.4)

        self.assertAlmostEqual(updated["yes"], 0.4, delta=1e-12)
        self.assertAlmostEqual(updated["no"], 0.48, delta=1e-12)
        self.assertAlmostEqual(updated["delayed"], 0.12, delta=1e-12)
        self.assertAlmostEqual(
            updated["no"] / updated["delayed"],
            self.multi_previous["no"] / self.multi_previous["delayed"],
            delta=1e-12,
        )
        self.assertAlmostEqual(sum(updated.values()), 1.0, delta=1e-12)

    def test_rescale_probability_edit_uniformizes_non_target_mass_when_previous_other_mass_is_zero(self):
        updated = lmsr.rescale_probability_edit({"yes": 1.0, "no": 0.0, "delayed": 0.0}, "yes", 0.4)

        self.assertAlmostEqual(updated["yes"], 0.4, delta=1e-12)
        self.assertAlmostEqual(updated["no"], 0.3, delta=1e-12)
        self.assertAlmostEqual(updated["delayed"], 0.3, delta=1e-12)

    def test_lmsr_score_delta_scales_with_liquidity(self):
        updated = lmsr.rescale_probability_edit(self.binary_previous, "yes", 0.8)
        base_delta = lmsr.lmsr_score_delta(self.binary_previous, updated, self.binary_liquidity)
        doubled_delta = lmsr.lmsr_score_delta(self.binary_previous, updated, self.binary_liquidity * 2.0)

        for outcome_id, delta in base_delta.items():
            self.assertAlmostEqual(doubled_delta[outcome_id], delta * 2.0, delta=1e-9)

    def test_lmsr_expected_edit_cost_scales_with_liquidity(self):
        updated = lmsr.rescale_probability_edit(self.multi_previous, "yes", 0.4)
        base_cost = lmsr.lmsr_expected_edit_cost(self.multi_previous, updated, self.multi_liquidity)
        doubled_cost = lmsr.lmsr_expected_edit_cost(self.multi_previous, updated, self.multi_liquidity * 2.0)

        self.assertAlmostEqual(doubled_cost, base_cost * 2.0, delta=1e-9)

    def test_lmsr_expected_edit_cost_matches_b_times_relative_entropy(self):
        updated = lmsr.rescale_probability_edit(self.multi_previous, "yes", 0.4)
        expected_kl = sum(
            updated[outcome_id] * math.log(updated[outcome_id] / self.multi_previous[outcome_id])
            for outcome_id in self.multi_previous
        )

        self.assertAlmostEqual(
            lmsr.lmsr_expected_edit_cost(self.multi_previous, updated, self.multi_liquidity),
            self.multi_liquidity * expected_kl,
            delta=1e-9,
        )

    def test_quote_probability_edit_is_deterministic_and_consistent(self):
        first_quote = lmsr.quote_probability_edit(self.multi_previous, "yes", 0.4, self.multi_liquidity)
        second_quote = lmsr.quote_probability_edit(self.multi_previous, "yes", 0.4, self.multi_liquidity)

        self.assertEqual(first_quote, second_quote)
        self.assertAlmostEqual(
            first_quote["cost"],
            lmsr.lmsr_expected_edit_cost(self.multi_previous, first_quote["updated"], self.multi_liquidity),
            delta=1e-9,
        )

    def test_quote_probability_edit_supports_non_leading_target_outcome(self):
        quote = lmsr.quote_probability_edit(self.multi_previous, "no", 0.3, self.multi_liquidity)

        self.assertAlmostEqual(quote["updated"]["no"], 0.3, delta=1e-12)
        self.assertEqual(set(quote["score_delta"]), {"yes", "no", "delayed"})
        self.assertAlmostEqual(
            quote["cost"],
            lmsr.lmsr_expected_edit_cost(self.multi_previous, quote["updated"], self.multi_liquidity),
            delta=1e-9,
        )

    def test_rescale_probability_edit_rejects_unknown_outcome(self):
        with self.assertRaisesRegex(ValueError, "known outcome"):
            lmsr.rescale_probability_edit(self.binary_previous, "unknown", 0.8)

    def test_lmsr_expected_edit_cost_rejects_non_finite_liquidity(self):
        updated = lmsr.rescale_probability_edit(self.binary_previous, "yes", 0.8)

        with self.assertRaisesRegex(ValueError, "liquidity must be finite"):
            lmsr.lmsr_expected_edit_cost(self.binary_previous, updated, math.inf)

    def test_lmsr_score_delta_rejects_zero_probability_inputs(self):
        with self.assertRaisesRegex(ValueError, "strictly positive"):
            lmsr.lmsr_score_delta(
                {"yes": 1.0, "no": 0.0},
                {"yes": 0.8, "no": 0.2},
                self.binary_liquidity,
            )


if __name__ == "__main__":
    unittest.main()
