"""Stage-3 Q3b: does WEALTH SELECTION rescue the market mechanism?

Q3a left one market-native hypothesis standing: across repeated settled
events, profitable (i.e. genuinely informed) traders accumulate wealth and
therefore influence, so the market's terminal prices should improve over time
-- something a static equal-weight pool cannot do. The literature makes this
conditional, not guaranteed (Beygelzimer-Langford-Pennock 2012 prove it for
Kelly bettors in a budget-balanced parimutuel setting, NOT for sequential
subsidized LMSR; Kets et al. 2014 show aggressive sizing can destroy the very
heterogeneity that makes crowds accurate; risk-neutral sizing implies ruin
w.p. 1 across repeated gambles). Hence, per design review, two phases:

  PHASE 1 (validate the machinery where theory has predictions): a repeated
  BINARY market on the same engine (single root node). Pre-registered
  predictions:
    P1  informed traders' wealth share rises over epochs under (fractional)
        Kelly sizing;
    P2  market KL falls from early to late epochs under Kelly, and does NOT
        fall in the equal-quality control (no quality differences to select);
    P3  under risk-neutral sizing, ruin (wealth driven to ~0; sizing is
        solvency-bounded so wealth never goes negative) exceeds Kelly's.
        OUTCOME NOTE (kept honest): P1 and the ruin half of P3 held; the
        accuracy half of P3 FAILED -- risk-neutral showed a slightly larger
        early->late KL improvement than Kelly (its harsher selection
        concentrates wealth faster), while remaining ~4x less accurate in
        absolute KL. P2's improvement claim was not detectable in phase 1
        (no CIs were pre-computed there; ceiling effects are a live
        alternative), and IS established in phase 2 with paired CIs plus a
        selection/capitalization decomposition (see PR body).

  PHASE 2 (port to the combinatorial engine): comb vs flat arms with the same
  Kelly traders and per-arm wealth carried across epochs; per-epoch KL
  trajectories vs the static pools. The question: does wealth selection close
  the market-vs-pool gap that Q3a measured, in either arm?

Trading: one randomized pass per epoch; per-contract sizing maximizes
E_posterior[log(bankroll_x + payoff_x)] over the solvency-feasible move
(ternary search in log-odds), with bankroll_x = wealth + cumulative payoff in
state x (so, within an epoch, later trades hedge earlier positions -- only
material in phase 2, where traders hold several contracts). Honest labels,
per review: (a) sizing is certainty-equivalent Kelly on the posterior MEAN,
not Bayesian Kelly over the posterior; (b) lambda<1 shrinks the move in
LOG-ODDS toward the full-Kelly target -- a conservative variant, not exactly
"lambda times the Kelly stake"; (c) settlement is BATCH (K i.i.d. outcomes
per epoch, payoff averaged) which lowers wealth-update variance -- the K=1
rows are the internally-consistent single-outcome Kelly cells, and the K=25
Kelly sizing is conservative relative to a true batch-Kelly objective.

Run:  PYTHONPATH=. python3 scripts/experiments/live_run/stage3_wealth.py
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
import montecarlo as mc          # noqa: E402
import stage3_market as sm       # noqa: E402

from backend.inference.factored_market import FactoredMarket  # noqa: E402


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ---- Kelly sizing on an LMSR price move ------------------------------------


def kelly_target(bankroll: list[float], payoff_of: "callable",
                 belief_probs: list[float], p: float, belief: float,
                 b: float, lam: float) -> float | None:
    """Move the (conditional) yes-price p toward `belief`, sizing by expected
    log-bankroll. bankroll[i] = trader's per-state wealth BEFORE this trade;
    payoff_of(q) -> per-state payoff vector of moving p->q; belief_probs[i] =
    trader's subjective probability of state i.

    Full Kelly maximizes sum_i belief_probs[i]*log(bankroll[i]+payoff[i])
    over feasible q strictly between p and belief (ternary search in
    log-odds; the objective is unimodal on the feasible segment). Fractional
    Kelly (lam<1) then shrinks the move in log-odds. Returns None if no
    feasible improving move exists."""
    if abs(belief - p) < 1e-4:
        return None
    lp, lb = _logit(p), _logit(belief)

    def value(q: float) -> float:
        pay = payoff_of(q)
        tot = 0.0
        for pr, w0, dw in zip(belief_probs, bankroll, pay):
            if pr <= 0.0:
                continue
            w1 = w0 + dw
            if w1 <= 1e-12:
                return -math.inf
            tot += pr * math.log(w1)
        return tot

    base = value(p + (belief - p) * 1e-9)   # ~current, must be finite
    if base == -math.inf:
        return None
    lo, hi = 0.0, 1.0                       # fraction of the log-odds move
    for _ in range(60):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        v1 = value(_expit(lp + m1 * (lb - lp)))
        v2 = value(_expit(lp + m2 * (lb - lp)))
        if v1 < v2:
            lo = m1
        else:
            hi = m2
    frac = (lo + hi) / 2.0
    if value(_expit(lp + frac * (lb - lp))) <= base:
        return None
    frac *= lam
    if frac < 1e-6:
        return None
    return _expit(lp + frac * (lb - lp))


# ---- Phase 1: repeated binary market ----------------------------------------


@dataclass
class BTrader:
    n_obs: int
    wealth: float
    belief: float = 0.5


def phase1(worlds: int, seed: int, sizing: str, lam: float,
           equal_quality: bool, n_informed: int = 5, n_noise: int = 15,
           obs_hi: int = 200, obs_lo: int = 8, wealth0: float = 25.0,
           batch_k: int = 25, liq: float = 50.0) -> dict:
    rng = random.Random(seed)
    if equal_quality:
        traders = [BTrader(obs_lo, wealth0)
                   for _ in range(n_informed + n_noise)]
    else:
        traders = ([BTrader(obs_hi, wealth0) for _ in range(n_informed)]
                   + [BTrader(obs_lo, wealth0) for _ in range(n_noise)])
    informed_ix = set(range(n_informed)) if not equal_quality else set()

    kls, wshare, bankrupt = [], [], 0
    for _ in range(worlds):
        theta = rng.uniform(0.1, 0.9)
        for tr in traders:
            k = sum(1 for _ in range(tr.n_obs) if rng.random() < theta)
            tr.belief = (k + 1.0) / (tr.n_obs + 2.0)
        market = _binary_market(liq)
        payoffs = [[0.0, 0.0] for _ in traders]   # [yes, no] per trader
        order = list(range(len(traders)))
        rng.shuffle(order)
        for ix in order:
            tr = traders[ix]
            if tr.wealth <= 1e-6:
                continue
            p = market.marginal("X")["yes"]

            def payoff_of(q: float, _p: float = p) -> list[float]:
                sh, c = sm._fill_terms(liq, _p, q)
                return [sh - c, -c]

            bank = [tr.wealth + payoffs[ix][0], tr.wealth + payoffs[ix][1]]
            if sizing == "kelly":
                target = kelly_target(bank, payoff_of,
                                      [tr.belief, 1 - tr.belief],
                                      p, tr.belief, liq, lam)
            else:                     # risk-neutral, solvency-bounded (Q3a)
                target = _rn_target(bank, payoff_of, p, tr.belief)
            if target is None:
                continue
            fill = market.trade_to_probability("X", "yes", target)
            sh, c = fill["shares"], fill["cost"]
            payoffs[ix][0] += sh - c
            payoffs[ix][1] += -c
        # batch settlement: K i.i.d. outcomes, averaged payoff
        hits = sum(1 for _ in range(batch_k) if rng.random() < theta)
        f_yes = hits / batch_k
        for ix, tr in enumerate(traders):
            pnl = f_yes * payoffs[ix][0] + (1 - f_yes) * payoffs[ix][1]
            tr.wealth = max(0.0, tr.wealth + pnl)
        price = market.marginal("X")["yes"]
        kls.append(theta * math.log(theta / price)
                   + (1 - theta) * math.log((1 - theta) / (1 - price)))
        total_w = sum(t.wealth for t in traders) or 1.0
        wshare.append(sum(traders[i].wealth for i in informed_ix) / total_w
                      if informed_ix else float("nan"))
    bankrupt = sum(1 for t in traders if t.wealth <= 1e-6)
    third = max(1, worlds // 3)
    return {
        "kl_early": statistics.mean(kls[:third]),
        "kl_late": statistics.mean(kls[-third:]),
        "wshare_start": wshare[0] if wshare else float("nan"),
        "wshare_end": wshare[-1] if wshare else float("nan"),
        "bankruptcies": bankrupt,
        "kls": kls, "wshare": wshare,
    }


def _binary_market(liq: float) -> FactoredMarket:
    return FactoredMarket.from_nodes([mc._root("X", 0.5)], liq, 8)


def _rn_target(bank: list[float], payoff_of, p: float,
               belief: float) -> float | None:
    """Q3a's risk-neutral sizing: as far toward belief as solvency allows."""
    if abs(belief - p) < 1e-4:
        return None

    def ok(q: float) -> bool:
        pay = payoff_of(q)
        return all(w + d >= 0.0 for w, d in zip(bank, pay))

    if ok(belief):
        return belief
    lo, hi = p, belief
    for _ in range(50):
        m = (lo + hi) / 2.0
        if ok(m):
            lo = m
        else:
            hi = m
    return lo if abs(lo - p) >= 1e-4 else None


