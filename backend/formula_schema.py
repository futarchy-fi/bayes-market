#!/usr/bin/env python3
"""Shared EventTrade CNF validator and public EventTrade formula adapter."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Optional

MAX_EVENT_FORMULA_CLAUSES = 16
MAX_EVENT_FORMULA_CLAUSE_LITERALS = 8
EVENT_FORMULA_LITERAL_FIELDS = frozenset({"negated", "outcomeId", "variableId"})

MarketLookup = Callable[[str], Optional[dict[str, Any]]]
ErrorFactory = Callable[[int, str, str, Optional[dict[str, Any]]], Exception]


class FormulaSchemaError(Exception):
    """Represent a formula validation error using the API-style error shape."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a validation error with status, code, and optional details."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _raise(
    error_factory: ErrorFactory,
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    raise error_factory(status, code, message, details)


def _market_outcome_ids(market: dict[str, Any]) -> frozenset[str]:
    return frozenset(str(outcome["id"]) for outcome in market["outcomes"])


def normalize_event_formula(
    formula: Any,
    *,
    lookup_market_by_variable_id: MarketLookup,
    error_factory: ErrorFactory = FormulaSchemaError,
    max_clauses: int = MAX_EVENT_FORMULA_CLAUSES,
    max_clause_literals: int = MAX_EVENT_FORMULA_CLAUSE_LITERALS,
) -> list[list[dict[str, Any]]]:
    """Normalize a CNF formula that references markets by variable id."""
    if not isinstance(formula, list):
        _raise(error_factory, 400, "invalid_event_formula", "formula must be an array", {"field": "formula"})

    if not formula:
        _raise(error_factory, 400, "invalid_event_formula", "formula must not be empty", {"field": "formula"})

    if len(formula) > max_clauses:
        _raise(
            error_factory,
            400,
            "invalid_event_formula",
            f"formula must contain at most {max_clauses} clauses",
            {"field": "formula", "maximum": max_clauses, "received": len(formula)},
        )

    normalized_formula: list[list[dict[str, Any]]] = []
    for clause_index, clause in enumerate(formula):
        clause_field = f"formula[{clause_index}]"
        if not isinstance(clause, list):
            _raise(
                error_factory,
                400,
                "invalid_event_formula",
                "formula clauses must be arrays",
                {"field": clause_field},
            )

        if not clause:
            _raise(
                error_factory,
                400,
                "invalid_event_formula",
                "formula clauses must not be empty",
                {"field": clause_field},
            )

        if len(clause) > max_clause_literals:
            _raise(
                error_factory,
                400,
                "invalid_event_formula",
                f"formula clauses must contain at most {max_clause_literals} literals",
                {
                    "field": clause_field,
                    "maximum": max_clause_literals,
                    "received": len(clause),
                },
            )

        normalized_literals: list[tuple[str, str, bool]] = []
        seen_literals: set[tuple[str, str, bool]] = set()
        for literal_index, literal in enumerate(clause):
            literal_field = f"{clause_field}[{literal_index}]"
            if not isinstance(literal, dict):
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "formula literals must be objects",
                    {"field": literal_field},
                )

            raw_variable_id = literal.get("variableId")
            if not isinstance(raw_variable_id, str) or not raw_variable_id.strip():
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "variableId is required",
                    {"field": f"{literal_field}.variableId"},
                )
            normalized_variable_id = raw_variable_id.strip()

            raw_outcome_id = literal.get("outcomeId")
            if not isinstance(raw_outcome_id, str) or not raw_outcome_id.strip():
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "outcomeId is required",
                    {"field": f"{literal_field}.outcomeId"},
                )
            normalized_outcome_id = raw_outcome_id.strip()

            referenced_market = lookup_market_by_variable_id(normalized_variable_id)
            if referenced_market is None:
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "variableId must match a known market variable",
                    {"field": f"{literal_field}.variableId", "received": normalized_variable_id},
                )

            allowed_outcome_ids = _market_outcome_ids(referenced_market)
            if normalized_outcome_id not in allowed_outcome_ids:
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "outcomeId must match a known outcome for the referenced variable",
                    {
                        "field": f"{literal_field}.outcomeId",
                        "variableId": normalized_variable_id,
                        "received": normalized_outcome_id,
                    },
                )

            negated = literal.get("negated", False)
            if not isinstance(negated, bool):
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "negated must be a boolean",
                    {"field": f"{literal_field}.negated", "received": negated},
                )

            unexpected_fields = sorted(
                str(field_name) for field_name in literal if str(field_name) not in EVENT_FORMULA_LITERAL_FIELDS
            )
            if unexpected_fields:
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "formula literals contain unexpected fields",
                    {
                        "field": literal_field,
                        "allowed": sorted(EVENT_FORMULA_LITERAL_FIELDS),
                        "unexpected": unexpected_fields,
                    },
                )

            normalized_literal = (
                normalized_variable_id,
                normalized_outcome_id,
                negated,
            )
            if normalized_literal in seen_literals:
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "formula clauses must not contain duplicate literals",
                    {
                        "field": literal_field,
                        "variableId": normalized_variable_id,
                        "outcomeId": normalized_outcome_id,
                        "negated": negated,
                    },
                )

            seen_literals.add(normalized_literal)
            normalized_literals.append(normalized_literal)

        normalized_formula.append(
            [
                {
                    "variableId": variable_id,
                    "outcomeId": outcome_id,
                    "negated": negated,
                }
                for variable_id, outcome_id, negated in sorted(normalized_literals)
            ]
        )

    return normalized_formula


