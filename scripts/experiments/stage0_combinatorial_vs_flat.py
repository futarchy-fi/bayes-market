#!/usr/bin/env python3
"""Stage 0: does the combinatorial (junction-tree) market aggregate relational
information better than independent flat markets?

The SciCast/DAGGRE question, on this engine, with scripted bots (Stage 1 swaps
bots for LLM agents). Both markets are driven by the SAME real engine class
(backend.inference.FactoredMarket) and start from the IDENTICAL uniform joint;
the only difference is structure:

  - FLAT: N independent root markets. A trade on one never moves another.
  - COMBINATORIAL: the same variables wired with the TRUE graph's cliques, but
    CPTs initialized to independence — so it starts equal to FLAT and can only
    *learn* dependence through conditional trades.

Ground truth is a synthetic Bayesian network we control (so we can score
against a known joint and design the information). Bots aggregate noisy signals
by moving prices a fraction alpha toward each observation (a bounded-trade
averaging process). BOTH markets always receive the marginal signals (shared,
fair information); the combinatorial market additionally receives conditional
signals P(child|parent) at rate p_cond — the relational information a flat
market structurally cannot represent.

We sweep p_cond. The mandatory sanity check: at p_cond=0 (no extra relational
info) the two markets must tie, and the combinatorial market must NOT
hallucinate dependence. The interesting quantity is how the advantage grows
with p_cond.

Run:  PYTHONPATH=. python3 scripts/experiments/stage0_combinatorial_vs_flat.py
"""

from __future__ import annotations

import itertools
import math
import random
from decimal import Decimal  # noqa: F401  (engine uses floats here; kept for parity)

from backend.inference.factored_market import FactoredMarket

SEED = 20260715
YES, NO = "yes", "no"
OUTCOMES = (YES, NO)

# --- synthetic ground-truth Bayesian network (binary vars) -----------------
# P(var=yes | parents=assignment). Strong dependence = real relational info.
BN: dict[str, dict] = {
    "x0": {"parents": (), "cpt": {(): 0.50}},
    "x1": {"parents": ("x0",), "cpt": {(1,): 0.85, (0,): 0.15}},
    "x2": {"parents": ("x0",), "cpt": {(1,): 0.80, (0,): 0.10}},
    "x3": {"parents": ("x1",), "cpt": {(1,): 0.75, (0,): 0.20}},
    "x4": {"parents": ("x2",), "cpt": {(1,): 0.70, (0,): 0.25}},
    "x5": {"parents": ("x3", "x4"),
           "cpt": {(1, 1): 0.90, (1, 0): 0.55, (0, 1): 0.50, (0, 0): 0.10}},
}
VARS = list(BN)
TOPO = ["x0", "x1", "x2", "x3", "x4", "x5"]  # a valid topological order


# --- true joint by enumeration ---------------------------------------------

def _p_child_yes(var: str, assign: dict[str, int]) -> float:
    parents = BN[var]["parents"]
    key = tuple(assign[p] for p in parents)
    return BN[var]["cpt"][key]


def true_joint() -> dict[tuple[int, ...], float]:
    joint: dict[tuple[int, ...], float] = {}
    for bits in itertools.product((0, 1), repeat=len(VARS)):
        assign = dict(zip(VARS, bits))
        p = 1.0
        for var in VARS:
            py = _p_child_yes(var, assign)
            p *= py if assign[var] == 1 else (1.0 - py)
        joint[bits] = p
    return joint


TRUE = true_joint()


def true_marginal(var: str) -> float:
    i = VARS.index(var)
    return sum(p for bits, p in TRUE.items() if bits[i] == 1)


def true_conditional(child: str, parent: str, parent_val: int) -> float:
    ci, pi = VARS.index(child), VARS.index(parent)
    num = sum(p for bits, p in TRUE.items() if bits[pi] == parent_val and bits[ci] == 1)
    den = sum(p for bits, p in TRUE.items() if bits[pi] == parent_val)
    return num / den if den > 0 else 0.5


# --- market construction (both start at the identical uniform joint) --------

def _node(var: str, parents: tuple[str, ...]) -> dict:
    """A node whose CPT is independence at 0.5 — the uniform starting joint."""
    if not parents:
        return {"variable_id": var, "outcomes": OUTCOMES, "parents": (),
                "rows": {frozenset(): {YES: 0.5, NO: 0.5}}}
    rows = {}
    for combo in itertools.product(OUTCOMES, repeat=len(parents)):
        key = frozenset(zip(parents, combo))
        rows[key] = {YES: 0.5, NO: 0.5}
    return {"variable_id": var, "outcomes": OUTCOMES,
            "parents": tuple(sorted(parents)), "rows": rows}


def build_flat(liquidity: float) -> FactoredMarket:
    nodes = [_node(v, ()) for v in VARS]           # every var an independent root
    return FactoredMarket.from_nodes(nodes, liquidity, max_width=6)


def build_combinatorial(liquidity: float) -> FactoredMarket:
    nodes = [_node(v, BN[v]["parents"]) for v in VARS]  # true structure, indep values
    return FactoredMarket.from_nodes(nodes, liquidity, max_width=6)