def run_phase1(reps: int, worlds: int, seed: int) -> dict:
    print("PHASE 1 -- repeated binary market (validation against theory)")
    print(f"{reps} independent populations x {worlds} epochs; informed 5x"
          "n=200 vs noise 15x n=8; batch K=25\n")
    rows = [
        ("kelly lam=0.5", "kelly", 0.5, False, 25),
        ("kelly lam=1.0", "kelly", 1.0, False, 25),
        ("risk-neutral (Q3a sizing)", "rn", 1.0, False, 25),
        ("CONTROL equal quality, kelly 0.5", "kelly", 0.5, True, 25),
        # Single-outcome settlement: where theory predicts risk-neutral ruin
        # and the sharpest Kelly-vs-RN separation (batching dampens both).
        ("kelly lam=0.5, K=1", "kelly", 0.5, False, 1),
        ("risk-neutral, K=1", "rn", 1.0, False, 1),
    ]
    header = (f"{'variant':<34}{'KL early':>10}{'KL late':>10}{'Δ':>9}"
              f"{'wsh 0':>7}{'wsh T':>7}{'bankrupt':>10}")
    print(header)
    print("-" * len(header))
    out = {}
    for name, sizing, lam, eq, bk_ in rows:
        res = [phase1(worlds, seed + 17 * r, sizing, lam, eq, batch_k=bk_)
               for r in range(reps)]
        ke = statistics.mean(r["kl_early"] for r in res)
        kl = statistics.mean(r["kl_late"] for r in res)
        w0 = statistics.mean(r["wshare_start"] for r in res)
        wT = statistics.mean(r["wshare_end"] for r in res)
        bk = statistics.mean(r["bankruptcies"] for r in res)
        out[name] = {"kl_early": ke, "kl_late": kl,
                     "wshare0": w0, "wshareT": wT, "bankrupt": bk}
        print(f"{name:<34}{ke:>10.4f}{kl:>10.4f}{kl-ke:>+9.4f}"
              f"{w0:>7.2f}{wT:>7.2f}{bk:>10.1f}")
    return out


