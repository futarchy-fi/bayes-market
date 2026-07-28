#!/usr/bin/env python3
"""Stage-3, experiment 1: when does imposing graphical structure help *finite-
sample* joint forecasting? A pure estimation study -- NO market, NO trading.

Motivation (from adversarial review of the market-based design): comparing a
combinatorial market to a flat one conflates five things -- representable family,
structural assumptions, parameter count, expressible information, and market
aggregation dynamics. Before touching markets we isolate the one question that
underlies all of them:

    Given a finite training sample, does restricting the joint to a graphical
    family reduce estimation variance more than it adds approximation bias?

Design (paired, hierarchical):
  * Draw a ground-truth Bayes net over k binary vars from a chosen topology.
  * Draw ONE finite training sample of size N; every estimator sees the SAME sample.
  * Fit each estimator family by smoothed MLE (identical Dirichlet(alpha) prior):
        independence  : empty graph      (flat)
        correct       : the true DAG
        under-dense   : true DAG minus one real edge  (imposes a FALSE
                        conditional independence -- the only misspecification
                        that binds for a BN family; a spurious edge is mere
                        over-parameterisation, the family still contains the
                        truth. NB: edge *reversal* is family-preserving only for
                        covered reversals / 2-var cases, so no reversal is used.)
        over-dense    : true DAG plus a spurious edge (over-parameterised)
        saturated     : full DAG          (the 2^k table; no bias, max variance)
  * Score by EXPECTED held-out log-loss, computed exactly as the cross-entropy
    H(truth, fitted) -- the large-test-sample limit, without test-set noise.

Regret decomposition, per estimator family G:
    test_loss(G,N)         = H(truth, fitted_G)                 [what you pay]
    oracle_loss(G)         = H(truth, Q*_G)                     [best-in-family]
    approx_error(G)        = oracle_loss(G) - H(truth) = KL(truth || Q*_G)
                              -- irreducible representational bias of family G
    estimation_regret(G,N) = test_loss(G,N) - oracle_loss(G)
                              -- finite-sample cost, -> 0 as N -> inf
    excess(G,N)            = test_loss(G,N) - H(truth)
                              = approx_error(G) + estimation_regret(G,N)
Q*_G is the KL-projection of the truth onto family G: for a BN it is exactly the
true conditionals P(Xi | parents_G(Xi)), a standard result.

Everything is exact given the truth joint (2^k table) -- the only randomness is
the truth draw and the finite training sample, so the reported spread is honest
Monte Carlo over worlds. Deterministic given --seed. Offline, stdlib only.
"""

from __future__ import annotations

import argparse
import itertools
import math
import random
import statistics
from dataclasses import dataclass

# ---- distributions over k binary variables --------------------------------
# A joint is a dict: state (tuple of 0/1, length k) -> probability.

# Only guards float underflow in log() -- NOT a probability floor. The truth and
# every fitted/oracle joint are strictly positive here (smoothed conditionals),
# so a real 1e-6 floor would spuriously inflate tiny truth cells (down to ~1e-24
# at k=4) and make approx_error negative for truth-containing families instead of
# exactly zero. Set far below any real state probability.
CLIP = 1e-300


def _states(k: int) -> list[tuple[int, ...]]:
    return list(itertools.product((0, 1), repeat=k))


def conditionals_from_dist(parents: dict[int, list[int]],
                           dist: dict[tuple[int, ...], float],
                           k: int) -> dict[tuple[int, ...], float]:
    """KL-project `dist` onto the BN family defined by `parents`: build the joint
    whose every factor is the conditional of `dist` given that node's parents.
    With `dist` = truth this is the family oracle Q*_G; with `dist` = the
    (smoothed) empirical distribution it is the fitted MLE."""
    # Precompute, per node, P(Xi=1 | parent-config) under dist.
    cond1: dict[int, dict[tuple[int, ...], float]] = {}
    for i in range(k):
        pa = parents[i]
        num: dict[tuple[int, ...], float] = {}
        den: dict[tuple[int, ...], float] = {}
        for state, p in dist.items():
            key = tuple(state[j] for j in pa)
            den[key] = den.get(key, 0.0) + p
            if state[i] == 1:
                num[key] = num.get(key, 0.0) + p
        table: dict[tuple[int, ...], float] = {}
        for key, d in den.items():
            table[key] = (num.get(key, 0.0) / d) if d > 0 else 0.5
        cond1[i] = table

    out: dict[tuple[int, ...], float] = {}
    for state in _states(k):
        p = 1.0
        for i in range(k):
            key = tuple(state[j] for j in parents[i])
            p1 = cond1[i].get(key, 0.5)
            p *= p1 if state[i] == 1 else (1.0 - p1)
        out[state] = p
    return out