# --- scoring ---------------------------------------------------------------

def market_marginal(m: FactoredMarket, var: str, ctx: dict | None = None) -> float:
    return m.marginal(var, ctx or {})[YES]


def flat_joint_prob(m: FactoredMarket, bits: tuple[int, ...]) -> float:
    p = 1.0
    for i, var in enumerate(VARS):
        py = market_marginal(m, var)
        p *= py if bits[i] == 1 else (1.0 - py)
    return p


def comb_joint_prob(m: FactoredMarket, bits: tuple[int, ...]) -> float:
    assign = dict(zip(VARS, bits))
    p = 1.0
    for var in TOPO:
        ctx = {par: (YES if assign[par] == 1 else NO) for par in BN[var]["parents"]}
        py = market_marginal(m, var, ctx)
        p *= py if assign[var] == 1 else (1.0 - py)
    return p


def kl_true_vs(prob_fn) -> float:
    """KL(true || market) in nats — how far the market's joint is from truth."""
    total = 0.0
    for bits, pt in TRUE.items():
        if pt <= 0:
            continue
        pm = max(prob_fn(bits), 1e-12)
        total += pt * math.log(pt / pm)
    return total


def mean_conditional_error(m: FactoredMarket, comb: bool) -> float:
    """Mean |market P(child|parent) - true| across every true edge — the
    relational accuracy a flat market structurally cannot achieve."""
    errs = []
    for child, spec in BN.items():
        for parent in spec["parents"]:
            for pv in (0, 1):
                t = true_conditional(child, parent, pv)
                if comb:
                    got = market_marginal(m, child, {parent: (YES if pv else NO)})
                else:
                    got = market_marginal(m, child)   # flat: P(child|parent)=P(child)
                errs.append(abs(got - t))
    return sum(errs) / len(errs)


# --- the aggregation process (scripted bots) -------------------------------

def clip(x: float, lo: float = 0.02, hi: float = 0.98) -> float:
    return max(lo, min(hi, x))


def run(p_cond: float, iters: int = 4000, alpha: float = 0.15,
        noise: float = 0.10, liquidity: float = 100.0, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    flat = build_flat(liquidity)
    comb = build_combinatorial(liquidity)

    marg_signals = [("marg", v) for v in VARS]
    cond_signals = [("cond", c, p) for c, s in BN.items() for p in s["parents"]]

    for _ in range(iters):
        if cond_signals and rng.random() < p_cond:
            # relational signal — only the combinatorial market can use it
            _, child, parent = rng.choice(cond_signals)
            pv = rng.randint(0, 1)
            obs = clip(true_conditional(child, parent, pv) + rng.gauss(0, noise))
            cur = market_marginal(comb, child, {parent: (YES if pv else NO)})
            target = clip(cur + alpha * (obs - cur))
            comb.trade_to_probability(child, YES, target,
                                      context={parent: (YES if pv else NO)})
        else:
            # marginal signal — both markets receive it (shared, fair info)
            _, var = rng.choice(marg_signals)
            obs = clip(true_marginal(var) + rng.gauss(0, noise))
            for m in (flat, comb):
                cur = market_marginal(m, var)
                target = clip(cur + alpha * (obs - cur))
                m.trade_to_probability(var, YES, target)

    return {
        "p_cond": p_cond,
        "kl_flat": kl_true_vs(lambda b: flat_joint_prob(flat, b)),
        "kl_comb": kl_true_vs(lambda b: comb_joint_prob(comb, b)),
        "conderr_flat": mean_conditional_error(flat, comb=False),
        "conderr_comb": mean_conditional_error(comb, comb=True),
    }


def main() -> None:
    print(f"Synthetic BN: {len(VARS)} binary vars, "
          f"{sum(len(s['parents']) for s in BN.values())} true edges")
    print(f"True marginals: " + ", ".join(f"{v}={true_marginal(v):.2f}" for v in VARS))
    print()
    print(f"{'p_cond':>7} {'KL(flat)':>10} {'KL(comb)':>10} {'KL gain':>9} "
          f"{'condErr flat':>13} {'condErr comb':>13}")
    for p_cond in (0.0, 0.25, 0.5, 0.75):
        r = run(p_cond)
        gain = r["kl_flat"] - r["kl_comb"]
        print(f"{p_cond:>7.2f} {r['kl_flat']:>10.4f} {r['kl_comb']:>10.4f} "
              f"{gain:>+9.4f} {r['conderr_flat']:>13.3f} {r['conderr_comb']:>13.3f}")

    print()
    base = run(0.0)
    tie = abs(base["kl_flat"] - base["kl_comb"])
    print(f"SANITY (p_cond=0, marginal-only): KL(flat)={base['kl_flat']:.4f} "
          f"KL(comb)={base['kl_comb']:.4f}  |gap|={tie:.4f}")
    print("  expect |gap|~0 (tie) and condErr(comb)~condErr(flat) "
          "(comb does NOT hallucinate dependence with no relational signal)")


if __name__ == "__main__":
    main()
