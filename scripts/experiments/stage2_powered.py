#!/usr/bin/env python3
"""Stage 2: is the combinatorial advantage robust across many random worlds,
and how does it depend on relational-information density and agent pollution?

Stage 1b showed, on one hand-built BN with 10 live LLM agents, that the
combinatorial market's aggregate forecast beats flat by ~5-11x on KL — and it
surfaced a failure mode (marginal-info agents asserting false independence
via conditional trades). Stage 2 asks whether that result is real or an
artifact of one lucky structure, with statistical power.

Design note (honest): running live LLM agents across hundreds of cells is
infeasible. Stages 1/1b established empirically WHAT agents do — faithfully
express their signal as the right trade type, with a false-independence
over-application failure mode. Stage 2 encodes that observed behavior as a
calibrated stochastic bot model and runs it at scale over RANDOM BNs and
seeds. This is the standard move: small expensive LLM runs calibrate the
behavior; the cheap model delivers the power. A live-LLM-at-scale run remains
a further (costly) confirmation.

We sweep:
  - relational density R (relational agents per edge): R=0 is the sanity case
    (no relational info → both markets should tie).
  - false-independence pollution rate f (fraction of marginal-info agents that
    also assert independence via conditional trades — comb-only harm).

Metric: KL(true joint || market joint), flat vs comb, reported as mean and
95% CI of the advantage (flat - comb) across BN x seed runs.

    PYTHONPATH=. python3 scripts/experiments/stage2_powered.py
"""

from __future__ import annotations

import itertools
import math
import random

from backend.inference.factored_market import FactoredMarket

YES, NO = "yes", "no"
OUTCOMES = (YES, NO)


# --- random Bayesian network (binary vars, bounded in-degree) ---------------

def random_bn(rng: random.Random, n: int = 6, max_indeg: int = 2) -> dict:
    """A random DAG over v0..v{n-1} with random, genuinely-dependent CPTs."""
    vars_ = [f"v{i}" for i in range(n)]
    bn: dict = {}
    for i, v in enumerate(vars_):
        earlier = vars_[:i]
        k = 0 if not earlier else rng.randint(0, min(max_indeg, len(earlier)))
        parents = tuple(sorted(rng.sample(earlier, k)))
        base = rng.gauss(0, 0.6)
        effects = [rng.gauss(0, 1.3) for _ in parents]  # strong parent effects
        cpt = {}
        for combo in itertools.product((0, 1), repeat=len(parents)):
            logit = base + sum(e * c for e, c in zip(effects, combo))
            p = 1 / (1 + math.exp(-logit))
            cpt[combo] = min(0.97, max(0.03, p))
        bn[v] = {"parents": parents, "cpt": cpt}
    return bn


def topo(bn: dict) -> list[str]:
    return list(bn)  # v0..v{n-1} is already topological


def enumerate_joint(bn: dict) -> dict:
    vars_ = topo(bn)
    joint = {}
    for bits in itertools.product((0, 1), repeat=len(vars_)):
        a = dict(zip(vars_, bits))
        p = 1.0
        for v in vars_:
            py = bn[v]["cpt"][tuple(a[par] for par in bn[v]["parents"])]
            p *= py if a[v] == 1 else (1 - py)
        joint[bits] = p
    return joint


def true_marginal(bn, joint, var):
    i = topo(bn).index(var)
    return sum(p for b, p in joint.items() if b[i] == 1)


def true_conditional(bn, joint, child, parent, pv):
    vs = topo(bn)
    ci, pi = vs.index(child), vs.index(parent)
    num = sum(p for b, p in joint.items() if b[pi] == pv and b[ci] == 1)
    den = sum(p for b, p in joint.items() if b[pi] == pv)
    return num / den if den else 0.5


# --- markets ---------------------------------------------------------------

def _node(var, parents):
    if not parents:
        return {"variable_id": var, "outcomes": OUTCOMES, "parents": (),
                "rows": {frozenset(): {YES: 0.5, NO: 0.5}}}
    rows = {frozenset(zip(parents, combo)): {YES: 0.5, NO: 0.5}
            for combo in itertools.product(OUTCOMES, repeat=len(parents))}
    return {"variable_id": var, "outcomes": OUTCOMES,
            "parents": tuple(sorted(parents)), "rows": rows}


def build(bn, combinatorial, liquidity=100.0, max_width=8):
    nodes = [_node(v, bn[v]["parents"] if combinatorial else ()) for v in bn]
    return FactoredMarket.from_nodes(nodes, liquidity, max_width)


def _clip(x, lo=0.02, hi=0.98):
    return max(lo, min(hi, x))


# --- calibrated behavior model ---------------------------------------------

