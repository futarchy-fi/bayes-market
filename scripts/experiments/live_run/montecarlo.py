#!/usr/bin/env python3
"""Monte Carlo: does the combinatorial market beat flat markets, and does the
edge come from *relational* information (Stage-3 hypothesis)?

Both arms run on the SAME production engine (backend.inference.FactoredMarket).
A no-edge FactoredMarket is numerically identical to independent binary LMSRs,
so the ONLY difference between arms is one structural edge:

    comb arm : AGI41 -> GOODS39            (the single genuine conditional edge)
    flat arm : AGI41, GOODS39 independent  (no edge)

GOODS40 and RND are independent roots in both arms (nuisance nodes; they let the
joint be 4-dimensional without adding structure either arm can exploit).

Dual elicitation (v2): every agent holds ONE belief, expressed through two
interfaces. A *relational* agent trades the conditional P(GOODS39 | AGI41) in
the comb arm, but can only trade the implied marginal in the flat arm -- flat
cannot represent the dependence. A *marginal* agent trades marginals in both
arms identically. Both arms receive the identical decision stream, so incentive
asymmetry cannot move the beliefs (they are elicited once, applied to both).

Primary estimand, per run:
    delta_KL = KL(ground_truth || flat_joint) - KL(ground_truth || comb_joint)
Positive => comb is closer to the truth. We report the distribution of delta_KL
over many runs (mean, 95% CI, win-rate), stratified by condition.

Controls that make the result falsifiable:
  * no-dependence     : ground-truth conditional gap ~ 0  -> comb must NOT win.
  * marginal-only     : zero relational agents             -> comb must NOT win.
These pin down that any comb advantage is caused by relational information
carried by relational agents, not by the extra parameter or by chance.

Read-only, offline, no network, no credits. Deterministic given --seed.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass, field

from backend.inference.factored_market import FactoredMarket

AGI, G39, G40, RND = "AGI41", "GOODS39", "GOODS40", "RND"
OUT = ("yes", "no")
LIQ = 50.0          # matches the live net venue's b
MAX_WIDTH = 8
CLIP = 0.02         # keep probabilities strictly inside (0, 1) for the LMSR


def _clip(p: float) -> float:
    return min(1.0 - CLIP, max(CLIP, p))


def _root(var: str, yes: float) -> dict:
    yes = _clip(yes)
    return {"variable_id": var, "outcomes": OUT, "parents": (),
            "rows": {frozenset(): {"yes": yes, "no": 1.0 - yes}}}


def _child(var: str, parent: str, y_given_yes: float, y_given_no: float) -> dict:
    yy, yn = _clip(y_given_yes), _clip(y_given_no)
    return {"variable_id": var, "outcomes": OUT, "parents": (parent,),
            "rows": {
                frozenset({(parent, "yes")}): {"yes": yy, "no": 1.0 - yy},
                frozenset({(parent, "no")}): {"yes": yn, "no": 1.0 - yn}}}


def _build_pair() -> tuple[FactoredMarket, FactoredMarket]:
    """Both arms initialised to a flat 0.5 prior (no structural head start)."""
    comb_nodes = [_root(AGI, 0.5), _child(G39, AGI, 0.5, 0.5),
                  _root(G40, 0.5), _root(RND, 0.5)]
    flat_nodes = [_root(AGI, 0.5), _root(G39, 0.5),
                  _root(G40, 0.5), _root(RND, 0.5)]
    comb = FactoredMarket.from_nodes(comb_nodes, LIQ, MAX_WIDTH)
    flat = FactoredMarket.from_nodes(flat_nodes, LIQ, MAX_WIDTH)
    return comb, flat


# ---- ground truth ----------------------------------------------------------


@dataclass
class Truth:
    p_agi: float
    g39_given_yes: float
    g39_given_no: float
    p_g40: float
    p_rnd: float

    @property
    def gap(self) -> float:
        return self.g39_given_yes - self.g39_given_no

    def joint(self) -> dict[tuple[str, str, str, str], float]:
        out: dict[tuple[str, str, str, str], float] = {}
        for a in OUT:
            pa = self.p_agi if a == "yes" else 1 - self.p_agi
            pg_cond = self.g39_given_yes if a == "yes" else self.g39_given_no
            for g in OUT:
                pg = pg_cond if g == "yes" else 1 - pg_cond
                for h in OUT:
                    p40 = self.p_g40 if h == "yes" else 1 - self.p_g40
                    for r in OUT:
                        pr = self.p_rnd if r == "yes" else 1 - self.p_rnd
                        out[(a, g, h, r)] = pa * pg * p40 * pr
        return out


def sample_truth(rng: random.Random, dependence: bool) -> Truth:
    p_agi = rng.uniform(0.25, 0.75)
    base = rng.uniform(0.2, 0.8)
    if dependence:
        half = rng.uniform(0.15, 0.35)          # genuine, sizable gap
        gy, gn = _clip(base + half), _clip(base - half)
    else:
        jitter = rng.uniform(-0.03, 0.03)        # ~ no dependence (control)
        gy, gn = _clip(base + jitter), _clip(base - jitter)
    return Truth(p_agi, gy, gn, rng.uniform(0.2, 0.8), rng.uniform(0.2, 0.8))


# ---- agents ----------------------------------------------------------------


@dataclass
class Agent:
    relational: bool
    b_agi: float
    b_g39_y: float      # belief P(G39 | AGI=yes)   (relational)
    b_g39_n: float      # belief P(G39 | AGI=no)    (relational)
    b_g39_marg: float   # belief P(G39) marginal    (marginal agent)
    b_g40: float
    b_rnd: float


def _noisy(rng: random.Random, p: float, sigma: float) -> float:
    return _clip(p + rng.gauss(0.0, sigma))


def sample_agents(rng: random.Random, n: int, frac_relational: float,
                  sigma: float, truth: Truth) -> list[Agent]:
    agents: list[Agent] = []
    n_rel = round(n * frac_relational)
    for i in range(n):
        relational = i < n_rel
        b_agi = _noisy(rng, truth.p_agi, sigma)
        agents.append(Agent(
            relational=relational,
            b_agi=b_agi,
            b_g39_y=_noisy(rng, truth.g39_given_yes, sigma),
            b_g39_n=_noisy(rng, truth.g39_given_no, sigma),
            # A marginal agent sees only the blended marginal of the truth,
            # observed through the same noise -- it never perceives the split.
            b_g39_marg=_noisy(
                rng,
                truth.p_agi * truth.g39_given_yes
                + (1 - truth.p_agi) * truth.g39_given_no,
                sigma),
            b_g40=_noisy(rng, truth.p_g40, sigma),
            b_rnd=_noisy(rng, truth.p_rnd, sigma),
        ))
    rng.shuffle(agents)
    return agents


def _nudge(market: FactoredMarket, var: str, target: float, alpha: float,
           context: dict | None = None) -> None:
    """Move the (conditional) price a fraction alpha toward target -- bounded
    impact, so a crowd of agents aggregates rather than the last one winning."""
    cur = market.marginal(var, context or None)
    if cur is None:
        return
    new = _clip(cur["yes"] + alpha * (target - cur["yes"]))
    market.trade_to_probability(var, "yes", new, context=context)


def run_agents(comb: FactoredMarket, flat: FactoredMarket,
               agents: list[Agent], alpha: float) -> None:
    for ag in agents:
        # Nuisance + AGI marginals: identical in both arms.
        for market in (comb, flat):
            _nudge(market, AGI, ag.b_agi, alpha)
            _nudge(market, G40, ag.b_g40, alpha)
            _nudge(market, RND, ag.b_rnd, alpha)
        if ag.relational:
            # Full interface (comb): trade the conditional both ways.
            _nudge(comb, G39, ag.b_g39_y, alpha, context={AGI: "yes"})
            _nudge(comb, G39, ag.b_g39_n, alpha, context={AGI: "no"})
            # Flat interface: only the implied marginal is expressible.
            implied = ag.b_agi * ag.b_g39_y + (1 - ag.b_agi) * ag.b_g39_n
            _nudge(flat, G39, implied, alpha)
        else:
            # Marginal agent: same marginal target in both arms.
            _nudge(comb, G39, ag.b_g39_marg, alpha)
            _nudge(flat, G39, ag.b_g39_marg, alpha)


# ---- scoring ---------------------------------------------------------------


def market_joint(m: FactoredMarket) -> dict[tuple[str, str, str, str], float]:
    """Reconstruct the 4-var joint from the market's own (conditional) prices.
    Only AGI->G39 can be dependent; G40, RND are independent in both arms."""
    p_agi = m.marginal(AGI)["yes"]
    g_y = m.marginal(G39, {AGI: "yes"})["yes"]
    g_n = m.marginal(G39, {AGI: "no"})["yes"]
    p40 = m.marginal(G40)["yes"]
    prnd = m.marginal(RND)["yes"]
    out: dict[tuple[str, str, str, str], float] = {}
    for a in OUT:
        pa = p_agi if a == "yes" else 1 - p_agi
        gc = g_y if a == "yes" else g_n
        for g in OUT:
            pg = gc if g == "yes" else 1 - gc
            for h in OUT:
                ph = p40 if h == "yes" else 1 - p40
                for r in OUT:
                    pr = prnd if r == "yes" else 1 - prnd
                    out[(a, g, h, r)] = pa * pg * ph * pr
    return out


def kl(truth: dict, model: dict) -> float:
    total = 0.0
    for state, pt in truth.items():
        if pt <= 0.0:
            continue
        pm = max(model.get(state, 0.0), 1e-12)
        total += pt * math.log(pt / pm)
    return total


def mutual_info_agi_g39(t: Truth) -> float:
    """I(AGI; GOODS39) in nats for the ground-truth joint. This is the
    irreducible KL penalty any independence-constrained (flat) forecast pays
    even with perfect marginals -- the theoretical ceiling on comb's edge."""
    p_a = t.p_agi
    p_g = t.p_agi * t.g39_given_yes + (1 - t.p_agi) * t.g39_given_no
    info = 0.0
    for a, pa, gc in (("y", p_a, t.g39_given_yes), ("n", 1 - p_a, t.g39_given_no)):
        for g, pg_joint_cond in (("y", gc), ("n", 1 - gc)):
            joint = pa * pg_joint_cond
            marg = pa * (p_g if g == "y" else 1 - p_g)
            if joint > 0.0 and marg > 0.0:
                info += joint * math.log(joint / marg)
    return info


