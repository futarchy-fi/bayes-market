#!/usr/bin/env python3
"""Stage 1b: does the combinatorial market's AGGREGATE forecast beat flat's,
with a realistic mixed population of LLM agents?

Stage 1 (pilot) showed agents spontaneously use conditional trades for
relational evidence. That answers "do agents use the structure?" It does NOT
answer "does the structure predict better?" — and it surfaced a real risk: the
pilot agents were overconfident (0.9 vs a true 0.7). A combinatorial market
faithfully propagates whatever agents feed it, INCLUDING a shared bias, so
coherence could amplify a systematic agent error and end up worse than flat.
This stage measures the outcome that matters.

Design:
  - A mixed agent population. MARGINAL signals (about P(A), P(B), P(C)) go to
    BOTH markets. RELATIONAL signals (about P(B|A), P(C|A)) are usable ONLY by
    the combinatorial market — the flat market structurally drops them.
  - Signals are QUANTITATIVE and noisy (centered on truth) so a faithful
    population's aggregate can converge to truth; this isolates the market's
    aggregation from the qualitative-language interpretation effect the pilot
    found separately.
  - The market aggregates by damped LMSR moves over many rounds (a bounded
    trade each pass): the price of each quantity converges to the mean of the
    noisy targets aimed at it.
  - Score: KL(true joint || market joint) and mean conditional error, flat vs
    combinatorial. The flat market receives the same agent decisions; its
    structure simply cannot apply the conditional ones (the charitable
    baseline — flat is not misled, it just can't use relational info).

The agent decisions (JSON action arrays) are elicited once each by the
orchestrator from the prompts this module emits, then replayed here.

    PYTHONPATH=. python3 scripts/experiments/stage1b_market_sim.py --prompts
    PYTHONPATH=. python3 scripts/experiments/stage1b_market_sim.py --score decisions.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys

from scripts.experiments.stage1_agents import (
    BN, VARS, TOPO, QUESTIONS, YES, NO, OUTCOMES,
    build_market, TRUE, comb_joint_prob, kl_true_vs_market, parse_agent_json,
)

SEED = 20260715


def true_marginal(var: str) -> float:
    i = VARS.index(var)
    return sum(p for bits, p in TRUE.items() if bits[i] == 1)


def true_conditional(child: str, parent: str, pv: int) -> float:
    ci, pi = VARS.index(child), VARS.index(parent)
    num = sum(p for b, p in TRUE.items() if b[pi] == pv and b[ci] == 1)
    den = sum(p for b, p in TRUE.items() if b[pi] == pv)
    return num / den if den else 0.5


def _pct(x: float) -> int:
    return round(max(2, min(98, x)) )


def build_signal_prompts(seed: int = SEED) -> list[dict]:
    """The mixed noisy population. 2 agents per quantity."""
    rng = random.Random(seed)
    noise = 0.06
    specs: list[dict] = []

    def marg_prompt(var: str, est: float) -> str:
        return (f"You are a prediction-market trader. Do NOT use tools — reason "
                f"and reply with ONLY a JSON array of actions.\n\n"
                f"Questions (current price 50% each):\n"
                + "\n".join(f"  [{k}] {QUESTIONS[k]}" for k in VARS)
                + "\n\nActions (use whichever fits your evidence):\n"
                f'  {{"action":"set_marginal","question":"<A|B|C>","probability":<0-1>}}\n'
                f'  {{"action":"set_conditional","question":"<A|B|C>",'
                f'"given":{{"question":"<A|B|C>","outcome":"yes|no"}},"probability":<0-1>}}\n\n'
                f"Your private evidence: your data estimates the probability of "
                f"question {var} at about {_pct(est*100)}%. You have no information "
                f"relating it to the other questions.\n\n"
                f"Return ONLY the JSON array.")

    def cond_prompt(child: str, parent: str, e_yes: float, e_no: float) -> str:
        return (f"You are a prediction-market trader. Do NOT use tools — reason "
                f"and reply with ONLY a JSON array of actions.\n\n"
                f"Questions (current price 50% each):\n"
                + "\n".join(f"  [{k}] {QUESTIONS[k]}" for k in VARS)
                + "\n\nActions (use whichever fits your evidence):\n"
                f'  {{"action":"set_marginal","question":"<A|B|C>","probability":<0-1>}}\n'
                f'  {{"action":"set_conditional","question":"<A|B|C>",'
                f'"given":{{"question":"<A|B|C>","outcome":"yes|no"}},"probability":<0-1>}}\n\n'
                f"Your private evidence: your data estimates that {child} happens "
                f"about {_pct(e_yes*100)}% of the time when {parent} is true (yes), "
                f"and about {_pct(e_no*100)}% of the time when {parent} is false (no).\n\n"
                f"Return ONLY the JSON array.")

    idx = 0
    for var in VARS:  # marginal signals, both markets, 2 agents each
        tm = true_marginal(var)
        for _ in range(2):
            est = tm + rng.gauss(0, noise)
            specs.append({"id": f"marg_{var}_{idx}", "class": "marginal",
                          "prompt": marg_prompt(var, est)})
            idx += 1
    for child in ("B", "C"):  # relational signals, comb only, 2 agents each
        parent = BN[child]["parents"][0]
        cy, cn = true_conditional(child, parent, 1), true_conditional(child, parent, 0)
        for _ in range(2):
            ey = cy + rng.gauss(0, noise)
            en = cn + rng.gauss(0, noise)
            specs.append({"id": f"cond_{child}_{idx}", "class": "relational",
                          "prompt": cond_prompt(child, parent, ey, en)})
            idx += 1
    return specs


# --- damped aggregation ----------------------------------------------------

def _apply_damped(market, actions, combinatorial, alpha):
    for act in actions:
        kind, q = act.get("action"), act.get("question")
        try:
            p = float(act.get("probability"))
        except (TypeError, ValueError):
            continue
        if q not in VARS:
            continue
        if kind == "set_marginal":
            cur = market.marginal(q, {})[YES]
            market.trade_to_probability(q, YES, _clip(cur + alpha * (p - cur)))
        elif kind == "set_conditional" and combinatorial:
            g = act.get("given", {})
            gq, go = g.get("question"), g.get("outcome")
            if gq in VARS and go in OUTCOMES:
                cur = market.marginal(q, {gq: go})[YES]
                market.trade_to_probability(q, YES, _clip(cur + alpha * (p - cur)),
                                            context={gq: go})


def _clip(x, lo=0.02, hi=0.98):
    return max(lo, min(hi, x))


def run_market(decisions, combinatorial, rounds=40, alpha=0.2, seed=SEED):
    market = build_market(combinatorial)
    rng = random.Random(seed)
    order = list(range(len(decisions)))
    for _ in range(rounds):
        rng.shuffle(order)
        for i in order:
            _apply_damped(market, decisions[i], combinatorial, alpha)
    return market


def mean_cond_error(m, combinatorial):
    errs = []
    for child, spec in BN.items():
        for parent in spec["parents"]:
            for pv in (0, 1):
                t = true_conditional(child, parent, pv)
                got = (m.marginal(child, {parent: (YES if pv else NO)})[YES]
                       if combinatorial else m.marginal(child, {})[YES])
                errs.append(abs(got - t))
    return sum(errs) / len(errs)


def score(decisions):
    flat = run_market(decisions, combinatorial=False)
    comb = run_market(decisions, combinatorial=True)
    return {
        "kl_flat": kl_true_vs_market(flat),
        "kl_comb": kl_true_vs_market(comb),
        "conderr_flat": mean_cond_error(flat, False),
        "conderr_comb": mean_cond_error(comb, True),
        "marg_flat": {v: round(flat.marginal(v, {})[YES], 3) for v in VARS},
        "marg_comb": {v: round(comb.marginal(v, {})[YES], 3) for v in VARS},
        "true_marg": {v: round(true_marginal(v), 3) for v in VARS},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", action="store_true", help="emit agent prompts as JSON")
    ap.add_argument("--score", metavar="FILE",
                    help="score a JSON list of agent decision arrays")
    args = ap.parse_args()

    if args.prompts:
        specs = build_signal_prompts()
        print(json.dumps([{"id": s["id"], "class": s["class"], "prompt": s["prompt"]}
                          for s in specs], indent=1))
        return
    if args.score:
        raw = json.load(open(args.score))
        decisions = [d if isinstance(d, list) else parse_agent_json(d) for d in raw]
        r = score(decisions)
        print(f"agents: {len(decisions)}")
        print(f"true marginals:  {r['true_marg']}")
        print(f"flat marginals:  {r['marg_flat']}")
        print(f"comb marginals:  {r['marg_comb']}")
        print()
        print(f"KL(true||flat) = {r['kl_flat']:.4f}   condErr flat = {r['conderr_flat']:.3f}")
        print(f"KL(true||comb) = {r['kl_comb']:.4f}   condErr comb = {r['conderr_comb']:.3f}")
        print(f"KL improvement (flat-comb) = {r['kl_flat']-r['kl_comb']:+.4f}")
        return
    ap.print_help(sys.stderr)


if __name__ == "__main__":
    main()
