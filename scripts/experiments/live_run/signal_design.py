#!/usr/bin/env python3
"""Pre-registered private signals for the live comb-vs-flat run.

WHY THIS EXISTS. The first cut of `agent_briefs` filled each marginal agent's
brief with the *current live price* ("your models put P(AGI) around 43%" while
the same prompt showed "current price: 43%"). Under a strictly proper LMSR a
trader whose belief equals the price maximizes expected score by not trading at
all -- moving the price to q earns -b*KL(p||q) < 0 -- so all six marginal
agents were no-ops, the flat arm received no information, and the advertised
"marginal baseline usable by both arms" did not exist. Two independent
adversarial reviews confirmed this and prescribed the design below.

THE DESIGN.

1. Pre-registration BEFORE any live price is observed. `preregister()` derives
   the per-agent sign vector from a seed and writes it with a SHA-256 digest;
   nothing here reads the exchange. The live snapshot only enters later, as the
   frozen common prior both arms start from.

2. Marginal signals as likelihood-ratio shifts on the frozen prior pi0:

       logit(r_i) = logit(pi0_q) + s_i * delta,     s_i in {-1, +1}

   with delta = log(alpha / (1 - alpha)) for a pre-registered signal accuracy
   alpha (default 0.60 -> delta = log 1.5). This is an *informative* signal at
   a controlled strength, and it is the same object in both arms.

3. The relational signal is MARGINAL-PRESERVING. A bare "P(G|A) is high" is not
   purely relational: combined with P(A) it moves P(G), which the flat arm can
   trade, so the treatment would leak into the marginals. Instead we solve for
   the conditional pair (gy, gn) that carries a pre-registered odds ratio while
   reproducing the prior marginal exactly:

       p_A*gy + (1 - p_A)*gn = p_G        (marginal preserved)
       odds(gy) / odds(gn)   = OR         (the dependence being injected)

   So the relational agents add dependence and nothing else.

4. A computable scoring target. `full_information_target()` returns the joint
   implied by pooling every pre-registered signal against pi0 -- the benchmark
   both arms are scored against, fixed before the run rather than argued for
   afterwards.

FROZEN SEMANTICS (decided 2026-08-01 after the second review round; the panel
showed the design was ambiguous between two coherent experiments and that the
target already implied the second one, while the agent brief was written for
the first). This experiment is:

    MARGINS-PLUS-ASSOCIATION (modular).
    The marginal agents jointly determine the two margins. The relational
    agents supply ONLY an association -- the odds ratio -- carrying no
    independent information about either margin. The full-information target
    is the unique 2x2 joint with the pooled margins and that odds ratio.

Two consequences, both mechanical rather than discretionary:

  * The relational BRIEF is stated as an odds ratio, and says in words that it
    contains no view on either level.
  * `(gy, gn)` is only ever a *rendering* of that odds ratio at some margin.
    A rendering computed at pi0 is stale once the marginal agents have moved
    the price, so the runner re-renders it at the execution-state margins
    (`reexpress_at`). This adapter is pre-registered and applied to EVERY
    order in EVERY arm, so it cannot be tuned per run -- the earlier one-off
    "in-situ" recomputation was a post-hoc oracle check and is explicitly not
    the headline.

The alternative semantics (fixed likelihood relative to pi0, target
proportional to pi0 * prod_k L_k) is a legitimate different experiment and is
NOT what this file implements.

Offline, deterministic, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field

OUT = ("yes", "no")


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def delta_for_accuracy(alpha: float) -> float:
    """Log-likelihood-ratio shift of a binary signal with accuracy alpha."""
    if not 0.5 < alpha < 1.0:
        raise ValueError("signal accuracy must lie in (0.5, 1.0)")
    return math.log(alpha / (1.0 - alpha))


# ---- pre-registration -------------------------------------------------------


@dataclass
class Preregistration:
    """Everything fixed before a single live price is read."""
    seed: int
    accuracy: float
    odds_ratio: float
    marginal_agents: list[dict]      # {id, question, sign}
    relational_agents: list[dict]    # {id, driver, child}
    replicate: int = 0

    @property
    def delta(self) -> float:
        return delta_for_accuracy(self.accuracy)

    def to_dict(self) -> dict:
        return {"seed": self.seed, "replicate": self.replicate,
                "accuracy": self.accuracy, "delta": self.delta,
                "odds_ratio": self.odds_ratio,
                "marginal_agents": self.marginal_agents,
                "relational_agents": self.relational_agents}

    def digest(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def preregister(design: dict, seed: int, replicate: int = 0,
                accuracy: float = 0.60, odds_ratio: float = 4.0
                ) -> Preregistration:
    """Draw the sign vector for one replicate. Signs are balanced within each
    question group where the group size is even, so a replicate does not
    smuggle in a net directional push; across replicates the residual signs
    are re-drawn, which is what the reviewer asked for instead of forcing every
    single run to be exactly sign-neutral."""
    rng = random.Random((seed << 8) ^ replicate)
    marginals: list[dict] = []
    idx = 0
    for grp in design.get("marginal_agents", []):
        n = grp["n"]
        signs = [1] * (n // 2) + [-1] * (n // 2)
        if n % 2:
            signs.append(rng.choice((1, -1)))
        rng.shuffle(signs)
        for s in signs:
            marginals.append({"id": f"marg{idx}", "question": grp["question"],
                              "sign": s})
            idx += 1
    relationals: list[dict] = []
    for grp in design.get("relational_agents", []):
        for _ in range(grp["n"]):
            relationals.append({"id": f"rel{idx}",
                                "driver": grp.get("driver", "AGI41"),
                                "child": grp.get("child", "GOODS39")})
            idx += 1
    return Preregistration(seed=seed, accuracy=accuracy, odds_ratio=odds_ratio,
                           marginal_agents=marginals,
                           relational_agents=relationals, replicate=replicate)


# ---- signal realization against a frozen prior ------------------------------


def marginal_belief(pi0_q: float, sign: int, delta: float) -> float:
    """The agent's posterior after its private signal, on the frozen prior."""
    return expit(logit(pi0_q) + sign * delta)


