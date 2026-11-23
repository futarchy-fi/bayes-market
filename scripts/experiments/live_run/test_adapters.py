#!/usr/bin/env python3
"""Invariants the comb-vs-flat comparison rests on. Run before any live run.

    PYTHONPATH=. python3 scripts/experiments/live_run/test_adapters.py
"""

from __future__ import annotations

import itertools
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import signal_design as sig      # noqa: E402
import score_run as sr           # noqa: E402

PI0 = {"AGI41": 0.431, "GOODS39": 0.577, "GOODS40": 0.626, "RND": 0.426}
ORDER = list(PI0)
DRIVER, CHILD = "AGI41", "GOODS39"
OK = "ok"


def t_marginal_preserving():
    """The relational signal must not move the margin it is rendered against —
    otherwise the 'purely relational' treatment leaks into the flat arm."""
    worst = 0.0
    for pa in (0.1, 0.3, 0.5, 0.7, 0.9):
        for pg in (0.15, 0.4, 0.6, 0.85):
            for orr in (1.5, 4.0, 12.0):
                gy, gn = sig.conditional_pair(pa, pg, orr)
                worst = max(worst, abs(pa * gy + (1 - pa) * gn - pg),
                            abs(sig.odds_ratio_of(gy, gn) - orr) / orr)
    assert worst < 1e-9, worst
    return f"{OK} (max deviation {worst:.2e} over 60 cases)"


def t_reexpress_preserves_or():
    """Re-rendering at new margins keeps the association and hits the new
    margin exactly — this is what makes the conditional adapter honest."""
    gy, gn = sig.conditional_pair(0.431, 0.577, 4.0)
    worst = 0.0
    for pa in (0.2, 0.34, 0.5, 0.8):
        for pg in (0.25, 0.48, 0.7):
            gy2, gn2 = sig.reexpress_at(gy, gn, pa, pg)
            worst = max(worst, abs(sig.odds_ratio_of(gy2, gn2) - 4.0) / 4.0,
                        abs(pa * gy2 + (1 - pa) * gn2 - pg))
    assert worst < 1e-9, worst
    return f"{OK} (max deviation {worst:.2e})"


def t_marginal_adapter_commutes():
    """Log-odds increments commute, so the flat arm must be EXACTLY invariant
    to arrival order. Without the adapter this is last-writer-wins."""
    dec = {"a": [{"action": "set_marginal", "question": "AGI41", "probability": 0.53}],
           "b": [{"action": "set_marginal", "question": "AGI41", "probability": 0.34}],
           "c": [{"action": "set_marginal", "question": "AGI41", "probability": 0.34}],
           "d": [{"action": "set_marginal", "question": "GOODS39", "probability": 0.67}]}
    seen = set()
    for perm in itertools.permutations(dec):
        _, f = sr.build_arms(PI0, ORDER, DRIVER, CHILD)
        for k in perm:
            sr.apply_decision(f, dec[k], "flat", adapter=True, shown_prices=PI0)
        seen.add(tuple(round(f.marginal(v)["yes"], 10) for v in ORDER))
    assert len(seen) == 1, f"flat arm not order-invariant: {len(seen)} outcomes"
    return f"{OK} (all {math.factorial(len(dec))} orders identical)"


def t_no_adapter_is_last_writer_wins():
    """The defect this all exists to fix, pinned as a regression test: without
    the adapter the final price is simply the last trader's number."""
    dec = {"a": [{"action": "set_marginal", "question": "AGI41", "probability": 0.53}],
           "b": [{"action": "set_marginal", "question": "AGI41", "probability": 0.34}]}
    outs = []
    for perm in (("a", "b"), ("b", "a")):
        _, f = sr.build_arms(PI0, ORDER, DRIVER, CHILD)
        for k in perm:
            sr.apply_decision(f, dec[k], "flat", adapter=False, shown_prices=PI0)
        outs.append(round(f.marginal("AGI41")["yes"], 4))
    assert outs == [0.34, 0.53], outs
    return f"{OK} (order-dependent as expected: {outs})"


def t_flat_cannot_express_dependence():
    """The representational limit under test: a conditional order applied to
    the flat arm must leave it with zero dependence."""
    dec = [{"action": "set_conditional", "question": CHILD,
            "given": {"question": DRIVER, "outcome": o}, "probability": p}
           for o, p in (("yes", 0.76), ("no", 0.44))]
    _, f = sr.build_arms(PI0, ORDER, DRIVER, CHILD)
    sr.apply_decision(f, dec, "flat", adapter=True, shown_prices=PI0)
    gy = f.marginal(CHILD, {DRIVER: "yes"})["yes"]
    gn = f.marginal(CHILD, {DRIVER: "no"})["yes"]
    assert abs(gy - gn) < 1e-12, (gy, gn)
    return f"{OK} (gy - gn = {gy - gn:.2e})"


def t_arms_start_identical():
    """Both arms must begin at the same frozen prior; a head start would be a
    confound rather than a representation effect."""
    c, f = sr.build_arms(PI0, ORDER, DRIVER, CHILD)
    worst = max(abs(c.marginal(v)["yes"] - f.marginal(v)["yes"]) for v in ORDER)
    assert worst < 1e-12, worst
    return f"{OK} (max marginal gap {worst:.2e})"


def t_target_is_normalized():
    pre = sig.preregister(
        {"marginal_agents": [{"n": 3, "question": "AGI41"},
                             {"n": 3, "question": "GOODS39"}],
         "relational_agents": [{"n": 3}]}, seed=20260728)
    tgt = sig.full_information_target(pre, PI0, ORDER)
    tj = sig.target_joint(tgt, ORDER)
    assert abs(sum(tj.values()) - 1.0) < 1e-12, sum(tj.values())
    assert all(p > 0 for p in tj.values())
    return f"{OK} (sums to 1, {len(tj)} states, all positive)"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_")]
    fails = 0
    for t in tests:
        try:
            print(f"  {t.__name__:34} {t()}")
        except AssertionError as exc:
            fails += 1
            print(f"  {t.__name__:34} FAIL: {exc}")
    print(f"\n{len(tests) - fails}/{len(tests)} passed")
    sys.exit(1 if fails else 0)