def fit_family(parents: dict[int, list[int]],
               counts: dict[tuple[int, ...], int],
               n: int, alpha: float, k: int) -> dict[tuple[int, ...], float]:
    """Smoothed-MLE fit of a BN family from training counts, using a BDeu-style
    prior: each node carries a FIXED equivalent sample size (2*alpha) that is
    SPLIT across its parent-configs (alpha_eff = alpha / 2**|parents|). This keeps
    the total prior shrinkage per node identical across families. The earlier
    constant-per-config prior handed a saturated node 2**|pa| times the total
    pseudocounts of a root, so richer families were over-regularised -- the
    'variance' gap then mixed in a prior-induced bias. With constant per-node ESS
    the family comparison is on estimation error, not on differing priors."""
    cond1: dict[int, dict[tuple[int, ...], float]] = {}
    for i in range(k):
        pa = parents[i]
        a = alpha / (2 ** len(pa))   # BDeu: constant ESS = 2*alpha per node
        num: dict[tuple[int, ...], float] = {}
        den: dict[tuple[int, ...], float] = {}
        for state, c in counts.items():
            key = tuple(state[j] for j in pa)
            den[key] = den.get(key, 0.0) + c
            if state[i] == 1:
                num[key] = num.get(key, 0.0) + c
        # Every parent-config that can occur, smoothed.
        table: dict[tuple[int, ...], float] = {}
        for key in itertools.product((0, 1), repeat=len(pa)):
            table[key] = (num.get(key, 0.0) + a) / (den.get(key, 0.0) + 2 * a)
        cond1[i] = table

    out: dict[tuple[int, ...], float] = {}
    for state in _states(k):
        p = 1.0
        for i in range(k):
            key = tuple(state[j] for j in parents[i])
            p1 = cond1[i][key]
            p *= p1 if state[i] == 1 else (1.0 - p1)
        out[state] = p
    return out


def cross_entropy(truth: dict, model: dict) -> float:
    return -sum(pt * math.log(max(model[s], CLIP))
               for s, pt in truth.items() if pt > 0.0)


def entropy(truth: dict) -> float:
    return -sum(pt * math.log(pt) for pt in truth.values() if pt > 0.0)


# ---- topologies and truth sampling ----------------------------------------


@dataclass
class Topology:
    name: str
    k: int
    true_parents: dict[int, list[int]]
    families: dict[str, dict[int, list[int]]]


def _saturated(k: int) -> dict[int, list[int]]:
    return {i: list(range(i)) for i in range(k)}


def _empty(k: int) -> dict[int, list[int]]:
    return {i: [] for i in range(k)}