def conditional_pair(p_driver: float, p_child: float,
                     odds_ratio: float) -> tuple[float, float]:
    """(gy, gn) = (P(child|driver=yes), P(child|driver=no)) carrying
    `odds_ratio` while preserving the prior marginal p_child exactly.

    Solves p_driver*gy + (1-p_driver)*gn = p_child with
    odds(gy)/odds(gn) = odds_ratio. The mixture is strictly increasing in gn,
    so bisection on gn in (0, p_child) is exact to machine precision."""
    if odds_ratio <= 1.0:
        raise ValueError("odds_ratio must exceed 1 (driver raises the child)")
    p_driver = min(max(p_driver, 1e-6), 1 - 1e-6)
    p_child = min(max(p_child, 1e-6), 1 - 1e-6)

    def gy_of(gn: float) -> float:
        o = odds_ratio * (gn / (1 - gn))
        return o / (1 + o)

    def mixture(gn: float) -> float:
        return p_driver * gy_of(gn) + (1 - p_driver) * gn

    lo, hi = 1e-12, p_child      # mixture(p_child) > p_child since gy > gn
    for _ in range(200):
        mid = (lo + hi) / 2
        if mixture(mid) < p_child:
            lo = mid
        else:
            hi = mid
    gn = (lo + hi) / 2
    return gy_of(gn), gn


def realize(prereg: Preregistration, pi0: dict[str, float]) -> list[dict]:
    """Turn the pre-registration into concrete per-agent beliefs, given the
    frozen prior snapshot pi0. This is the only place live numbers enter."""
    out: list[dict] = []
    d = prereg.delta
    for a in prereg.marginal_agents:
        q = a["question"]
        out.append({"id": a["id"], "class": "marginal", "question": q,
                    "sign": a["sign"], "accuracy": prereg.accuracy,
                    "delta": d,
                    "belief": marginal_belief(pi0[q], a["sign"], d),
                    "prior": pi0[q]})
    for a in prereg.relational_agents:
        gy, gn = conditional_pair(pi0[a["driver"]], pi0[a["child"]],
                                  prereg.odds_ratio)
        out.append({"id": a["id"], "class": "relational",
                    "driver": a["driver"], "child": a["child"],
                    "g_given_yes": gy, "g_given_no": gn,
                    "implied_marginal": pi0[a["child"]],
                    "odds_ratio": prereg.odds_ratio})
    return out


# ---- the pre-registered scoring target --------------------------------------


def full_information_target(prereg: Preregistration, pi0: dict[str, float],
                            questions: list[str]) -> dict:
    """Joint implied by pooling EVERY signal against the frozen prior.

    Marginals: independent likelihood-ratio evidence adds in log-odds, so a
    question receiving signs s_1..s_k lands at logit(pi0) + delta*sum(s_i).
    Dependence: the relational agents' odds ratio, applied once (they share one
    signal, so it is not counted three times), marginal-preserving at the
    POOLED child marginal. Untouched questions stay at the prior."""
    d = prereg.delta
    marg = dict(pi0)
    for a in prereg.marginal_agents:
        q = a["question"]
        marg[q] = expit(logit(marg[q]) + a["sign"] * d)
    target = {"marginals": {q: marg.get(q, pi0.get(q, 0.5)) for q in questions},
              "conditionals": {}}
    for a in prereg.relational_agents[:1]:      # one shared relational signal
        gy, gn = conditional_pair(marg[a["driver"]], marg[a["child"]],
                                  prereg.odds_ratio)
        target["conditionals"][f"{a['child']}|{a['driver']}"] = {
            "yes": gy, "no": gn}
    return target