# ---- Phase 2: combinatorial engine with wealth carryover --------------------


def phase2_epoch(traders: list[sm.Trader], rng: random.Random, lam: float,
                 batch_k: int, sizing: str) -> dict:
    truth = mc.sample_truth(rng, True)
    gt = truth.joint()
    for tr in traders:
        sm.observe(rng, tr, truth)
        tr.reset_world()
    comb, flat = mc._build_pair()
    markets = {"comb": comb, "flat": flat}
    order = list(range(len(traders)))
    rng.shuffle(order)
    for ix in order:
        tr = traders[ix]
        views = []
        for arm in sm.ARMS:
            views.append((arm, sm.AGI, tr.b_agi, {}))
            views.append((arm, sm.G40, tr.b_g40, {}))
            views.append((arm, sm.RND, tr.b_rnd, {}))
        if tr.relational:
            views.append(("comb", sm.G39, tr.b_g39_y, {sm.AGI: "yes"}))
            views.append(("comb", sm.G39, tr.b_g39_n, {sm.AGI: "no"}))
            implied = tr.b_agi * tr.b_g39_y + (1 - tr.b_agi) * tr.b_g39_n
            views.append(("flat", sm.G39, implied, {}))
        else:
            views.append(("comb", sm.G39, tr.b_g39_marg, {}))
            views.append(("flat", sm.G39, tr.b_g39_marg, {}))
        rng.shuffle(views)
        belief_joint = mc.agent_joint(tr, "comb")
        bprobs = [belief_joint[s] for s in sm.STATES]
        for arm, var, belief, context in views:
            if tr.wealth[arm] <= 1e-6:
                continue
            market = markets[arm]
            p = sm._quote(market, var, context)

            def payoff_of(q: float, _p: float = p, _v: str = var,
                          _c: dict = context) -> list[float]:
                sh, c = sm._fill_terms(market.liquidity, _p, q)
                return [sm._fill_payoff(s, _v, "yes", _c, sh, c)
                        for s in sm.STATES]

            bank = [tr.wealth[arm] + x for x in tr.payoff[arm]]
            if sizing == "kelly":
                target = kelly_target(bank, payoff_of, bprobs, p, belief,
                                      market.liquidity, lam)
            else:
                target = sm.budget_target(tr, arm, market, var, belief,
                                          context)
            if target is None:
                continue
            sm.apply_trade(tr, arm, market, var, target, context)
    # batch settlement per arm
    outcomes = rng.choices(list(gt.keys()), weights=list(gt.values()),
                           k=batch_k)
    for tr in traders:
        for arm in sm.ARMS:
            pnl = statistics.mean(
                tr.payoff[arm][sm.STATE_IX[o]] for o in outcomes)
            tr.wealth[arm] = max(0.0, tr.wealth[arm] + pnl)
    kl_pool = {a: mc.kl(gt, mc.modular_pool(traders, a)) for a in sm.ARMS}
    return {
        "kl_mkt": {a: mc.kl(gt, mc.market_joint(markets[a]))
                   for a in sm.ARMS},
        "kl_pool": kl_pool,
    }