def topologies() -> dict[str, Topology]:
    # Nodes are given in a valid topological order 0..k-1.
    chain = {0: [], 1: [0], 2: [1]}            # 0 -> 1 -> 2  (X0 _|_ X2 | X1)
    collider = {0: [], 1: [], 2: [0, 1]}       # 0 -> 2 <- 1  (X0 _|_ X1)
    fork = {0: [], 1: [0], 2: [0]}             # 1 <- 0 -> 2  (X1 _|_ X2 | X0)
    return {
        "chain": Topology("chain", 3, chain, {
            "independence": _empty(3),
            "under-dense": {0: [], 1: [0], 2: []},        # drops 1->2 (false indep)
            "correct": chain,
            "over-dense": {0: [], 1: [0], 2: [0, 1]},     # spurious 0->2 (==saturated here)
            "saturated": _saturated(3),
        }),
        "collider": Topology("collider", 3, collider, {
            "independence": _empty(3),
            "under-dense": {0: [], 1: [], 2: [0]},        # drops 1->2 (false indep)
            "correct": collider,
            "over-dense": {0: [], 1: [0], 2: [0, 1]},     # spurious 0->1
            "saturated": _saturated(3),
        }),
        "fork": Topology("fork", 3, fork, {
            "independence": _empty(3),
            "under-dense": {0: [], 1: [0], 2: []},        # drops 0->2 (false indep)
            "correct": fork,
            "over-dense": {0: [], 1: [0], 2: [0, 1]},     # spurious 1->2
            "saturated": _saturated(3),
        }),
        # k=4 chain: over-dense is now STRICTLY between correct and saturated,
        # exposing the variance ladder correct < over-dense < saturated.
        "chain4": Topology("chain4", 4, {0: [], 1: [0], 2: [1], 3: [2]}, {
            "independence": _empty(4),
            "under-dense": {0: [], 1: [0], 2: [1], 3: []},       # drops 2->3
            "correct": {0: [], 1: [0], 2: [1], 3: [2]},
            "over-dense": {0: [], 1: [0], 2: [1], 3: [2, 0]},    # spurious 0->3
            "saturated": _saturated(4),
        }),
    }


def sample_truth(rng: random.Random, topo: Topology, strength: float) -> dict:
    """Random CPTs on the true DAG. `strength` scales how far each parent-config
    pulls P(Xi=1) from a shared base -> tunable dependence. strength=0 => the
    node ignores its parents (no dependence, a within-topology control)."""
    cond1: dict[int, dict[tuple[int, ...], float]] = {}
    for i in range(topo.k):
        pa = topo.true_parents[i]
        base = rng.uniform(0.3, 0.7)
        table: dict[tuple[int, ...], float] = {}
        for key in itertools.product((0, 1), repeat=len(pa)):
            shift = rng.gauss(0.0, strength) if pa else 0.0
            table[key] = min(1 - CLIP, max(CLIP, base + shift))
        cond1[i] = table
    out: dict[tuple[int, ...], float] = {}
    for state in _states(topo.k):
        p = 1.0
        for i in range(topo.k):
            key = tuple(state[j] for j in topo.true_parents[i])
            p1 = cond1[i][key]
            p *= p1 if state[i] == 1 else (1.0 - p1)
        out[state] = p
    return out


def draw_sample(rng: random.Random, truth: dict, n: int) -> dict:
    states = list(truth.keys())
    weights = list(truth.values())
    counts: dict[tuple[int, ...], int] = {}
    for s in rng.choices(states, weights=weights, k=n):
        counts[s] = counts.get(s, 0) + 1
    return counts


# ---- experiment ------------------------------------------------------------

FAMILY_ORDER = ["independence", "under-dense", "correct", "over-dense", "saturated"]


@dataclass
class Cell:
    topology: str
    n: int
    strength: float
    family: str
    approx_error: float          # irreducible bias (mean over worlds; ~constant)
    est_regret: float            # finite-sample cost (mean over worlds)
    excess: float                # total nats above truth entropy
    excess_ci: tuple[float, float]
    win_vs_correct: float        # fraction of worlds this family beats 'correct'
    diff_mean: float             # mean PAIRED gap excess[f] - excess[correct]
    diff_ci: tuple[float, float]  # paired 95% CI on that gap (the honest test)
    win_ci: tuple[float, float]  # Wilson 95% CI on the win fraction


def _ci95(xs: list[float]) -> tuple[float, float]:
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    m = statistics.mean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    return (m - 1.96 * se, m + 1.96 * se)


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion -- honest for win rates
    near 0/1 where a normal approximation would spill outside [0,1]."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - half) / denom, (centre + half) / denom)