def target_joint(target: dict, order: list[str]) -> dict[tuple, float]:
    """Expand the target into a full joint over `order` (4 binary vars), with
    the single conditional edge applied and everything else independent."""
    marg = target["marginals"]
    cond = target["conditionals"]
    edge = next(iter(cond.items()), None)
    child = driver = None
    if edge is not None:
        child, driver = edge[0].split("|")
    out: dict[tuple, float] = {}
    for bits in range(1 << len(order)):
        assign = {v: (OUT[(bits >> i) & 1]) for i, v in enumerate(order)}
        p = 1.0
        for v in order:
            yes = assign[v] == "yes"
            if v == child and edge is not None:
                row = cond[edge[0]]
                pv = row["yes"] if assign[driver] == "yes" else row["no"]
            else:
                pv = marg[v]
            p *= pv if yes else (1 - pv)
        out[tuple(assign[v] for v in order)] = p
    return out


# ---- brief rendering (anti-anchoring wording) -------------------------------


MARGINAL_BRIEF = (
    "You hold one piece of private EVIDENCE about this question, and nothing "
    "else. Your evidence is a signal of accuracy {accuracy}% that came out "
    "{direction} for: {title}. It is independent evidence to be COMBINED with "
    "what the market already knows — not a finished forecast that replaces the "
    "market price. Starting from the current price and updating on your signal "
    "gives about {belief}%. You have no information about how this question "
    "relates to any other.")

RELATIONAL_BRIEF = (
    "Your research is about the DEPENDENCE between two questions, and about "
    "nothing else. You have found that {child_title} is gated by "
    "{driver_title}: the ODDS of the dependent question are {odds_ratio}x "
    "higher when the driver happens than when it does not. You have NO private "
    "view on the overall level of either question — your estimate of each "
    "question's own probability is exactly the market's current price, and "
    "your entire edge is the {odds_ratio}x relationship. At the current "
    "prices that association corresponds to about {gy}% conditional on the "
    "driver happening and about {gn}% conditional on it not happening; if the "
    "prices have moved, keep the {odds_ratio}x odds ratio, not these two "
    "numbers.")


# ---- execution adapter ------------------------------------------------------


def odds_ratio_of(gy: float, gn: float) -> float:
    gy = min(max(gy, 1e-9), 1 - 1e-9)
    gn = min(max(gn, 1e-9), 1 - 1e-9)
    return (gy / (1 - gy)) / (gn / (1 - gn))


def reexpress_at(gy: float, gn: float, cur_driver: float,
                 cur_child: float) -> tuple[float, float]:
    """Re-render a stated conditional pair at the CURRENT margins, preserving
    the association it carries.

    Under the frozen margins-plus-association semantics, `(gy, gn)` is only a
    rendering of an odds ratio at whatever margin held when it was computed.
    Once other agents move the price, the same pair no longer carries "pure
    association" -- it silently asserts a marginal too. The runner therefore
    extracts the odds ratio and re-renders it against the live margins before
    every conditional trade.

    Pre-registered and mechanical: applied to every conditional order, in every
    arm, in every trade order. It cannot be tuned per run."""
    return conditional_pair(cur_driver, cur_child, odds_ratio_of(gy, gn))


def render_briefs(realized: list[dict], titles: dict[str, str],
                  pi0: dict[str, float]) -> list[dict]:
    briefs = []
    for r in realized:
        if r["class"] == "marginal":
            info = MARGINAL_BRIEF.format(
                title=titles[r["question"]],
                accuracy=round(r.get("accuracy", 0.60) * 100),
                direction="YES" if r["sign"] > 0 else "NO",
                belief=round(r["belief"] * 100))
        else:
            info = RELATIONAL_BRIEF.format(
                child_title=titles[r["child"]],
                driver_title=titles[r["driver"]],
                odds_ratio=round(r["odds_ratio"], 1),
                gy=round(r["g_given_yes"] * 100),
                gn=round(r["g_given_no"] * 100))
        briefs.append({"id": r["id"], "class": r["class"], "info": info,
                       "allow_conditional": True})
    return briefs


if __name__ == "__main__":       # tiny self-check
    pre = preregister({"marginal_agents": [{"n": 3, "question": "AGI41"},
                                           {"n": 3, "question": "GOODS39"}],
                       "relational_agents": [{"n": 3}]}, seed=20260728)
    pi0 = {"AGI41": 0.43, "GOODS39": 0.58, "GOODS40": 0.63, "RND": 0.43}
    real = realize(pre, pi0)
    gy, gn = conditional_pair(pi0["AGI41"], pi0["GOODS39"], 4.0)
    mix = pi0["AGI41"] * gy + (1 - pi0["AGI41"]) * gn
    print(f"delta={pre.delta:.4f} digest={pre.digest()}")
    print(f"marginal beliefs: "
          f"{[round(r['belief'], 3) for r in real if r['class'] == 'marginal']}")
    print(f"relational: gy={gy:.4f} gn={gn:.4f}  mixture={mix:.6f} "
          f"(prior {pi0['GOODS39']}) -> marginal preserved: "
          f"{abs(mix - pi0['GOODS39']) < 1e-9}")