def validate_event_trade_formula_market_ids(
    formula: Any,
    *,
    lookup_market_by_id: MarketLookup,
    error_factory: ErrorFactory = FormulaSchemaError,
) -> None:
    """Validate that any market-id references in a formula resolve successfully."""
    if not isinstance(formula, list):
        return

    for clause_index, clause in enumerate(formula):
        if not isinstance(clause, list):
            continue

        for literal_index, literal in enumerate(clause):
            if not isinstance(literal, dict):
                continue

            raw_variable_id = literal.get("variableId")
            if not isinstance(raw_variable_id, str):
                continue

            normalized_market_id = raw_variable_id.strip()
            if normalized_market_id and lookup_market_by_id(normalized_market_id) is None:
                _raise(
                    error_factory,
                    400,
                    "invalid_event_formula",
                    "variableId must match a known market id",
                    {
                        "field": f"formula[{clause_index}][{literal_index}].variableId",
                        "received": normalized_market_id,
                    },
                )


def translate_event_trade_formula_for_validation(
    formula: Any,
    *,
    lookup_market_by_id: MarketLookup,
) -> Any:
    """Translate market-id literals into variable-id literals for validation."""
    if not isinstance(formula, list):
        return formula

    translated_formula: list[Any] = []
    for clause in formula:
        if not isinstance(clause, list):
            translated_formula.append(clause)
            continue

        translated_clause: list[Any] = []
        for literal in clause:
            if not isinstance(literal, dict):
                translated_clause.append(literal)
                continue

            translated_literal = deepcopy(literal)
            raw_variable_id = literal.get("variableId")
            if isinstance(raw_variable_id, str):
                market = lookup_market_by_id(raw_variable_id.strip())
                if market is not None:
                    translated_literal["variableId"] = str(market["variableId"])
            translated_clause.append(translated_literal)
        translated_formula.append(translated_clause)

    return translated_formula


def restore_event_trade_formula_market_ids(
    normalized_formula: list[list[dict[str, Any]]],
    *,
    lookup_market_by_variable_id: MarketLookup,
) -> list[list[dict[str, Any]]]:
    """Restore public market ids into a normalized formula representation."""
    restored_formula: list[list[dict[str, Any]]] = []
    for clause in normalized_formula:
        restored_clause: list[dict[str, Any]] = []
        for literal in clause:
            referenced_market = lookup_market_by_variable_id(str(literal["variableId"]))
            restored_clause.append(
                {
                    "variableId": (
                        str(referenced_market["id"])
                        if referenced_market is not None
                        else str(literal["variableId"])
                    ),
                    "outcomeId": str(literal["outcomeId"]),
                    "negated": bool(literal.get("negated", False)),
                }
            )
        restored_formula.append(restored_clause)
    return restored_formula


def normalize_event_trade_formula(
    formula: Any,
    *,
    lookup_market_by_id: MarketLookup,
    lookup_market_by_variable_id: MarketLookup,
    error_factory: ErrorFactory = FormulaSchemaError,
    max_clauses: int = MAX_EVENT_FORMULA_CLAUSES,
    max_clause_literals: int = MAX_EVENT_FORMULA_CLAUSE_LITERALS,
) -> list[list[dict[str, Any]]]:
    """Normalize a public EventTrade formula that may reference market ids."""
    validate_event_trade_formula_market_ids(
        formula,
        lookup_market_by_id=lookup_market_by_id,
        error_factory=error_factory,
    )

    try:
        normalized_formula = normalize_event_formula(
            translate_event_trade_formula_for_validation(
                formula,
                lookup_market_by_id=lookup_market_by_id,
            ),
            lookup_market_by_variable_id=lookup_market_by_variable_id,
            error_factory=error_factory,
            max_clauses=max_clauses,
            max_clause_literals=max_clause_literals,
        )
    except Exception as exc:
        if getattr(exc, "code", None) != "invalid_event_formula":
            raise

        translated_details = deepcopy(getattr(exc, "details", {}))
        variable_id = translated_details.get("variableId")
        if isinstance(variable_id, str):
            referenced_market = lookup_market_by_variable_id(variable_id)
            if referenced_market is not None:
                translated_details["variableId"] = str(referenced_market["id"])

        _raise(
            error_factory,
            int(getattr(exc, "status", 400)),
            str(getattr(exc, "code")),
            str(getattr(exc, "message", str(exc))),
            translated_details,
        )

    return restore_event_trade_formula_market_ids(
        normalized_formula,
        lookup_market_by_variable_id=lookup_market_by_variable_id,
    )


