"""Partial-context marginalization in the current-model query backend."""

from __future__ import annotations

import unittest

from backend.inference import CURRENT_MODEL_COMPILER, CURRENT_MODEL_QUERY_BACKEND

MARKET = {
    "id": "m1",
    "variableId": "child",
    "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
    "marginals": {"yes": 0.65, "no": 0.35},
}
CONDITIONALS = {
    "a=yes|b=yes": {"yes": 0.79, "no": 0.21},
    "a=yes|b=no": {"yes": 0.67, "no": 0.33},
    "a=no|b=yes": {"yes": 0.56, "no": 0.44},
    "a=no|b=no": {"yes": 0.41, "no": 0.59},
}
PARENT_MARGINALS = {
    "a": {"yes": 0.57, "no": 0.43},
    "b": {"yes": 0.54, "no": 0.46},
}


def compile_with_parents():
    return CURRENT_MODEL_COMPILER.compile_result(
        market_snapshot=MARKET,
        conditional_marginals=CONDITIONALS,
        market_outcomes_by_variable={"a": 2, "b": 2},
        parent_marginals=PARENT_MARGINALS,
        last_updated="2026-01-01T00:00:00Z",
    )


class PartialContextMarginalizationTests(unittest.TestCase):
    def test_full_context_uses_exact_cpt_row(self):
        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_with_parents(), context={"a": "yes", "b": "yes"}
        )
        self.assertAlmostEqual(result.marginals["yes"], 0.79)
        self.assertEqual(result.metadata["resolutionSource"], "conditional")

    def test_partial_context_marginalizes_over_unassigned_parent(self):
        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_with_parents(), context={"a": "yes"}
        )
        expected = 0.79 * 0.54 + 0.67 * 0.46
        self.assertAlmostEqual(result.marginals["yes"], expected, places=9)
        self.assertAlmostEqual(result.marginals["no"], 1.0 - expected, places=9)
        self.assertEqual(result.metadata["resolutionSource"], "conditional_marginalized")

    def test_unrelated_context_falls_back_to_unconditional(self):
        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_with_parents(), context={"unrelated_var": "yes"}
        )
        self.assertAlmostEqual(result.marginals["yes"], 0.65)
        self.assertEqual(result.metadata["resolutionSource"], "unconditional")

    def test_mixed_relevant_and_unrelated_context_uses_relevant_evidence(self):
        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_with_parents(), context={"a": "yes", "unrelated_var": "no"}
        )
        expected = 0.79 * 0.54 + 0.67 * 0.46
        self.assertAlmostEqual(result.marginals["yes"], expected, places=9)
        self.assertEqual(result.metadata["resolutionSource"], "conditional_marginalized")

    def test_partial_context_without_parent_priors_falls_back(self):
        compile_result = CURRENT_MODEL_COMPILER.compile_result(
            market_snapshot=MARKET,
            conditional_marginals=CONDITIONALS,
            market_outcomes_by_variable={"a": 2, "b": 2},
            last_updated="2026-01-01T00:00:00Z",
        )
        result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_result, context={"a": "yes"}
        )
        self.assertAlmostEqual(result.marginals["yes"], 0.65)
        self.assertEqual(result.metadata["resolutionSource"], "unconditional")

    def test_hash_stable_when_no_parent_marginals(self):
        without_parents_a = CURRENT_MODEL_COMPILER.compile_result(
            market_snapshot=MARKET,
            conditional_marginals=CONDITIONALS,
            market_outcomes_by_variable={"a": 2, "b": 2},
            last_updated="2026-01-01T00:00:00Z",
        )
        without_parents_b = CURRENT_MODEL_COMPILER.compile_result(
            market_snapshot=MARKET,
            conditional_marginals=CONDITIONALS,
            market_outcomes_by_variable={"a": 2, "b": 2},
            last_updated="2026-01-01T00:00:00Z",
        )
        self.assertEqual(
            without_parents_a.source_state_hash, without_parents_b.source_state_hash
        )


if __name__ == "__main__":
    unittest.main()