def run_phase2(reps: int, epochs: int, seed: int, lam: float = 0.5,
               batch_k: int = 25, sizing: str = "kelly") -> dict:
    """R independent populations, each living through E epochs with per-arm
    wealth carryover. Informed = rel-hi (n=400); the population mirrors Q3a's
    balanced condition."""
    trajs_mkt = {a: [[] for _ in range(epochs)] for a in sm.ARMS}
    trajs_pool = {a: [[] for _ in range(epochs)] for a in sm.ARMS}
    wshare = [[] for _ in range(epochs)]
    for r in range(reps):
        rng = random.Random(seed + 31 * r)
        cond = sm.Cond("q3b")
        traders = sm.make_traders(cond)
        informed = [i for i, t in enumerate(traders) if t.n_obs >= cond.obs_hi]
        for e in range(epochs):
            res = phase2_epoch(traders, rng, lam, batch_k, sizing)
            for a in sm.ARMS:
                trajs_mkt[a][e].append(res["kl_mkt"][a])
                trajs_pool[a][e].append(res["kl_pool"][a])
            tot = sum(t.wealth["comb"] for t in traders) or 1.0
            wshare[e].append(
                sum(traders[i].wealth["comb"] for i in informed) / tot)
    third = max(1, epochs // 3)
    def band(traj):
        per_epoch = [statistics.mean(xs) for xs in traj]
        return (statistics.mean(per_epoch[:third]),
                statistics.mean(per_epoch[-third:]))
    out = {}
    for a in sm.ARMS:
        e_m, l_m = band(trajs_mkt[a])
        e_p, l_p = band(trajs_pool[a])
        out[a] = {"mkt_early": e_m, "mkt_late": l_m,
                  "pool_early": e_p, "pool_late": l_p}
    out["wshare_start"] = statistics.mean(wshare[0])
    out["wshare_end"] = statistics.mean(wshare[-1])
    # paired early-vs-late per replicate (comb market)
    per_rep_delta = []
    for rix in range(reps):
        e = statistics.mean(trajs_mkt["comb"][i][rix] for i in range(third))
        l = statistics.mean(trajs_mkt["comb"][epochs - 1 - i][rix]
                            for i in range(third))
        per_rep_delta.append(l - e)
    out["comb_late_minus_early_ci"] = mc._ci95(per_rep_delta)
    out["comb_late_minus_early"] = statistics.mean(per_rep_delta)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--worlds", type=int, default=60,
                    help="epochs per population")
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", default="/tmp/stage3_wealth_results.json")
    ap.add_argument("--skip-phase2", action="store_true")
    args = ap.parse_args()

    p1 = run_phase1(args.reps, args.worlds, args.seed)

    payload = {"seed": args.seed, "reps": args.reps, "epochs": args.worlds,
               "phase1": p1}
    if not args.skip_phase2:
        print("\nPHASE 2 -- combinatorial engine, wealth carried across "
              "epochs (kelly lam=0.5, batch K=25)")
        p2 = run_phase2(args.reps, args.worlds, args.seed)
        for a in sm.ARMS:
            d = p2[a]
            print(f"  {a}: mkt early {d['mkt_early']:.4f} -> late "
                  f"{d['mkt_late']:.4f}   pool early {d['pool_early']:.4f} "
                  f"-> late {d['pool_late']:.4f}")
        print(f"  informed wealth share (comb): "
              f"{p2['wshare_start']:.2f} -> {p2['wshare_end']:.2f}")
        ci = p2["comb_late_minus_early_ci"]
        print(f"  comb mkt late-early (paired): "
              f"{p2['comb_late_minus_early']:+.4f} "
              f"[{ci[0]:+.4f},{ci[1]:+.4f}]  (negative = improves)")
        payload["phase2"] = p2
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
