#!/usr/bin/env python3
"""Stage 3 (backtest core): flat vs combinatorial on REAL resolved questions.

The live-experiment fast verdict. Uses real, already-resolved, relationally-
linked Manifold questions (asset price-threshold ladders sourced by
fetch_backtest_questions.py) whose ground truth is known and whose logical
structure is exact: "above $X" implies "above $Y" for Y<X on the same date.

The combinatorial market encodes that implication (a 0/1-ish CPT chain — the
same exact-implication rows the FTM compiler uses); the flat market treats
each threshold independently. A population of forecasters gets a noisy
point-in-time estimate of the price and trades. We then score the final
market prices against the REAL resolved outcomes (the monotone step at the
true price), flat vs combinatorial.

This module is the harness core, validated here with a calibrated behavior
model (the empirically-observed agent behavior from Stages 1/1b). The live
run swaps the behavior model for real LLM agents via the exchange MCP — same
loader, markets, and scorer.

    PYTHONPATH=. python3 scripts/experiments/stage3_backtest.py
"""

from __future__ import annotations

import math
import random

from backend.inference.factored_market import FactoredMarket
from scripts.experiments.fetch_backtest_questions import collect_ladders

YES, NO = "yes", "no"
OUTCOMES = (YES, NO)
SEED = 20260715


def ladder_to_case(lad: dict) -> dict:
    """A backtest case: thresholds ascending, real outcomes, true price bracket."""
    members = sorted(lad["members"], key=lambda m: m["threshold"])
    return {
        "asset": lad["asset"], "date": lad["dateKey"],
        "thresholds": [m["threshold"] for m in members],
        "titles": [m["title"] for m in members],
        "outcomes": [1 if m["resolution"] == "YES" else 0 for m in members],
        "true_lo": lad["impliedPrice"][0],   # highest YES threshold
        "true_hi": lad["impliedPrice"][1],   # lowest NO threshold
    }


# --- markets ---------------------------------------------------------------

def _var(i: int) -> str:
    return f"t{i}"


def build_flat(n: int, liq=100.0) -> FactoredMarket:
    nodes = [{"variable_id": _var(i), "outcomes": OUTCOMES, "parents": (),
              "rows": {frozenset(): {YES: 0.5, NO: 0.5}}} for i in range(n)]
    return FactoredMarket.from_nodes(nodes, liq, max_width=4)


def build_comb(n: int, liq=100.0) -> FactoredMarket:
    """Implication chain: above-t_{i+1} (higher) implies above-t_i (lower).

    t_i's parent is t_{i+1}; P(t_i=yes | t_{i+1}=yes) ~ 1 (structural
    implication), P(t_i=yes | t_{i+1}=no) free (learned), init at independence.
    """
    nodes = []
    for i in range(n):
        if i == n - 1:  # highest threshold = root
            nodes.append({"variable_id": _var(i), "outcomes": OUTCOMES,
                          "parents": (), "rows": {frozenset(): {YES: 0.5, NO: 0.5}}})
        else:
            parent = _var(i + 1)
            nodes.append({"variable_id": _var(i), "outcomes": OUTCOMES,
                          "parents": (parent,), "rows": {
                              frozenset({(parent, YES)}): {YES: 0.999, NO: 0.001},
                              frozenset({(parent, NO)}): {YES: 0.5, NO: 0.5}}})
    return FactoredMarket.from_nodes(nodes, liq, max_width=4)


def _clip(x, lo=0.02, hi=0.98):
    return max(lo, min(hi, x))


# --- behavior-model forecasters --------------------------------------------

def run_case(case: dict, combinatorial: bool, n_agents=8, rounds=30,
             alpha=0.2, price_noise=0.08, seed=SEED):
    """Forecasters get a noisy fractional price estimate and trade each
    threshold's marginal toward P(price >= threshold)."""
    rng = random.Random(seed + (1 if combinatorial else 0))
    n = len(case["thresholds"])
    m = build_comb(n) if combinatorial else build_flat(n)
    lo, hi = case["true_lo"], case["true_hi"]
    span = max(hi - lo, 1.0)
    true_price = (lo + hi) / 2 if lo > 0 and hi < 1e17 else (hi if lo <= 0 else lo)
    thr = case["thresholds"]

    for _ in range(rounds):
        for _ in range(n_agents):
            # a noisy point-in-time estimate of the settlement price
            est = true_price * (1 + rng.gauss(0, price_noise))
            i = rng.randrange(n)
            # forecaster's belief P(price >= threshold_i): logistic in the gap
            belief = 1 / (1 + math.exp(-(est - thr[i]) / (span * 0.5)))
            cur = m.marginal(_var(i), {})[YES]
            try:
                m.trade_to_probability(_var(i), YES, _clip(cur + alpha * (belief - cur)))
            except Exception:
                pass
    return [m.marginal(_var(i), {})[YES] for i in range(n)]


def brier(preds, outcomes):
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def monotonicity_violation(preds):
    """Thresholds ascending -> P(above) should be non-increasing. Sum of
    upward jumps = how incoherent the market is (0 = perfectly coherent)."""
    return sum(max(0.0, preds[i + 1] - preds[i]) for i in range(len(preds) - 1))


def main():
    print("sourcing real resolved threshold ladders from Manifold…")
    ladders = collect_ladders(min_len=3)
    cases = [ladder_to_case(l) for l in ladders]
    print(f"{len(cases)} real backtest cases\n")

    tot = {"bf": 0.0, "bc": 0.0, "vf": 0.0, "vc": 0.0}
    print(f"{'case':22} {'n':>2} {'Brier flat':>10} {'Brier comb':>10} "
          f"{'viol flat':>9} {'viol comb':>9}")
    for c in cases:
        pf = run_case(c, combinatorial=False)
        pc = run_case(c, combinatorial=True)
        bf, bc = brier(pf, c["outcomes"]), brier(pc, c["outcomes"])
        vf, vc = monotonicity_violation(pf), monotonicity_violation(pc)
        tot["bf"] += bf; tot["bc"] += bc; tot["vf"] += vf; tot["vc"] += vc
        label = f"{c['asset']} {c['date']}"
        print(f"{label:22} {len(c['thresholds']):>2} {bf:>10.4f} {bc:>10.4f} "
              f"{vf:>9.3f} {vc:>9.3f}")

    k = max(len(cases), 1)
    print(f"\nmean Brier  flat={tot['bf']/k:.4f}  comb={tot['bc']/k:.4f}  "
          f"(lower is better; comb improvement {(tot['bf']-tot['bc'])/k:+.4f})")
    print(f"mean monotonicity violation  flat={tot['vf']/k:.3f}  "
          f"comb={tot['vc']/k:.3f}  (0 = coherent)")
    print("\nNote: harness validated with the calibrated behavior model. The live "
          "run swaps in real LLM agents via the exchange MCP; same loader/scorer.")


if __name__ == "__main__":
    main()