def require_atomic_event_trade_formula(
    formula: list[list[dict[str, Any]]],
    *,
    error_factory: ErrorFactory = FormulaSchemaError,
) -> dict[str, Any]:
    """Require that a normalized formula is one non-negated atomic literal."""
    clause_count = len(formula)
    literal_count = len(formula[0]) if clause_count == 1 else None
    negated = bool(formula[0][0]["negated"]) if clause_count == 1 and literal_count == 1 else None

    if clause_count != 1 or literal_count != 1 or negated:
        _raise(
            error_factory,
            501,
            "event_trade_inference_unavailable",
            "EventTrade currently supports only a single non-negated atomic literal",
            {
                "supportedShape": "single_clause_single_literal_non_negated",
                "receivedClauseCount": clause_count,
                "receivedLiteralCount": literal_count,
                "receivedNegated": negated,
            },
        )
    return formula[0][0]


class FormulaValidator:
    """Reusable validator for the shared CNF-shaped EventTrade payload."""

    def __init__(
        self,
        *,
        lookup_market_by_variable_id: MarketLookup,
        error_factory: ErrorFactory = FormulaSchemaError,
        max_clauses: int = MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals: int = MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    ) -> None:
        """Initialize a validator that works directly with variable ids."""
        self.lookup_market_by_variable_id = lookup_market_by_variable_id
        self.error_factory = error_factory
        self.max_clauses = max_clauses
        self.max_clause_literals = max_clause_literals
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.last_error: Exception | None = None

    def normalize(self, formula: Any) -> list[list[dict[str, Any]]]:
        """Normalize a shared CNF formula or raise a schema error."""
        return normalize_event_formula(
            formula,
            lookup_market_by_variable_id=self.lookup_market_by_variable_id,
            error_factory=self.error_factory,
            max_clauses=self.max_clauses,
            max_clause_literals=self.max_clause_literals,
        )

    def validate(self, formula: Any) -> bool:
        """Validate a formula and store any failure details on the instance."""
        self.errors = []
        self.warnings = []
        self.last_error = None
        try:
            self.normalize(formula)
        except Exception as exc:
            self.last_error = exc
            self.errors.append(str(getattr(exc, "message", exc)))
            return False
        return True


class EventTradeFormulaAdapter:
    """Route-local adapter that accepts market ids and preserves public error semantics."""

    def __init__(
        self,
        *,
        lookup_market_by_id: MarketLookup,
        lookup_market_by_variable_id: MarketLookup,
        error_factory: ErrorFactory = FormulaSchemaError,
        max_clauses: int = MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals: int = MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    ) -> None:
        """Initialize an adapter that accepts market ids at the API boundary."""
        self.lookup_market_by_id = lookup_market_by_id
        self.lookup_market_by_variable_id = lookup_market_by_variable_id
        self.error_factory = error_factory
        self.max_clauses = max_clauses
        self.max_clause_literals = max_clause_literals
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.last_error: Exception | None = None

    def normalize(self, formula: Any) -> list[list[dict[str, Any]]]:
        """Normalize a public EventTrade formula into canonical clause form."""
        return normalize_event_trade_formula(
            formula,
            lookup_market_by_id=self.lookup_market_by_id,
            lookup_market_by_variable_id=self.lookup_market_by_variable_id,
            error_factory=self.error_factory,
            max_clauses=self.max_clauses,
            max_clause_literals=self.max_clause_literals,
        )

    def validate(self, formula: Any) -> bool:
        """Validate a public EventTrade formula and capture failure details."""
        self.errors = []
        self.warnings = []
        self.last_error = None
        try:
            self.normalize(formula)
        except Exception as exc:
            self.last_error = exc
            self.errors.append(str(getattr(exc, "message", exc)))
            return False
        return True

    def require_atomic(self, formula: list[list[dict[str, Any]]]) -> dict[str, Any]:
        """Require that a public EventTrade formula resolves to one atomic literal."""
        return require_atomic_event_trade_formula(formula, error_factory=self.error_factory)


__all__ = [
    "EVENT_FORMULA_LITERAL_FIELDS",
    "EventTradeFormulaAdapter",
    "FormulaSchemaError",
    "FormulaValidator",
    "MAX_EVENT_FORMULA_CLAUSE_LITERALS",
    "MAX_EVENT_FORMULA_CLAUSES",
    "normalize_event_formula",
    "normalize_event_trade_formula",
    "require_atomic_event_trade_formula",
    "restore_event_trade_formula_market_ids",
    "translate_event_trade_formula_for_validation",
    "validate_event_trade_formula_market_ids",
]
