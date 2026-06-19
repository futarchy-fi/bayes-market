from __future__ import annotations

import importlib.util
import pathlib
import unittest
from copy import deepcopy

ROOT = pathlib.Path(__file__).resolve().parents[1]
FORMULA_SCHEMA_PATH = ROOT / "backend" / "formula_schema.py"
SERVER_PATH = ROOT / "backend" / "server.py"

formula_schema_spec = importlib.util.spec_from_file_location("bayes_market_formula_schema_test", FORMULA_SCHEMA_PATH)
formula_schema = importlib.util.module_from_spec(formula_schema_spec)
assert formula_schema_spec is not None
assert formula_schema_spec.loader is not None
formula_schema_spec.loader.exec_module(formula_schema)

server_spec = importlib.util.spec_from_file_location("bayes_market_server_for_formula_schema_test", SERVER_PATH)
server = importlib.util.module_from_spec(server_spec)
assert server_spec is not None
assert server_spec.loader is not None
server_spec.loader.exec_module(server)


class BayesMarketFormulaSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markets = deepcopy(server.INITIAL_MARKETS)
        self.variable_id_to_market = {
            str(market["variableId"]): market for market in self.markets.values()
        }

    def lookup_market_by_id(self, market_id: str) -> dict[str, object] | None:
        return self.markets.get(market_id)

    def lookup_market_by_variable_id(self, variable_id: str) -> dict[str, object] | None:
        return self.variable_id_to_market.get(variable_id)

    def build_validator(self) -> object:
        return formula_schema.FormulaValidator(
            lookup_market_by_variable_id=self.lookup_market_by_variable_id,
        )

    def build_adapter(self) -> object:
        return formula_schema.EventTradeFormulaAdapter(
            lookup_market_by_id=self.lookup_market_by_id,
            lookup_market_by_variable_id=self.lookup_market_by_variable_id,
        )

    def test_formula_validator_rejects_non_cnf_clause_objects(self):
        validator = self.build_validator()

        self.assertFalse(validator.validate([{"op": "AND", "conditions": []}]))
        self.assertEqual(validator.last_error.code, "invalid_event_formula")
        self.assertEqual(validator.last_error.details["field"], "formula[0]")

    def test_formula_validator_rejects_old_multi_condition_not_shape(self):
        validator = self.build_validator()

        self.assertFalse(
            validator.validate(
                [
                    [
                        {
                            "op": "NOT",
                            "conditions": [
                                {"variableId": "frontier_capability_breakthrough_2028", "outcomeId": "yes"},
                                {"variableId": "autonomous_ai_coding_deployment_2028", "outcomeId": "yes"},
                            ],
                        }
                    ]
                ]
            )
        )
        self.assertEqual(validator.last_error.code, "invalid_event_formula")
        self.assertEqual(validator.last_error.details["field"], "formula[0][0].variableId")

    def test_formula_validator_rejects_literals_with_unexpected_fields(self):
        validator = self.build_validator()

        self.assertFalse(
            validator.validate(
                [
                    [
                        {
                            "variableId": "frontier_capability_breakthrough_2028",
                            "outcomeId": "yes",
                            "negated": False,
                            "kind": "legacy",
                        }
                    ]
                ]
            )
        )
        self.assertEqual(validator.last_error.code, "invalid_event_formula")
        self.assertEqual(validator.last_error.details["field"], "formula[0][0]")
        self.assertEqual(validator.last_error.details["unexpected"], ["kind"])
        self.assertEqual(
            validator.last_error.details["allowed"],
            sorted(formula_schema.EVENT_FORMULA_LITERAL_FIELDS),
        )

    def test_formula_validator_normalizes_literals_by_variable_id(self):
        normalized = formula_schema.normalize_event_formula(
            [
                [
                    {"variableId": " frontier_ai_governance_regime_2030 ", "outcomeId": " no "},
                    {"variableId": "autonomous_ai_coding_deployment_2028", "outcomeId": " delayed ", "negated": True},
                ]
            ],
            lookup_market_by_variable_id=self.lookup_market_by_variable_id,
        )

        self.assertEqual(
            normalized,
            [
                [
                    {"variableId": "autonomous_ai_coding_deployment_2028", "outcomeId": "delayed", "negated": True},
                    {"variableId": "frontier_ai_governance_regime_2030", "outcomeId": "no", "negated": False},
                ]
            ],
        )

    def test_event_trade_adapter_translates_market_ids_and_restores_public_shape(self):
        adapter = self.build_adapter()

        normalized = adapter.normalize(
            [
                [
                    {"variableId": " m3 ", "outcomeId": " no "},
                    {"variableId": "m2", "outcomeId": " delayed ", "negated": True},
                ]
            ]
        )

        self.assertEqual(
            normalized,
            [
                [
                    {"variableId": "m2", "outcomeId": "delayed", "negated": True},
                    {"variableId": "m3", "outcomeId": "no", "negated": False},
                ]
            ],
        )

    def test_event_trade_adapter_rewrites_shared_validation_errors_to_market_ids(self):
        adapter = self.build_adapter()

        with self.assertRaises(formula_schema.FormulaSchemaError) as ctx:
            adapter.normalize([[{"variableId": "m1", "outcomeId": "delayed"}]])

        error = ctx.exception
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0].outcomeId")
        self.assertEqual(error.details["variableId"], "m1")
        self.assertEqual(error.details["received"], "delayed")

    def test_event_trade_adapter_rejects_internal_variable_ids_before_translation(self):
        adapter = self.build_adapter()

        with self.assertRaises(formula_schema.FormulaSchemaError) as ctx:
            adapter.normalize(
                [[{"variableId": "frontier_capability_breakthrough_2028", "outcomeId": "yes", "negated": False}]]
            )

        error = ctx.exception
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0].variableId")
        self.assertEqual(error.details["received"], "frontier_capability_breakthrough_2028")

    def test_event_trade_adapter_rejects_literals_with_unexpected_fields(self):
        adapter = self.build_adapter()

        with self.assertRaises(formula_schema.FormulaSchemaError) as ctx:
            adapter.normalize(
                [[{"variableId": "m1", "outcomeId": "yes", "negated": False, "kind": "legacy"}]]
            )

        error = ctx.exception
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0]")
        self.assertEqual(error.details["unexpected"], ["kind"])
        self.assertEqual(error.details["allowed"], sorted(formula_schema.EVENT_FORMULA_LITERAL_FIELDS))

    def test_event_trade_adapter_preserves_501_boundary_for_valid_broader_cnf(self):
        adapter = self.build_adapter()
        normalized = adapter.normalize(
            [
                [{"variableId": "m1", "outcomeId": "yes", "negated": False}],
                [{"variableId": "m2", "outcomeId": "yes", "negated": False}],
            ]
        )

        with self.assertRaises(formula_schema.FormulaSchemaError) as ctx:
            adapter.require_atomic(normalized)

        error = ctx.exception
        self.assertEqual(error.status, 501)
        self.assertEqual(error.code, "event_trade_inference_unavailable")
        self.assertEqual(error.details["supportedShape"], "single_clause_single_literal_non_negated")


if __name__ == "__main__":
    unittest.main()
