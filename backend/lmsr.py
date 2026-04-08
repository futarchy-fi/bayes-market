#!/usr/bin/env python3
"""Pure LMSR math helpers for probability-edit quoting."""

from __future__ import annotations

import math
from typing import Any, Mapping

PROBABILITY_SUM_TOLERANCE = 1e-9


def _validate_distribution(
    distribution: Mapping[str, Any],
    *,
    name: str,
    require_strictly_positive: bool,
) -> dict[str, float]:
    if not isinstance(distribution, dict):
        raise ValueError(f"{name} must be a dictionary")

    if len(distribution) < 2:
        raise ValueError(f"{name} must contain at least two outcomes")

    normalized: dict[str, float] = {}
    for outcome_id, value in distribution.items():
        normalized_outcome_id = str(outcome_id)
        if not normalized_outcome_id:
            raise ValueError(f"{name} outcome ids must be non-empty strings")
        if normalized_outcome_id in normalized:
            raise ValueError(f"{name} outcome ids must be unique")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must contain numeric values for all outcomes")
        probability = float(value)
        if not math.isfinite(probability):
            raise ValueError(f"{name} must contain finite numeric values for all outcomes")
        normalized[normalized_outcome_id] = probability

    if require_strictly_positive:
        if any(probability <= 0.0 for probability in normalized.values()):
            raise ValueError(f"{name} must contain strictly positive probabilities for all outcomes")
    else:
        if any(probability < 0.0 for probability in normalized.values()):
            raise ValueError(f"{name} must contain non-negative probabilities for all outcomes")

    if not math.isclose(sum(normalized.values()), 1.0, abs_tol=PROBABILITY_SUM_TOLERANCE):
        raise ValueError(f"{name} must sum to 1.0")

    return normalized


def _validate_target_probability(target_probability: Any) -> float:
    if isinstance(target_probability, bool) or not isinstance(target_probability, (int, float)):
        raise ValueError("target_probability must be a number")

    normalized_probability = float(target_probability)
    if not math.isfinite(normalized_probability):
        raise ValueError("target_probability must be finite")
    if not (0.0 < normalized_probability < 1.0):
        raise ValueError("target_probability must be greater than 0 and less than 1")
    return normalized_probability


def _validate_liquidity(liquidity: Any) -> float:
    if isinstance(liquidity, bool) or not isinstance(liquidity, (int, float)):
        raise ValueError("liquidity must be a number")

    normalized_liquidity = float(liquidity)
    if not math.isfinite(normalized_liquidity):
        raise ValueError("liquidity must be finite")
    if normalized_liquidity <= 0.0:
        raise ValueError("liquidity must be greater than 0")
    return normalized_liquidity


def _validate_quote_inputs(
    previous: Mapping[str, Any],
    updated: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, float]]:
    normalized_previous = _validate_distribution(
        previous,
        name="previous",
        require_strictly_positive=True,
    )
    normalized_updated = _validate_distribution(
        updated,
        name="updated",
        require_strictly_positive=True,
    )
    if set(normalized_previous) != set(normalized_updated):
        raise ValueError("previous and updated must contain the same outcomes")
    return normalized_previous, normalized_updated


def rescale_probability_edit(
    previous: Mapping[str, Any],
    outcome_id: str,
    target_probability: float,
) -> dict[str, float]:
    """Rescale a distribution so one outcome reaches a target probability."""
    normalized_previous = _validate_distribution(
        previous,
        name="previous",
        require_strictly_positive=False,
    )
    normalized_target_probability = _validate_target_probability(target_probability)
    normalized_outcome_id = str(outcome_id)

    if normalized_outcome_id not in normalized_previous:
        raise ValueError("outcome_id must match a known outcome")

    other_outcome_ids = [candidate for candidate in normalized_previous if candidate != normalized_outcome_id]
    if not other_outcome_ids:
        raise ValueError("previous must contain at least two outcomes")

    previous_other_total = sum(normalized_previous[candidate] for candidate in other_outcome_ids)
    remaining_probability = 1.0 - normalized_target_probability
    if previous_other_total <= 0.0:
        scaled_others = {
            candidate: remaining_probability / len(other_outcome_ids) for candidate in other_outcome_ids
        }
    else:
        scaled_others = {
            candidate: normalized_previous[candidate] / previous_other_total * remaining_probability
            for candidate in other_outcome_ids
        }

    updated = {normalized_outcome_id: normalized_target_probability, **scaled_others}
    rounding_drift = 1.0 - sum(updated.values())
    if rounding_drift != 0.0:
        updated[other_outcome_ids[-1]] += rounding_drift
    return updated


def lmsr_score_delta(
    previous: Mapping[str, Any],
    updated: Mapping[str, Any],
    liquidity: float,
) -> dict[str, float]:
    """Compute the per-outcome LMSR score delta for a probability edit."""
    normalized_previous, normalized_updated = _validate_quote_inputs(previous, updated)
    normalized_liquidity = _validate_liquidity(liquidity)
    return {
        outcome_id: normalized_liquidity * math.log(normalized_updated[outcome_id] / normalized_previous[outcome_id])
        for outcome_id in normalized_previous
    }


def lmsr_expected_edit_cost(
    previous: Mapping[str, Any],
    updated: Mapping[str, Any],
    liquidity: float,
) -> float:
    """Compute the expected LMSR cost of moving between two distributions."""
    normalized_previous, normalized_updated = _validate_quote_inputs(previous, updated)
    normalized_liquidity = _validate_liquidity(liquidity)
    return sum(
        normalized_updated[outcome_id]
        * normalized_liquidity
        * math.log(normalized_updated[outcome_id] / normalized_previous[outcome_id])
        for outcome_id in normalized_previous
    )


def quote_probability_edit(
    previous: Mapping[str, Any],
    outcome_id: str,
    target_probability: float,
    liquidity: float,
) -> dict[str, Any]:
    """Return the updated distribution, score deltas, and total edit cost."""
    updated = rescale_probability_edit(previous, outcome_id, target_probability)
    score_delta = lmsr_score_delta(previous, updated, liquidity)
    return {
        "updated": updated,
        "score_delta": score_delta,
        "cost": sum(updated[outcome_id] * score_delta[outcome_id] for outcome_id in updated),
    }
