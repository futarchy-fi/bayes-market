#!/usr/bin/env python3
"""Stage 1: do LLM agents SPONTANEOUSLY use conditional (relational) trades?

The SciCast finding was that humans underused the combinatorial capability —
the expressivity was there, but people traded marginals. The one thing new
since 2013 is AI agents as traders. This stage tests the crux: given
relational evidence and a NEUTRAL interface that offers marginal and
conditional trades with equal framing, does an LLM agent reach for the
conditional trade?

This module is the deterministic harness: the AI-themed synthetic BN (so we
still have ground truth), the neutral prompt generator, a decision parser that
applies an agent's chosen actions to the real FactoredMarket, and the scorer
(usage rate + KL against truth). The agent calls themselves are run by the
orchestrator and their JSON decisions fed back here.

Neutrality is the whole validity of the experiment: both action types are
presented with identical framing and the evidence — not the prompt — is what
should drive the choice. A marginal-evidence control group checks the agent
does NOT over-reach for conditionals when the evidence is non-relational.
"""

from __future__ import annotations

import itertools
import json
import math

from backend.inference.factored_market import FactoredMarket

YES, NO = "yes", "no"
OUTCOMES = (YES, NO)

QUESTIONS = {
    "A": "A major AI capability jump (an autonomous AI-R&D milestone) occurs in 2027.",
    "B": "Significant new binding AI regulation passes in a major jurisdiction in 2028.",
    "C": "New compute export controls are enacted in 2027.",
}

# Ground-truth BN: regulation (B) and export controls (C) are both driven by a
# capability jump (A). Real conditional structure = real relational info.
BN = {
    "A": {"parents": (), "cpt": {(): 0.50}},
    "B": {"parents": ("A",), "cpt": {(1,): 0.70, (0,): 0.15}},
    "C": {"parents": ("A",), "cpt": {(1,): 0.55, (0,): 0.25}},
}
VARS = ["A", "B", "C"]
TOPO = ["A", "B", "C"]

# The private signals handed to trader agents (natural language, no interface
# steering). Relational signals describe a dependence; the marginal signal a
# level. The "expected" field is only for scoring, never shown to the agent.
SIGNALS = {
    "relational_B": {
        "text": ("Your research shows binding AI regulation almost always follows "
                 "within a year of a major capability jump, and is rare when no "
                 "such jump happens. The jump is the driver."),
        "expected": "conditional",  # B given A
    },
    "relational_C": {
        "text": ("Your analysis indicates compute export controls are tied to "
                 "capability jumps: a jump makes controls somewhat more likely, "
                 "and without a jump they are less likely."),
        "expected": "conditional",  # C given A
    },
    "marginal_A": {
        "text": ("Your forecasting model puts the probability of a major AI "
                 "capability jump in 2027 at about 60 percent. You have no "
                 "information about how it relates to other questions."),
        "expected": "marginal",  # A
    },
}


def build_prompt(signal_key: str, prices: dict[str, float]) -> str:
    q_lines = "\n".join(
        f"  [{k}] {QUESTIONS[k]}  (current market price: {round(prices[k]*100)}%)"
        for k in VARS
    )
    return f"""You are trading in a prediction market on these AI-related \
yes/no questions. The current price is the market's probability the question \
resolves YES.

Questions:
{q_lines}

You may trade in either of two ways — use whichever best expresses your evidence:
  1. Set the probability of a question:
     {{"action": "set_marginal", "question": "<A|B|C>", "probability": <0.0-1.0>}}
  2. Set the probability of a question conditional on another question's outcome:
     {{"action": "set_conditional", "question": "<A|B|C>",
       "given": {{"question": "<A|B|C>", "outcome": "yes|no"}}, "probability": <0.0-1.0>}}

Your private evidence:
  {SIGNALS[signal_key]['text']}

Make the trade or trades that best express this evidence to maximize your \
score — you profit when the market moves toward the truth in the direction \
your evidence supports. Return ONLY a JSON array of action objects and nothing \
else."""


# --- ground truth ----------------------------------------------------------

def _p_yes(var, assign):
    return BN[var]["cpt"][tuple(assign[p] for p in BN[var]["parents"])]


def true_joint():
    joint = {}
    for bits in itertools.product((0, 1), repeat=len(VARS)):
        a = dict(zip(VARS, bits))
        p = 1.0
        for v in VARS:
            py = _p_yes(v, a)
            p *= py if a[v] == 1 else (1 - py)
        joint[bits] = p
    return joint


TRUE = true_joint()


# --- market + decision application -----------------------------------------

def _node(var, parents):
    if not parents:
        return {"variable_id": var, "outcomes": OUTCOMES, "parents": (),
                "rows": {frozenset(): {YES: 0.5, NO: 0.5}}}
    rows = {frozenset(zip(parents, combo)): {YES: 0.5, NO: 0.5}
            for combo in itertools.product(OUTCOMES, repeat=len(parents))}
    return {"variable_id": var, "outcomes": OUTCOMES,
            "parents": tuple(sorted(parents)), "rows": rows}


def build_market(combinatorial: bool, liquidity: float = 100.0) -> FactoredMarket:
    nodes = [_node(v, BN[v]["parents"] if combinatorial else ()) for v in VARS]
    return FactoredMarket.from_nodes(nodes, liquidity, max_width=4)


def classify_and_apply(market: FactoredMarket, actions: list, combinatorial: bool):
    """Apply an agent's actions; return which action types it actually used."""
    used = set()
    for act in actions:
        kind = act.get("action")
        q = act.get("question")
        p = float(act.get("probability"))
        p = min(0.98, max(0.02, p))
        if kind == "set_marginal" and q in VARS:
            used.add("marginal")
            market.trade_to_probability(q, YES, p)
        elif kind == "set_conditional" and q in VARS and combinatorial:
            given = act.get("given", {})
            gq, go = given.get("question"), given.get("outcome")
            if gq in VARS and go in OUTCOMES:
                used.add("conditional")
                market.trade_to_probability(q, YES, p, context={gq: go})
    return used


# --- scoring ---------------------------------------------------------------

def comb_joint_prob(m, bits):
    a = dict(zip(VARS, bits))
    p = 1.0
    for v in TOPO:
        ctx = {par: (YES if a[par] == 1 else NO) for par in BN[v]["parents"]}
        py = m.marginal(v, ctx)[YES]
        p *= py if a[v] == 1 else (1 - py)
    return p


def kl_true_vs_market(m):
    total = 0.0
    for bits, pt in TRUE.items():
        if pt <= 0:
            continue
        pm = max(comb_joint_prob(m, bits), 1e-12)
        total += pt * math.log(pt / pm)
    return total


def parse_agent_json(text: str) -> list:
    """Extract the JSON array from an agent's reply (tolerates code fences)."""
    s = text.strip()
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array found in agent reply")
    return json.loads(s[start:end + 1])


if __name__ == "__main__":
    # Print the neutral prompts so the exact agent inputs are on record.
    flat_prices = {k: 0.5 for k in VARS}
    for key in SIGNALS:
        print("=" * 70)
        print(f"SIGNAL: {key}  (expected: {SIGNALS[key]['expected']})")
        print("=" * 70)
        print(build_prompt(key, flat_prices))
        print()