def run_cell(topo: Topology, n: int, strength: float, worlds: int,
             alpha: float, seed: int) -> dict[str, Cell]:
    rng = random.Random(seed)
    approx = {f: [] for f in FAMILY_ORDER}
    regret = {f: [] for f in FAMILY_ORDER}
    excess = {f: [] for f in FAMILY_ORDER}
    correct_excess: list[float] = []
    per_world_excess: list[dict[str, float]] = []
    for _ in range(worlds):
        truth = sample_truth(rng, topo, strength)
        h = entropy(truth)
        counts = draw_sample(rng, truth, n)
        world: dict[str, float] = {}
        for f in FAMILY_ORDER:
            parents = topo.families[f]
            oracle = conditionals_from_dist(parents, truth, topo.k)
            fitted = fit_family(parents, counts, n, alpha, topo.k)
            oracle_loss = cross_entropy(truth, oracle)
            test_loss = cross_entropy(truth, fitted)
            approx[f].append(oracle_loss - h)
            regret[f].append(test_loss - oracle_loss)
            ex = test_loss - h
            excess[f].append(ex)
            world[f] = ex
        correct_excess.append(world["correct"])
        per_world_excess.append(world)
    out: dict[str, Cell] = {}
    for f in FAMILY_ORDER:
        # Paired: gap to 'correct' in the SAME world -> paired CI, not marginal.
        diffs = [w[f] - w["correct"] for w in per_world_excess]
        nwin = sum(1 for d in diffs if d < 0.0)
        out[f] = Cell(
            topology=topo.name, n=n, strength=strength, family=f,
            approx_error=statistics.mean(approx[f]),
            est_regret=statistics.mean(regret[f]),
            excess=statistics.mean(excess[f]),
            excess_ci=_ci95(excess[f]),
            win_vs_correct=nwin / worlds,
            diff_mean=statistics.mean(diffs),
            diff_ci=_ci95(diffs),
            win_ci=_wilson(nwin, worlds),
        )
    return out


def _print_cell(topo: str, n: int, strength: float,
                cells: dict[str, Cell]) -> None:
    print(f"\n[{topo}]  N={n}  dependence-strength={strength}")
    print(f"  {'family':<14}{'excess':>8}{'approx':>8}{'estim':>8}"
          f"{'Δ vs correct [95% CI]':>27}{'win% [95% CI]':>18}")
    for f in FAMILY_ORDER:
        c = cells[f]
        if f == "correct":
            dcol, wcol = f"{'(reference)':>27}", f"{'—':>18}"
        else:
            d = f"{c.diff_mean:+.4f} [{c.diff_ci[0]:+.4f},{c.diff_ci[1]:+.4f}]"
            w = (f"{c.win_vs_correct*100:.0f}% "
                 f"[{c.win_ci[0]*100:.0f},{c.win_ci[1]*100:.0f}]")
            dcol, wcol = f"{d:>27}", f"{w:>18}"
        print(f"  {f:<14}{c.excess:>8.4f}{c.approx_error:>8.4f}"
              f"{c.est_regret:>8.4f}{dcol}{wcol}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=2000,
                    help="independently drawn ground-truth nets per cell")
    ap.add_argument("--alpha", type=float, default=1.0,
                    help="Dirichlet smoothing (identical across families)")
    ap.add_argument("--strength", type=float, default=0.25,
                    help="dependence strength of the truth CPTs")
    ap.add_argument("--ns", type=int, nargs="+",
                    default=[20, 50, 100, 200, 500, 2000])
    ap.add_argument("--topologies", nargs="+",
                    default=["chain", "collider", "fork", "chain4"])
    ap.add_argument("--seed", type=int, default=20260728)
    args = ap.parse_args()

    topos = topologies()
    print("Stage-3 experiment 1: graphical structure vs finite-sample forecasting")
    print(f"worlds/cell={args.worlds}  alpha={args.alpha}  "
          f"strength={args.strength}  (all quantities in nats above truth entropy)")
    print("excess = approx_error (irreducible family bias) + est_regret "
          "(finite-sample cost)")

    seed = args.seed
    for tname in args.topologies:
        topo = topos[tname]
        for n in args.ns:
            cells = run_cell(topo, n, args.strength, args.worlds, args.alpha, seed)
            _print_cell(tname, n, args.strength, cells)
            seed += 1

    # Strength=0 control: no dependence -> structure must not help.
    print("\n--- CONTROL: strength=0 (no dependence) ---")
    for tname in args.topologies:
        topo = topos[tname]
        cells = run_cell(topo, 100, 0.0, args.worlds, args.alpha, seed)
        _print_cell(tname, 100, 0.0, cells)
        seed += 1


if __name__ == "__main__":
    main()