def population(bn, joint, rng, rel_per_edge, false_indep_rate, noise=0.06,
               marg_per_var=2):
    """Agent decisions. Each is a list of actions. Flat drops conditionals."""
    vs = topo(bn)
    decisions = []
    # marginal-info agents (both markets): faithful marginal, plus pollution
    for v in vs:
        tm = true_marginal(bn, joint, v)
        for _ in range(marg_per_var):
            obs = _clip(tm + rng.gauss(0, noise))
            acts = [{"a": "m", "q": v, "p": obs}]
            if bn[v]["parents"] and rng.random() < false_indep_rate:
                # false independence: assert v ⟂ its true parents at its marginal
                for par in bn[v]["parents"]:
                    for o in OUTCOMES:
                        acts.append({"a": "c", "q": v, "gq": par, "go": o, "p": obs})
            decisions.append(acts)
    # relational-info agents (comb only): faithful conditional on true edges
    for child in vs:
        for parent in bn[child]["parents"]:
            for _ in range(rel_per_edge):
                oy = _clip(true_conditional(bn, joint, child, parent, 1) + rng.gauss(0, noise))
                on = _clip(true_conditional(bn, joint, child, parent, 0) + rng.gauss(0, noise))
                decisions.append([
                    {"a": "c", "q": child, "gq": parent, "go": YES, "p": oy},
                    {"a": "c", "q": child, "gq": parent, "go": NO, "p": on},
                ])
    return decisions


def apply_damped(market, acts, combinatorial, alpha):
    for act in acts:
        q = act["q"]
        if act["a"] == "m":
            cur = market.marginal(q, {})[YES]
            market.trade_to_probability(q, YES, _clip(cur + alpha * (act["p"] - cur)))
        elif act["a"] == "c" and combinatorial:
            cur = market.marginal(q, {act["gq"]: act["go"]})[YES]
            market.trade_to_probability(q, YES, _clip(cur + alpha * (act["p"] - cur)),
                                        context={act["gq"]: act["go"]})


def run_market(bn, decisions, combinatorial, rng, rounds=40, alpha=0.2):
    m = build(bn, combinatorial)
    order = list(range(len(decisions)))
    for _ in range(rounds):
        rng.shuffle(order)
        for i in order:
            try:
                apply_damped(m, decisions[i], combinatorial, alpha)
            except Exception:
                pass  # a conditional needing an over-budget re-triangulation is skipped
    return m


def kl(bn, joint, market):
    vs = topo(bn)
    total = 0.0
    for bits, pt in joint.items():
        if pt <= 0:
            continue
        a = dict(zip(vs, bits))
        pm = 1.0
        for v in vs:
            ctx = {par: (YES if a[par] == 1 else NO) for par in bn[v]["parents"]}
            py = market.marginal(v, ctx)[YES]
            pm *= py if a[v] == 1 else (1 - py)
        total += pt * math.log(pt / max(pm, 1e-12))
    return total


# --- powered runs ----------------------------------------------------------

def one_run(bn_seed, sig_seed, rel_per_edge, false_indep_rate, n_vars):
    bn = random_bn(random.Random(bn_seed), n=n_vars)
    joint = enumerate_joint(bn)
    dec = population(bn, joint, random.Random(sig_seed), rel_per_edge, false_indep_rate)
    flat = run_market(bn, dec, False, random.Random(sig_seed + 1))
    comb = run_market(bn, dec, True, random.Random(sig_seed + 1))
    return kl(bn, joint, flat), kl(bn, joint, comb)


def summarize(advs):
    n = len(advs)
    mean = sum(advs) / n
    var = sum((a - mean) ** 2 for a in advs) / (n - 1) if n > 1 else 0.0
    ci = 1.96 * math.sqrt(var / n)
    wins = sum(1 for a in advs if a > 0)
    return mean, ci, wins, n


def cell(n_bns, n_seeds, rel_per_edge, false_indep_rate, n_vars=6):
    advs, klf, klc = [], [], []
    for b in range(n_bns):
        for s in range(n_seeds):
            f, c = one_run(1000 + b, 7000 + b * 13 + s, rel_per_edge,
                           false_indep_rate, n_vars)
            advs.append(f - c)
            klf.append(f)
            klc.append(c)
    mean, ci, wins, n = summarize(advs)
    return {"rel": rel_per_edge, "f": false_indep_rate,
            "kl_flat": sum(klf) / len(klf), "kl_comb": sum(klc) / len(klc),
            "adv_mean": mean, "adv_ci": ci, "win_rate": wins / n, "n": n}


def main():
    N_BNS, N_SEEDS = 20, 5
    print(f"Random BNs: {N_BNS} structures x {N_SEEDS} signal seeds "
          f"= {N_BNS*N_SEEDS} runs per cell (6 binary vars, in-degree <=2)\n")

    print("A) SANITY + relational-density sweep (pollution f=0):")
    print(f"{'rel/edge':>9} {'KL flat':>9} {'KL comb':>9} "
          f"{'advantage (flat-comb) 95% CI':>32} {'comb wins':>10}")
    for rel in (0, 1, 2, 3):
        r = cell(N_BNS, N_SEEDS, rel, 0.0)
        print(f"{rel:>9} {r['kl_flat']:>9.4f} {r['kl_comb']:>9.4f} "
              f"{r['adv_mean']:>18.4f} +/- {r['adv_ci']:.4f}   {r['win_rate']*100:>7.0f}%")

    print("\nB) POLLUTION sweep (false-independence rate f, at rel/edge=2):")
    print(f"{'f':>9} {'KL flat':>9} {'KL comb':>9} "
          f"{'advantage (flat-comb) 95% CI':>32} {'comb wins':>10}")
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        r = cell(N_BNS, N_SEEDS, 2, f)
        print(f"{f:>9.2f} {r['kl_flat']:>9.4f} {r['kl_comb']:>9.4f} "
              f"{r['adv_mean']:>18.4f} +/- {r['adv_ci']:.4f}   {r['win_rate']*100:>7.0f}%")


if __name__ == "__main__":
    main()
