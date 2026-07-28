"""Stage-3 Q3: does the MARKET MECHANISM earn its keep once trading is
strategic?

Q2 (montecarlo.py baselines) showed that under stylized nudge aggregation the
LMSR market is NOT the active ingredient: a per-parameter opinion pool fed the
identical reports beats it everywhere. This experiment gives the market what
the pool cannot use -- incentives, budgets, private information, and (Q3b)
wealth carried across worlds -- with the contract space as the ONLY difference
between the comb and flat arms.

Key design points (adversarially reviewed before implementation):

  * Private information is a finite i.i.d. sample from the ground truth, not
    truth+gaussian noise: agent quality is its sample size n_i, so "informed"
    is endogenous and honestly finite-sample.
  * Traders are budget-constrained: every agent's cumulative payoff vector
    over the 16 joint states is tracked exactly from the engine's LMSR fills,
    and a trade is sized (binary search on the target) so that
    min_state(payoff) >= -wealth. Conditional trades on exclusive contexts
    (AGI=yes vs AGI=no) naturally don't add worst-case losses -- a real
    capital-efficiency property of the combinatorial book.
  * P&L is settled from the fills themselves (profit == shares*1{hit} - cost,
    which equals b*log(q_x/p_x) on the realized outcome -- verified against
    the engine to 1e-6 before this was written).
  * Non-market baselines get the same posteriors: equal-weight modular pool
    (Q2's winner) and an oracle precision-weighted pool (weights ~ n_i) as
    the honest ceiling.

Run:  PYTHONPATH=. python3 scripts/experiments/live_run/stage3_market.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import montecarlo as mc  # noqa: E402  (shared world/engine harness from Q2)

AGI, G39, G40, RND = mc.AGI, mc.G39, mc.G40, mc.RND
OUT = mc.OUT
STATES: list[tuple[str, str, str, str]] = [
    (a, g, h, r) for a in OUT for g in OUT for h in OUT for r in OUT
]
STATE_IX = {s: i for i, s in enumerate(STATES)}


# ---- private information and posteriors ------------------------------------


ARMS = ("comb", "flat")


@dataclass
class Trader:
    """Budget accounting is PER ARM: the comb and flat markets are parallel
    economies over the same world -- same posterior, same initial wealth --
    and a trade in one must never consume budget in the other (that would
    couple the arms and confound the comparison)."""
    relational: bool
    n_obs: int                  # private sample size == information quality
    wealth: dict[str, float]    # per arm
    # Posterior means (Beta(1,1)-smoothed from the private sample):
    b_agi: float = 0.5
    b_g39_y: float = 0.5
    b_g39_n: float = 0.5
    b_g39_marg: float = 0.5
    b_g40: float = 0.5
    b_rnd: float = 0.5
    # Cumulative payoff per joint state for the CURRENT world, per arm.
    payoff: dict[str, list[float]] = field(
        default_factory=lambda: {a: [0.0] * 16 for a in ARMS})
    pnl_total: dict[str, float] = field(
        default_factory=lambda: {a: 0.0 for a in ARMS})

    def reset_world(self) -> None:
        self.payoff = {a: [0.0] * 16 for a in ARMS}


def _beta_mean(k: float, n: float) -> float:
    return (k + 1.0) / (n + 2.0)


def observe(rng: random.Random, tr: Trader, truth: mc.Truth) -> None:
    """Draw the trader's private sample and form smoothed posterior means for
    every parameter its type can express. A marginal trader tabulates G39
    without reference to AGI (it never perceives the split)."""
    n = tr.n_obs
    joint = truth.joint()
    states, probs = zip(*joint.items())
    draws = rng.choices(states, weights=probs, k=n)
    n_agi = sum(1 for s in draws if s[0] == "yes")
    n_g40 = sum(1 for s in draws if s[2] == "yes")
    n_rnd = sum(1 for s in draws if s[3] == "yes")
    tr.b_agi = _beta_mean(n_agi, n)
    tr.b_g40 = _beta_mean(n_g40, n)
    tr.b_rnd = _beta_mean(n_rnd, n)
    n_g39 = sum(1 for s in draws if s[1] == "yes")
    tr.b_g39_marg = _beta_mean(n_g39, n)
    if tr.relational:
        n_y = sum(1 for s in draws if s[0] == "yes")
        k_y = sum(1 for s in draws if s[0] == "yes" and s[1] == "yes")
        n_n = n - n_y
        k_n = n_g39 - k_y
        tr.b_g39_y = _beta_mean(k_y, n_y)
        tr.b_g39_n = _beta_mean(k_n, n_n)


# ---- budget-constrained trading --------------------------------------------


def _fill_payoff(state: tuple[str, str, str, str], var: str, outcome: str,
                 context: dict[str, str], shares: float, cost: float) -> float:
    """This trade's payoff if `state` realizes: called off (0) when the
    context does not realize, else shares*1{var hits} - cost."""
    var_ix = {AGI: 0, G39: 1, G40: 2, RND: 3}
    for cv, co in context.items():
        if state[var_ix[cv]] != co:
            return 0.0
    hit = state[var_ix[var]] == outcome
    return (shares if hit else 0.0) - cost


def _worst_case_after(tr: Trader, arm: str, var: str, outcome: str,
                      context: dict[str, str], shares: float,
                      cost: float) -> float:
    pv = tr.payoff[arm]
    return min(
        pv[i] + _fill_payoff(s, var, outcome, context, shares, cost)
        for i, s in enumerate(STATES)
    )


def _quote(market: mc.FactoredMarket, var: str,
           context: dict[str, str]) -> float:
    return market.marginal(var, context or None)["yes"]


def _fill_terms(b: float, p: float, q: float) -> tuple[float, float]:
    """LMSR shares and cost for moving the (conditional) yes-price p -> q,
    identical algebra to the engine (verified)."""
    shares = b * math.log(q * (1 - p) / (p * (1 - q)))
    cost = b * math.log((1 - p) / (1 - q))
    return shares, cost


def budget_target(tr: Trader, arm: str, market: mc.FactoredMarket, var: str,
                  belief: float, context: dict[str, str],
                  tol: float = 1e-4) -> float | None:
    """Largest move from the current price toward `belief` whose worst-case
    cumulative payoff stays >= -wealth. Returns None for a negligible move.

    Binary search on the target; exact payoff-vector accounting, so exclusive
    contexts and offsetting positions are handled with no approximation."""
    p = _quote(market, var, context)
    belief = min(max(belief, mc.CLIP), 1.0 - mc.CLIP)
    if abs(belief - p) < tol:
        return None
    b = market.liquidity

    def ok(q: float) -> bool:
        sh, c = _fill_terms(b, p, q)
        return (_worst_case_after(tr, arm, var, "yes", context, sh, c)
                >= -tr.wealth[arm])

    if ok(belief):
        return belief
    lo, hi = p, belief          # lo is always feasible (null trade)
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if ok(mid):
            lo = mid
        else:
            hi = mid
    if abs(lo - p) < tol:
        return None
    return lo


def apply_trade(tr: Trader, arm: str, market: mc.FactoredMarket, var: str,
                target: float, context: dict[str, str]) -> None:
    fill = market.trade_to_probability(var, "yes", target,
                                       context=context or None)
    sh, c = fill["shares"], fill["cost"]
    pv = tr.payoff[arm]
    for i, s in enumerate(STATES):
        pv[i] += _fill_payoff(s, var, "yes", context, sh, c)


def trade_round(traders: list[Trader], comb: mc.FactoredMarket,
                flat: mc.FactoredMarket, rng: random.Random) -> int:
    """One arrival round: each trader (random order) moves every price it has
    an opinion on toward its posterior, as far as its budget allows, in BOTH
    arms. Returns the number of executed trades (0 => converged)."""
    order = list(range(len(traders)))
    rng.shuffle(order)
    n_trades = 0
    for ix in order:
        tr = traders[ix]
        markets = {"comb": comb, "flat": flat}
        views: list[tuple[str, str, float, dict[str, str]]] = []
        for arm in ARMS:
            views.append((arm, AGI, tr.b_agi, {}))
            views.append((arm, G40, tr.b_g40, {}))
            views.append((arm, RND, tr.b_rnd, {}))
        if tr.relational:
            views.append(("comb", G39, tr.b_g39_y, {AGI: "yes"}))
            views.append(("comb", G39, tr.b_g39_n, {AGI: "no"}))
            implied = (tr.b_agi * tr.b_g39_y
                       + (1 - tr.b_agi) * tr.b_g39_n)
            views.append(("flat", G39, implied, {}))
        else:
            views.append(("comb", G39, tr.b_g39_marg, {}))
            views.append(("flat", G39, tr.b_g39_marg, {}))
        # Randomize the within-trader contract order: a fixed order is a
        # greedy allocation policy that systematically starves whichever
        # contract comes last of budget headroom (review finding).
        rng.shuffle(views)
        for arm, var, belief, context in views:
            market = markets[arm]
            target = budget_target(tr, arm, market, var, belief, context)
            if target is not None:
                apply_trade(tr, arm, market, var, target, context)
                n_trades += 1
    return n_trades


# ---- non-market baselines ---------------------------------------------------
#
# Equal-weight modular pool: mc.modular_pool works on Traders directly (same
# b_*/relational interface as mc.Agent). The oracle-weighted variant below is
# the honest ceiling: weights ~ private sample size n_i, information no
# mechanism could extract without observing the traders' private quality.


def _wlogit_mean(pairs: list[tuple[float, float]]) -> float:
    """Weighted mean in log-odds; pairs = (weight, probability)."""
    tot = sum(w for w, _ in pairs)
    x = sum(w * math.log(min(max(p, 1e-12), 1 - 1e-12)
                         / (1 - min(max(p, 1e-12), 1 - 1e-12)))
            for w, p in pairs) / tot
    return 1.0 / (1.0 + math.exp(-x))


def oracle_pool(traders: list[Trader], arm: str) -> dict:
    """modular_pool with precision weights w_i = n_i (oracle knowledge)."""
    pa = _wlogit_mean([(t.n_obs, t.b_agi) for t in traders])
    p40 = _wlogit_mean([(t.n_obs, t.b_g40) for t in traders])
    prnd = _wlogit_mean([(t.n_obs, t.b_rnd) for t in traders])
    marg = [(t.n_obs,
             t.b_agi * t.b_g39_y + (1 - t.b_agi) * t.b_g39_n
             if t.relational else t.b_g39_marg) for t in traders]
    if arm == "comb":
        rel = [t for t in traders if t.relational]
        if rel:
            gy = _wlogit_mean([(t.n_obs, t.b_g39_y) for t in rel])
            gn = _wlogit_mean([(t.n_obs, t.b_g39_n) for t in rel])
        else:
            gy = gn = _wlogit_mean(marg)
    else:
        gy = gn = _wlogit_mean(marg)
    return mc._factored_joint(pa, gy, gn, p40, prnd)


# ---- settlement -------------------------------------------------------------


def settle(traders: list[Trader], outcome: tuple[str, str, str, str]) -> None:
    ix = STATE_IX[outcome]
    for tr in traders:
        for arm in ARMS:
            pnl = tr.payoff[arm][ix]
            tr.pnl_total[arm] += pnl
            tr.wealth[arm] = max(0.0, tr.wealth[arm] + pnl)


# ---- experiment (Q3a: minimal decisive version, per design review) ---------
#
# Estimand (difference-in-differences, per world, paired):
#     DiD = (KL_comb_market - KL_comb_pool) - (KL_flat_market - KL_flat_pool)
# Negative DiD => the incentivized LMSR adds value over non-market pooling
# BEYOND what the richer representation already provides. Comparing comb
# market to flat market alone would re-measure representation (Q2's result).
#
# Design-review constraints honored:
#   * agent TYPE (relational/marginal) fully crossed with QUALITY (n_i);
#   * ONE randomized trading pass (no trade-to-convergence; order-sensitivity
#     is measured instead, by re-running the same world under R fresh orders);
#   * traders are plainly solvency-constrained report automatons, not
#     strategic Bayesians -- the claim tested is about incentive-compatible
#     budgeted reporting, not equilibrium behavior;
#   * the n_i-weighted pool is reported as a REFERENCE aggregator, not an
#     "oracle ceiling" (conditional precision depends on realized cell
#     counts, not n_i alone);
#   * cross-world wealth carryover (Q3b) is deliberately excluded here.


@dataclass
class Cond:
    name: str
    dependence: bool = True
    n_rel_hi: int = 5           # relational, large private sample
    n_rel_lo: int = 5           # relational, small private sample
    n_marg_hi: int = 5          # marginal, large private sample
    n_marg_lo: int = 5
    obs_hi: int = 400
    obs_lo: int = 20
    wealth0: float = 25.0
    orders: int = 2             # arrival orders per world (sensitivity)


def make_traders(cond: Cond) -> list[Trader]:
    spec = [(True, cond.obs_hi)] * cond.n_rel_hi \
         + [(True, cond.obs_lo)] * cond.n_rel_lo \
         + [(False, cond.obs_hi)] * cond.n_marg_hi \
         + [(False, cond.obs_lo)] * cond.n_marg_lo
    return [Trader(relational=r, n_obs=n,
                   wealth={a: cond.wealth0 for a in ARMS}) for r, n in spec]


@dataclass
class WorldResult:
    kl_mkt: dict[str, float]
    kl_pool: dict[str, float]
    kl_wpool: dict[str, float]
    did: float
    did_wpool: float
    order_spread: float          # max-min terminal comb KL across orders
    pnl_by_group: dict[str, float]
    order_spread_flat: float = 0.0
    maker_pnl: float = 0.0       # market maker's expected P&L (comb arm)
    gap_comb: float = 0.0        # paired per-world KLmkt - KLpool, comb
    gap_flat: float = 0.0


def run_world(cond: Cond, rng: random.Random) -> WorldResult:
    truth = mc.sample_truth(rng, cond.dependence)
    gt = truth.joint()
    base = make_traders(cond)
    for tr in base:
        observe(rng, tr, truth)

    # Pools consume the identical posteriors; no trading, no budgets.
    kl_pool = {arm: mc.kl(gt, mc.modular_pool(base, arm)) for arm in ARMS}
    kl_wpool = {arm: mc.kl(gt, oracle_pool(base, arm)) for arm in ARMS}

    # Markets: one randomized pass; repeat under fresh orders for sensitivity.
    per_order: list[dict[str, float]] = []
    keep: list[Trader] | None = None
    for _ in range(max(1, cond.orders)):
        traders = [Trader(relational=t.relational, n_obs=t.n_obs,
                          wealth={a: cond.wealth0 for a in ARMS},
                          b_agi=t.b_agi, b_g39_y=t.b_g39_y,
                          b_g39_n=t.b_g39_n, b_g39_marg=t.b_g39_marg,
                          b_g40=t.b_g40, b_rnd=t.b_rnd) for t in base]
        comb, flat = mc._build_pair()
        trade_round(traders, comb, flat, rng)
        per_order.append({"comb": mc.kl(gt, mc.market_joint(comb)),
                          "flat": mc.kl(gt, mc.market_joint(flat))})
        if keep is None:
            keep = traders

    kl_mkt = per_order[0]
    combs = [o["comb"] for o in per_order]
    flats = [o["flat"] for o in per_order]
    # True pairwise spread (max-min), reported for BOTH arms -- a comb-only
    # sensitivity number would be selective (review finding).
    spread = max(combs) - min(combs)
    spread_flat = max(flats) - min(flats)

    # EXPECTED P&L under the true joint (noiseless diagnostic; single-outcome
    # settlement noise is a Q3b concern, per design review): are informed
    # traders profitable in expectation, and at whose expense?
    pnl: dict[str, list[float]] = {}
    assert keep is not None
    total_trader_pnl = 0.0
    for tr in keep:
        key = (f"{'rel' if tr.relational else 'marg'}-"
               f"{'hi' if tr.n_obs >= cond.obs_hi else 'lo'}")
        e_pnl = sum(gt[s] * tr.payoff["comb"][i]
                    for i, s in enumerate(STATES))
        pnl.setdefault(key, []).append(e_pnl)
        total_trader_pnl += e_pnl
    did = ((kl_mkt["comb"] - kl_pool["comb"])
           - (kl_mkt["flat"] - kl_pool["flat"]))
    did_w = ((kl_mkt["comb"] - kl_wpool["comb"])
             - (kl_mkt["flat"] - kl_wpool["flat"]))
    return WorldResult(
        kl_mkt=kl_mkt, kl_pool=kl_pool, kl_wpool=kl_wpool,
        did=did, did_wpool=did_w, order_spread=spread,
        order_spread_flat=spread_flat,
        pnl_by_group={k: statistics.mean(v) for k, v in pnl.items()},
        maker_pnl=-total_trader_pnl,   # LMSR maker is the counterparty
        gap_comb=kl_mkt["comb"] - kl_pool["comb"],
        gap_flat=kl_mkt["flat"] - kl_pool["flat"],
    )


def run_condition(cond: Cond, worlds: int, seed: int) -> dict:
    rng = random.Random(seed)
    rs = [run_world(cond, rng) for _ in range(worlds)]
    def agg(xs: list[float]) -> tuple[float, tuple[float, float]]:
        return statistics.mean(xs), mc._ci95(xs)
    dids = [r.did for r in rs]
    did_m, did_ci = agg(dids)
    out = {
        "condition": cond.name,
        "worlds": worlds,
        "kl_mkt_comb": statistics.mean(r.kl_mkt["comb"] for r in rs),
        "kl_mkt_flat": statistics.mean(r.kl_mkt["flat"] for r in rs),
        "kl_pool_comb": statistics.mean(r.kl_pool["comb"] for r in rs),
        "kl_pool_flat": statistics.mean(r.kl_pool["flat"] for r in rs),
        "kl_wpool_comb": statistics.mean(r.kl_wpool["comb"] for r in rs),
        "kl_wpool_flat": statistics.mean(r.kl_wpool["flat"] for r in rs),
        "did_mean": did_m,
        "did_ci": did_ci,
        "did_win": sum(1 for d in dids if d < 0.0) / worlds,
        "did_win_ci": _wilson_ci(sum(1 for d in dids if d < 0.0), worlds),
        "did_wpool_mean": statistics.mean(r.did_wpool for r in rs),
        # Main effects with paired CIs (review ask): per-world mkt - pool gap.
        "gap_comb_mean": statistics.mean(r.gap_comb for r in rs),
        "gap_comb_ci": mc._ci95([r.gap_comb for r in rs]),
        "gap_flat_mean": statistics.mean(r.gap_flat for r in rs),
        "gap_flat_ci": mc._ci95([r.gap_flat for r in rs]),
        "maker_pnl_mean": statistics.mean(r.maker_pnl for r in rs),
        "order_spread_p90": mc._pctl([r.order_spread for r in rs], 0.90),
        "order_spread_flat_p90": mc._pctl(
            [r.order_spread_flat for r in rs], 0.90),
        "pnl": {k: (statistics.mean(vals) if (vals := [
                    r.pnl_by_group[k] for r in rs if k in r.pnl_by_group])
                    else float("nan"))
                for k in ("rel-hi", "rel-lo", "marg-hi", "marg-lo")},
    }
    return out


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (center - half, center + half)


def default_conditions() -> list[Cond]:
    return [
        Cond("balanced 5/5/5/5"),
        Cond("informed minority: 2 rel-hi vs 18 others",
             n_rel_hi=2, n_rel_lo=4, n_marg_hi=4, n_marg_lo=10),
        # 100% relational: the pool-filters-by-type asymmetry (comb pool drops
        # marginal G39 reports; comb market absorbs them) vanishes by
        # construction -- the cleanest market-vs-pool cell (review finding).
        Cond("100% relational (asymmetry-free)",
             n_rel_hi=10, n_rel_lo=10, n_marg_hi=0, n_marg_lo=0),
        Cond("poor: wealth0=5", wealth0=5.0),
        Cond("rich: wealth0=100", wealth0=100.0),
        Cond("CONTROL no-dependence", dependence=False),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", default="/tmp/stage3_market_results.json")
    args = ap.parse_args()

    print("Q3a: budgeted incentive-compatible trading vs non-market pooling "
          "(2x2, DiD)\n"
          "DiD = (KLmkt-KLpool)[comb] - (KLmkt-KLpool)[flat]; negative => "
          "the market mechanism\nadds value beyond representation. "
          "wpool = n_i-weighted reference pool (not a ceiling).\n")
    results = []
    header = (f"{'condition':<42}{'mktC':>7}{'poolC':>7}{'wplC':>7}"
              f"{'mktF':>7}{'poolF':>7}"
              f"{'DiD [95% CI]':>26}{'win%':>6}{'ordC90':>8}{'ordF90':>8}")
    print(header)
    print("-" * len(header))
    for i, cond in enumerate(default_conditions()):
        r = run_condition(cond, args.worlds, args.seed + i * 1000)
        results.append(r)
        ci = f"{r['did_mean']:+.4f} [{r['did_ci'][0]:+.4f},{r['did_ci'][1]:+.4f}]"
        print(f"{r['condition']:<42}{r['kl_mkt_comb']:>7.4f}"
              f"{r['kl_pool_comb']:>7.4f}{r['kl_wpool_comb']:>7.4f}"
              f"{r['kl_mkt_flat']:>7.4f}{r['kl_pool_flat']:>7.4f}"
              f"{ci:>26}{r['did_win']*100:>5.0f}%"
              f"{r['order_spread_p90']:>8.4f}{r['order_spread_flat_p90']:>8.4f}")
    print("\nMain effects (paired per-world KL_mkt - KL_pool; positive => pool "
          "better):")
    for r in results:
        gc, gf = r["gap_comb_ci"], r["gap_flat_ci"]
        print(f"  {r['condition']:<42}"
              f"comb {r['gap_comb_mean']:+.4f} [{gc[0]:+.4f},{gc[1]:+.4f}]   "
              f"flat {r['gap_flat_mean']:+.4f} [{gf[0]:+.4f},{gf[1]:+.4f}]")
    print("\nExpected P&L per trader group (comb arm; maker = LMSR "
          "counterparty, negative = subsidy paid):")
    for r in results:
        pl = "  ".join(f"{k}={v:+.2f}" for k, v in r["pnl"].items()
                       if v == v)  # skip NaN for absent groups
        print(f"  {r['condition']:<42}{pl}  maker={r['maker_pnl_mean']:+.2f}")
    with open(args.out, "w") as fh:
        json.dump({"seed": args.seed, "worlds": args.worlds,
                   "results": results}, fh, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
