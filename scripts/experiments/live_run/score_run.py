#!/usr/bin/env python3
"""Score one comb-vs-flat run against the PRE-REGISTERED full-information target.

Reads the artefact emitted by `preview_run.py --prompts` (frozen prior pi0,
pre-registration, target) plus the collected agent decisions, replays each arm
on the production engine, and reports KL(target || arm) for both arms.

The target is the joint implied by pooling every pre-registered signal against
pi0 -- fixed before elicitation, so "which arm aggregates better" is answered
against a benchmark nobody chose after seeing the answer. Resolution accuracy
stays long-horizon; this measures aggregation of the induced information.

    PYTHONPATH=. python3 scripts/experiments/live_run/score_run.py \
        --run /tmp/q3_prompts2.json --decisions /tmp/q3_decisions.json

Offline: both arms are replayed locally. The live comb arm is scored the same
way from its own snapshot (see --live-after).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import signal_design as sig  # noqa: E402
from backend.inference.factored_market import FactoredMarket  # noqa: E402

OUT = ("yes", "no")
LIQ = 50.0
MAX_WIDTH = 8
CLIP = 0.02


def _clip(p: float) -> float:
    return min(1 - CLIP, max(CLIP, p))


def _root(var: str, yes: float) -> dict:
    yes = _clip(yes)
    return {"variable_id": var, "outcomes": OUT, "parents": (),
            "rows": {frozenset(): {"yes": yes, "no": 1 - yes}}}


def _child(var: str, parent: str, gy: float, gn: float) -> dict:
    gy, gn = _clip(gy), _clip(gn)
    return {"variable_id": var, "outcomes": OUT, "parents": (parent,),
            "rows": {frozenset({(parent, "yes")}): {"yes": gy, "no": 1 - gy},
                     frozenset({(parent, "no")}): {"yes": gn, "no": 1 - gn}}}


def build_arms(pi0: dict[str, float], order: list[str], driver: str,
               child: str) -> tuple[FactoredMarket, FactoredMarket]:
    """Both arms start at the SAME frozen prior. The comb arm carries the one
    genuine edge; the flat arm is edge-free (numerically identical to
    independent binary LMSRs at the same b)."""
    comb_nodes, flat_nodes = [], []
    for v in order:
        if v == child:
            comb_nodes.append(_child(v, driver, pi0[v], pi0[v]))
        else:
            comb_nodes.append(_root(v, pi0[v]))
        flat_nodes.append(_root(v, pi0[v]))
    return (FactoredMarket.from_nodes(comb_nodes, LIQ, MAX_WIDTH),
            FactoredMarket.from_nodes(flat_nodes, LIQ, MAX_WIDTH))


def apply_decision(market: FactoredMarket, decision: list, arm: str,
                   adapter: bool = True, shown_prices: dict | None = None) -> int:
    """Apply one agent's actions. Conditional actions are dropped in the flat
    arm -- that is exactly the representational limit under test, not a bug.

    With `adapter` (the pre-registered default), a *pair* of conditional
    actions on the same child is treated as a rendering of an odds ratio and
    re-expressed at the current margins before execution -- see
    signal_design.reexpress_at. Applied mechanically to every order in every
    arm; `--no-adapter` reproduces the raw stated-probability protocol."""
    n = 0
    shown_prices = shown_prices or {}
    if adapter:
        # MARGINAL adapter: a stated absolute probability is read as "prior +
        # my evidence", so we extract the evidence (its log-odds distance from
        # the price the agent was shown) and re-apply it to the CURRENT price.
        # Log-odds shifts commute, so independent signals now compose instead
        # of overwriting each other -- without this, set_marginal at alpha=1.0
        # is last-writer-wins and the final price is whoever traded last.
        for act in decision:
            if act.get("action") != "set_marginal":
                continue
            q = act.get("question")
            try:
                shown = shown_prices.get(q)
                stated = float(act["probability"])
                if shown is None:
                    continue
                shift = sig.logit(stated) - sig.logit(shown)
                cur = market.marginal(q)["yes"]
                market.trade_to_probability(
                    q, "yes", _clip(sig.expit(sig.logit(cur) + shift)))
                n += 1
            except Exception as exc:
                print(f"  ! marginal adapter failed on {q}: {exc}",
                      file=sys.stderr)
        decision = [a for a in decision if a.get("action") != "set_marginal"]
    conds = [a for a in decision if a.get("action") == "set_conditional"]
    if adapter and arm != "flat" and len(conds) == 2:
        try:
            g0 = conds[0].get("given") or {}
            driver = g0["question"]
            child = conds[0]["question"]
            by = {(a.get("given") or {}).get("outcome"): float(a["probability"])
                  for a in conds}
            cur_d = market.marginal(driver)["yes"]
            cur_c = market.marginal(child)["yes"]
            gy, gn = sig.reexpress_at(by["yes"], by["no"], cur_d, cur_c)
            for outcome, newp in (("yes", gy), ("no", gn)):
                market.trade_to_probability(child, "yes", _clip(newp),
                                            context={driver: outcome})
                n += 1
            decision = [a for a in decision if a.get("action") != "set_conditional"]
        except Exception as exc:
            print(f"  ! adapter failed, falling back to raw: {exc}",
                  file=sys.stderr)
    for act in decision:
        kind = act.get("action")
        q = act.get("question")
        p = act.get("probability")
        if q is None or p is None:
            continue
        try:
            if kind == "set_marginal":
                market.trade_to_probability(q, "yes", _clip(float(p)))
                n += 1
            elif kind == "set_conditional":
                if arm == "flat":
                    continue            # inexpressible in independent books
                g = act.get("given") or {}
                ctx = {g["question"]: g["outcome"]}
                market.trade_to_probability(q, "yes", _clip(float(p)),
                                            context=ctx)
                n += 1
        except Exception as exc:        # malformed action: skip, keep going
            print(f"  ! skipped {kind} {q}: {exc}", file=sys.stderr)
    return n


def decompose(target: dict, m: FactoredMarket, order: list[str], driver: str,
              child: str) -> dict:
    """Split the joint error into a MARGIN part and a DEPENDENCE part.

    marginal_kl      : a genuine KL -- between the target margins and the arm's
                       margins, both treated as independent. Error in levels.
    dependence_resid : total joint KL MINUS the marginal part. This is a signed
                       ATTRIBUTION, not a KL component: it can go slightly
                       negative (KL itself never can), which just means the
                       arm's joint fits marginally worse than its own margins
                       would suggest in isolation. Reported separately because
                       an arm can buy dependence accuracy while losing margin
                       accuracy -- exactly what the first dry run did."""
    tm = target["marginals"]
    am = {v: m.marginal(v)["yes"] for v in order}
    marg_kl = 0.0
    for v in order:
        t, a = tm[v], am[v]
        marg_kl += (t * math.log(t / max(a, 1e-12))
                    + (1 - t) * math.log((1 - t) / max(1 - a, 1e-12)))
    tj = sig.target_joint(target, order)
    total = kl(tj, market_joint(m, order, driver, child))
    return {"marginal_kl": marg_kl, "dependence_resid": total - marg_kl,
            "total_kl": total}


def market_joint(m: FactoredMarket, order: list[str], driver: str,
                 child: str) -> dict[tuple, float]:
    p = {v: m.marginal(v)["yes"] for v in order if v != child}
    gy = m.marginal(child, {driver: "yes"})["yes"]
    gn = m.marginal(child, {driver: "no"})["yes"]
    out: dict[tuple, float] = {}
    for bits in range(1 << len(order)):
        assign = {v: OUT[(bits >> i) & 1] for i, v in enumerate(order)}
        prob = 1.0
        for v in order:
            yes = assign[v] == "yes"
            pv = (gy if assign[driver] == "yes" else gn) if v == child else p[v]
            prob *= pv if yes else 1 - pv
        out[tuple(assign[v] for v in order)] = prob
    return out


def kl(target: dict, model: dict) -> float:
    tot = 0.0
    for s, pt in target.items():
        if pt <= 0:
            continue
        tot += pt * math.log(pt / max(model.get(s, 0.0), 1e-12))
    return tot


def order_sweep(run, decisions, pi0, order, driver, child, n_orders,
                adapter=True, seed=20260728) -> dict:
    """Replay the same decisions under N random arrival orders. A protocol
    whose conclusion depends on who trades first is not reporting a property of
    the venue; this quantifies how much of delta_KL is order noise."""
    import random as _r
    rng = _r.Random(seed)
    specs = [s for s in run["prompts"] if decisions.get(s["id"])]
    combs, flats, deltas = [], [], []
    for _ in range(n_orders):
        seq = specs[:]
        rng.shuffle(seq)
        c, f = build_arms(pi0, order, driver, child)
        for spec in seq:
            apply_decision(c if spec["arm"] == "comb" else f,
                           decisions[spec["id"]], spec["arm"], adapter=adapter,
                           shown_prices=pi0)
        tj = sig.target_joint(run["full_information_target"], order)
        kc = kl(tj, market_joint(c, order, driver, child))
        kf = kl(tj, market_joint(f, order, driver, child))
        combs.append(kc); flats.append(kf); deltas.append(kf - kc)
    return {"n": n_orders, "comb_min": min(combs), "comb_max": max(combs),
            "flat_min": min(flats), "flat_max": max(flats),
            "delta_min": min(deltas), "delta_max": max(deltas),
            "comb_wins": sum(1 for d in deltas if d > 0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="artefact from --prompts")
    ap.add_argument("--decisions", required=True,
                    help="JSON map {prompt_id: [actions]}")
    ap.add_argument("--out", default="/tmp/q3_score.json")
    ap.add_argument("--no-adapter", action="store_true",
                    help="raw stated-probability protocol (pre-adapter)")
    ap.add_argument("--permute-orders", type=int, default=0, metavar="N",
                    help="replay under N random arrival orders and report spread")
    args = ap.parse_args()

    run = json.loads(Path(args.run).read_text())
    decisions = json.loads(Path(args.decisions).read_text())
    pi0 = run["pi0"]
    order = list(pi0)
    edge = next(iter(run["full_information_target"]["conditionals"]))
    child, driver = edge.split("|")

    target = sig.target_joint(run["full_information_target"], order)
    comb, flat = build_arms(pi0, order, driver, child)
    prior_joint = market_joint(flat, order, driver, child)

    applied = {"comb": 0, "flat": 0}
    traded_agents = {"comb": 0, "flat": 0}
    for spec in run["prompts"]:
        pid, arm = spec["id"], spec["arm"]
        dec = decisions.get(pid)
        if not dec:
            continue
        n = apply_decision(comb if arm == "comb" else flat, dec, arm,
                           adapter=not args.no_adapter, shown_prices=pi0)
        applied[arm] += n
        traded_agents[arm] += 1 if n else 0

    jc = market_joint(comb, order, driver, child)
    jf = market_joint(flat, order, driver, child)
    res = {
        "digest": run["digest"],
        "pi0": pi0,
        "orders_applied": applied,
        "agents_that_traded": traded_agents,
        "kl_prior": kl(target, prior_joint),
        "kl_comb": kl(target, jc),
        "kl_flat": kl(target, jf),
        "final_marginals": {
            "comb": {v: comb.marginal(v)["yes"] for v in order},
            "flat": {v: flat.marginal(v)["yes"] for v in order}},
        "final_conditional_comb": {
            "yes": comb.marginal(child, {driver: "yes"})["yes"],
            "no": comb.marginal(child, {driver: "no"})["yes"]},
        "final_conditional_flat": {
            "yes": flat.marginal(child, {driver: "yes"})["yes"],
            "no": flat.marginal(child, {driver: "no"})["yes"]},
        "target": run["full_information_target"],
    }
    res["decomposition"] = {
        "comb": decompose(run["full_information_target"], comb, order, driver, child),
        "flat": decompose(run["full_information_target"], flat, order, driver, child)}
    res["adapter"] = not args.no_adapter
    if args.permute_orders:
        res["order_sensitivity"] = order_sweep(
            run, decisions, pi0, order, driver, child, args.permute_orders,
            adapter=not args.no_adapter)
    res["delta_kl"] = res["kl_flat"] - res["kl_comb"]
    res["kl_reduction_comb"] = res["kl_prior"] - res["kl_comb"]
    res["kl_reduction_flat"] = res["kl_prior"] - res["kl_flat"]

    print(f"pre-registration digest : {res['digest']}")
    print(f"orders applied          : comb={applied['comb']} flat={applied['flat']}"
          f"   (agents that traded: comb={traded_agents['comb']}/9 "
          f"flat={traded_agents['flat']}/9)")
    print()
    print(f"KL(target || prior)     : {res['kl_prior']:.5f}   <- start, both arms")
    print(f"KL(target || comb)      : {res['kl_comb']:.5f}   "
          f"(reduced {res['kl_reduction_comb']:+.5f})")
    print(f"KL(target || flat)      : {res['kl_flat']:.5f}   "
          f"(reduced {res['kl_reduction_flat']:+.5f})")
    print(f"delta_KL (flat - comb)  : {res['delta_kl']:+.5f}   "
          f"{'comb closer' if res['delta_kl'] > 0 else 'flat closer'}")
    print()
    t = run["full_information_target"]
    print("target vs realized:")
    for v in order:
        print(f"  {v:9} target {t['marginals'][v]:.3f} | "
              f"comb {res['final_marginals']['comb'][v]:.3f} | "
              f"flat {res['final_marginals']['flat'][v]:.3f}")
    tc = t["conditionals"][edge]
    print(f"  {edge}: target ({tc['yes']:.3f},{tc['no']:.3f}) | "
          f"comb ({res['final_conditional_comb']['yes']:.3f},"
          f"{res['final_conditional_comb']['no']:.3f}) | "
          f"flat ({res['final_conditional_flat']['yes']:.3f},"
          f"{res['final_conditional_flat']['no']:.3f})")
    Path(args.out).write_text(json.dumps(res, indent=2))
    dc, df = res["decomposition"]["comb"], res["decomposition"]["flat"]
    print()
    print(f"{'decomposition':22}{'margins KL':>12}{'dep. resid':>12}{'total':>9}"
          f"   (resid = signed attribution, not a KL)")
    print(f"{'  comb':22}{dc['marginal_kl']:>12.5f}{dc['dependence_resid']:>12.5f}"
          f"{dc['total_kl']:>9.5f}")
    print(f"{'  flat':22}{df['marginal_kl']:>12.5f}{df['dependence_resid']:>12.5f}"
          f"{df['total_kl']:>9.5f}")
    if res.get("order_sensitivity"):
        o = res["order_sensitivity"]
        print(f"\norder sensitivity ({o['n']} random arrival orders):")
        print(f"  comb KL  min {o['comb_min']:.5f}  max {o['comb_max']:.5f}  "
              f"spread {o['comb_max']-o['comb_min']:.5f}")
        print(f"  flat KL  min {o['flat_min']:.5f}  max {o['flat_max']:.5f}  "
              f"spread {o['flat_max']-o['flat_min']:.5f}")
        print(f"  delta_KL min {o['delta_min']:+.5f}  max {o['delta_max']:+.5f}"
              f"   comb wins {o['comb_wins']}/{o['n']}")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