# ---- experiment ------------------------------------------------------------


@dataclass
class Condition:
    name: str
    dependence: bool
    frac_relational: float
    sigma: float = 0.12
    n_agents: int = 40
    alpha: float = 0.2


@dataclass
class Summary:
    condition: str
    runs: int
    mean_delta_kl: float
    ci95: tuple[float, float]
    win_rate: float
    mean_kl_flat: float
    mean_kl_comb: float
    mean_gap_truth: float
    mean_spread_comb: float
    mean_spread_flat: float
    # Measured per-run mutual information I(AGI;G39) and how ΔKL relates to it.
    # I is the irreducible KL flat pays with *perfect* marginals; comparing ΔKL
    # to I (not asserting equality) separates representational ceiling from the
    # estimation/aggregation error our stylized nudge policy introduces.
    mean_info: float
    mean_delta_minus_info: float
    corr_delta_info: float
    # Honest clipping report: realized conditional gap after sampling+clip, and
    # the share of runs where either conditional probability hit the CLIP rail.
    realized_gap_p10: float
    realized_gap_p90: float
    clip_rate: float
    deltas: list[float] = field(default_factory=list)


def _ci95(xs: list[float]) -> tuple[float, float]:
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    m = statistics.mean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    return (m - 1.96 * se, m + 1.96 * se)


