#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from itertools import product
from pathlib import Path


OUTCOMES = ("yes", "no")


def clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return min(high, max(low, value))


def probability_pair(yes_probability: float) -> dict[str, float]:
    yes = round(clamp(yes_probability), 6)
    return {"yes": yes, "no": round(1.0 - yes, 6)}


def build_context_key(assignments: list[tuple[str, str]]) -> str:
    return "|".join(f"{variable_id}={outcome_id}" for variable_id, outcome_id in assignments)


def build_market(index: int, yes_probability: float) -> dict[str, object]:
    number = index + 1
    market_id = f"seed_synth_{number:04d}"
    variable_id = f"synthetic_var_{number:04d}"
    return {
        "id": market_id,
        "title": f"Synthetic calibration market {number:04d}",
        "description": "Synthetic scale seed used for staging and graph-load verification.",
        "variableId": variable_id,
        "status": "active",
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": probability_pair(yes_probability),
        "liquidity": round(75000.0 + number * 11.0, 2),
        "volume": round(1000.0 + number * 3.5, 2),
        "created_at": "2026-07-04T00:00:00Z",
        "expires_at": "2031-12-31T23:59:59Z",
        "provenance": {
            "source": "synthetic",
            "ref": f"synthetic:{market_id}",
            "method": "scripts/make_synthetic_seeds.py",
            "fetchedAt": "2026-07-04T00:00:00Z",
        },
        "anchor": {
            "source": "synthetic",
            "ref": f"anchor:{market_id}",
            "url": "https://example.invalid/synthetic-seeds",
            "value": round(yes_probability, 4),
            "fetchedAt": "2026-07-04T00:00:00Z",
        },
        "ftmImplied": round(yes_probability, 4),
    }


def build_synthetic_seeds(count: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    markets: dict[str, dict[str, object]] = {}
    conditionals: dict[str, dict[str, dict[str, float]]] = {}
    variable_ids: list[str] = []
    root_count = max(1, min(25, count // 50 or 1))

    for index in range(count):
        base_probability = rng.uniform(0.22, 0.78)
        market = build_market(index, base_probability)
        market_id = str(market["id"])
        variable_id = str(market["variableId"])
        markets[market_id] = market
        variable_ids.append(variable_id)

        if index < root_count:
            continue

        parent_indices = [rng.randrange(0, index)]
        if index > 2 and rng.random() < 0.05:
            candidates = [candidate for candidate in range(index) if candidate not in parent_indices]
            parent_indices.append(rng.choice(candidates))
        parent_variables = [variable_ids[parent_index] for parent_index in parent_indices]
        effects = [rng.uniform(0.08, 0.18) for _ in parent_variables]
        rows: dict[str, dict[str, float]] = {}
        for outcomes in product(OUTCOMES, repeat=len(parent_variables)):
            yes_probability = base_probability
            assignments: list[tuple[str, str]] = []
            for parent_variable, outcome_id, effect in zip(parent_variables, outcomes, effects):
                assignments.append((parent_variable, outcome_id))
                yes_probability += effect if outcome_id == "yes" else -effect
            rows[build_context_key(assignments)] = probability_pair(yes_probability)
        conditionals[market_id] = rows

    return {"version": "seeds-v1", "markets": markets, "conditionalMarginals": conditionals}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic bayes-market seed records.")
    parser.add_argument("output", nargs="?", help="Optional output path. Defaults to stdout.")
    parser.add_argument(
        "-n", "--n", "--count", dest="count", type=int, default=1000, help="Number of markets to generate."
    )
    parser.add_argument("--seed", type=int, default=20260704, help="Deterministic random seed.")
    parser.add_argument("--output", dest="output_flag", help="Output path, equivalent to the positional path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("count must be at least 1")
    payload = build_synthetic_seeds(args.count, args.seed)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    output_path = args.output_flag or args.output
    if output_path:
        Path(output_path).write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