def _corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    try:
        return statistics.correlation(xs, ys)
    except (statistics.StatisticsError, ZeroDivisionError):
        return float("nan")


def _pctl(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def _hit_clip(t: Truth) -> bool:
    rail_lo, rail_hi = CLIP + 1e-9, 1.0 - CLIP - 1e-9
    return (t.g39_given_yes <= rail_lo or t.g39_given_yes >= rail_hi
            or t.g39_given_no <= rail_lo or t.g39_given_no >= rail_hi)


def run_condition(cond: Condition, runs: int, seed: int) -> Summary:
    rng = random.Random(seed)
    deltas, kl_flat, kl_comb = [], [], []
    gaps, spread_comb, spread_flat = [], [], []
    infos, delta_minus_info, realized_gaps = [], [], []
    n_clipped = 0
    for _ in range(runs):
        truth = sample_truth(rng, cond.dependence)
        agents = sample_agents(rng, cond.n_agents, cond.frac_relational,
                               cond.sigma, truth)
        comb, flat = _build_pair()
        run_agents(comb, flat, agents, cond.alpha)
        gt = truth.joint()
        kc, kf = kl(gt, market_joint(comb)), kl(gt, market_joint(flat))
        info = mutual_info_agi_g39(truth)
        deltas.append(kf - kc)
        kl_comb.append(kc)
        kl_flat.append(kf)
        gaps.append(truth.gap)
        infos.append(info)
        delta_minus_info.append((kf - kc) - info)
        realized_gaps.append(truth.gap)          # post-clip by construction
        if _hit_clip(truth):
            n_clipped += 1
        spread_comb.append(
            comb.marginal(G39, {AGI: "yes"})["yes"]
            - comb.marginal(G39, {AGI: "no"})["yes"])
        spread_flat.append(
            flat.marginal(G39, {AGI: "yes"})["yes"]
            - flat.marginal(G39, {AGI: "no"})["yes"])
    return Summary(
        condition=cond.name,
        runs=runs,
        mean_delta_kl=statistics.mean(deltas),
        ci95=_ci95(deltas),
        win_rate=sum(1 for d in deltas if d > 0) / len(deltas),
        mean_kl_flat=statistics.mean(kl_flat),
        mean_kl_comb=statistics.mean(kl_comb),
        mean_gap_truth=statistics.mean(gaps),
        mean_spread_comb=statistics.mean(spread_comb),
        mean_spread_flat=statistics.mean(spread_flat),
        mean_info=statistics.mean(infos),
        mean_delta_minus_info=statistics.mean(delta_minus_info),
        corr_delta_info=_corr(deltas, infos),
        realized_gap_p10=_pctl(realized_gaps, 0.10),
        realized_gap_p90=_pctl(realized_gaps, 0.90),
        clip_rate=n_clipped / runs,
        deltas=deltas,
    )


def default_conditions() -> list[Condition]:
    return [
        Condition("dependence, 50% relational", True, 0.50),
        Condition("dependence, 100% relational", True, 1.00),
        Condition("dependence, 25% relational", True, 0.25),
        Condition("CONTROL no-dependence, 50% relational", False, 0.50),
        Condition("CONTROL marginal-only (0% relational)", True, 0.00),
        Condition("dependence, 100% rel, low noise", True, 1.00, sigma=0.06),
        Condition("dependence, 100% rel, high noise", True, 1.00, sigma=0.20),
    ]


def self_check() -> None:
    """Assert the two structural invariants the whole comparison rests on, so a
    regression in the engine can never silently inflate ΔKL:

      (1) No-edge identity: a comb arm whose child row carries no information
          (P(G39|AGI=yes)==P(G39|AGI=no)) is byte-identical to the flat arm.
      (2) Called-off invariance: a conditional trade on the comb child leaves
          the parent (AGI) and nuisance (G40, RND) marginals fixed -- so ΔKL
          cannot be contaminated by relational trades leaking into marginals.
    """
    # (1) no-edge identity
    comb, flat = _build_pair()
    for m in (comb, flat):
        _nudge(m, AGI, 0.6, 1.0)
        _nudge(m, G39, 0.61, 1.0) if m is flat else None
    _nudge(comb, G39, 0.61, 1.0, context={AGI: "yes"})
    _nudge(comb, G39, 0.61, 1.0, context={AGI: "no"})
    cg = comb.marginal(G39)["yes"]
    fg = flat.marginal(G39)["yes"]
    assert abs(cg - fg) < 1e-9, f"no-edge identity broke: {cg} vs {fg}"

    # (2) called-off invariance
    comb, _ = _build_pair()
    _nudge(comb, AGI, 0.6, 1.0)
    _nudge(comb, G40, 0.55, 1.0)
    _nudge(comb, RND, 0.45, 1.0)
    before = (comb.marginal(AGI)["yes"], comb.marginal(G40)["yes"],
              comb.marginal(RND)["yes"])
    _nudge(comb, G39, 0.9, 1.0, context={AGI: "yes"})
    _nudge(comb, G39, 0.1, 1.0, context={AGI: "no"})
    after = (comb.marginal(AGI)["yes"], comb.marginal(G40)["yes"],
             comb.marginal(RND)["yes"])
    drift = max(abs(a - b) for a, b in zip(before, after))
    assert drift < 1e-9, f"called-off invariance broke: drift={drift:.2e}"
    print(f"self-check OK: no-edge identity |Δ|={abs(cg-fg):.2e}, "
          f"parent/nuisance drift={drift:.2e}\n")


def dose_response(runs: int, seed: int) -> list[Summary]:
    """Sweep relational fraction to expose the dose-response curve instead of
    asserting an effect from a single 50%-relational point (reviewer ask)."""
    fracs = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    out: list[Summary] = []
    for j, f in enumerate(fracs):
        cond = Condition(f"dose relational={int(f*100):>3}%", True, f)
        out.append(run_condition(cond, runs, seed + 500 + j * 100))
    return out


def _print_table(results: list[Summary]) -> None:
    header = (f"{'condition':<40}{'ΔKL':>9}{'95% CI':>19}{'win%':>6}"
              f"{'I(A;G)':>8}{'ΔKL-I':>9}{'r(Δ,I)':>8}{'clip%':>7}")
    print(header)
    print("-" * len(header))
    for s in results:
        ci = f"[{s.ci95[0]:+.4f},{s.ci95[1]:+.4f}]"
        print(f"{s.condition:<40}{s.mean_delta_kl:>+9.4f}{ci:>19}"
              f"{s.win_rate*100:>5.0f}%{s.mean_info:>8.4f}"
              f"{s.mean_delta_minus_info:>+9.4f}{s.corr_delta_info:>8.3f}"
              f"{s.clip_rate*100:>6.0f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=500,
                    help="Monte Carlo runs per condition")
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", default="/tmp/montecarlo_results.json")
    ap.add_argument("--sweep", action="store_true",
                    help="also run the relational-fraction dose-response sweep")
    args = ap.parse_args()

    self_check()

    conditions = default_conditions()
    results: list[Summary] = []
    print(f"Monte Carlo: {args.runs} runs x {len(conditions)} conditions "
          f"(seed={args.seed})")
    print("ΔKL = KL(truth‖flat) - KL(truth‖comb);  I(A;G) = ground-truth "
          "mutual info (flat's irreducible penalty);\nΔKL-I isolates estimation"
          "/aggregation error;  r(Δ,I) = per-run correlation of ΔKL with I.\n")
    for i, cond in enumerate(conditions):
        results.append(run_condition(cond, args.runs, args.seed + i * 1000))
    _print_table(results)

    sweep: list[Summary] = []
    if args.sweep:
        print("\nDose-response (dependence on, relational fraction swept):")
        sweep = dose_response(args.runs, args.seed)
        _print_table(sweep)

    payload = {
        "runs_per_condition": args.runs,
        "seed": args.seed,
        "engine": "backend.inference.FactoredMarket",
        "liquidity": LIQ,
        "estimand": "delta_KL = KL(truth||flat) - KL(truth||comb)",
        "conditions": [
            {k: v for k, v in s.__dict__.items() if k != "deltas"}
            for s in results + sweep
        ],
    }
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
