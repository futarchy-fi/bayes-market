#!/usr/bin/env python3
"""Apply curated bridge CPTs: externals become children of FTM variables.

Bridges connect externally-anchored root markets (x####) into the FTM net so
trades propagate. Each bridged external stays a LEAF (parents are FTM vars,
externals are never parents), so its CPT can be recalibrated in isolation:
a single logit shift, solved by bisection against the parent-context
distribution of the real factored net, pins the implied marginal to the
external's anchored seed price exactly. The calibrator bot keeps anchoring
the marginal afterwards; the bridge only reshapes conditional structure.

Run on farol from ~/bayes-market:
  python3 scratch/apply_bridges.py \
      --proposals /tmp/bridge_proposals.json \
      --seeds backend/seeds_takeoff.json \
      --report /tmp/bridge_report.json [--dry-run]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bayes-market"))
sys.path.insert(0, ".")

from backend.inference.factored_market import FactoredMarket, JointMarketError
from backend.inference.network_model import build_network_nodes

WIDTH_BUDGET = 8
LIQUIDITY = 10000.0
ROW_CLAMP = (0.02, 0.98)
MAX_PARENTS = 2
MIN_STRENGTH = 3


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def clamp_row(p: float) -> float:
    return min(max(float(p), ROW_CLAMP[0]), ROW_CLAMP[1])


def assignments(parents: list[str]) -> list[dict[str, str]]:
    combos: list[dict[str, str]] = [{}]
    for p in parents:
        combos = [dict(c, **{p: o}) for c in combos for o in ("yes", "no")]
    return combos


def row_key(assign: dict[str, str], parents: list[str]) -> str:
    return "|".join(f"{p}={assign[p]}" for p in parents)


def parse_proposal_cpt(raw_cpt: dict, parents: list[str]) -> dict[str, float] | None:
    """Normalize proposal CPT keys to sorted-parent order; None if incomplete."""
    parsed: dict[frozenset, float] = {}
    for key, p_yes in raw_cpt.items():
        pairs = []
        for part in str(key).split("|"):
            if "=" not in part:
                return None
            var, _, outcome = part.partition("=")
            pairs.append((var.strip(), outcome.strip()))
        parsed[frozenset(pairs)] = clamp_row(p_yes)
    rows: dict[str, float] = {}
    for assign in assignments(parents):
        fs = frozenset(assign.items())
        if fs not in parsed:
            return None
        rows[row_key(assign, parents)] = parsed[fs]
    return rows


def parent_context_dist(fm: FactoredMarket, parents: list[str]) -> list[tuple[dict, float]] | None:
    """Joint distribution over parent assignments, from the live net (chain rule)."""
    out = []
    for assign in assignments(parents):
        prob, evidence = 1.0, {}
        for p in parents:
            m = fm.marginal(p, evidence=evidence or None)
            if m is None:
                return None
            prob *= m.get(assign[p], 0.0)
            evidence[p] = assign[p]
        out.append((assign, prob))
    return out


def calibrate_leaf(rows: dict[str, float], parents: list[str],
                   dist: list[tuple[dict, float]], target: float) -> dict[str, float] | None:
    """Solve logit shift delta so implied marginal == target; None if infeasible."""

    def implied(delta: float) -> float:
        return sum(
            prob * sigmoid(logit(rows[row_key(assign, parents)]) + delta)
            for assign, prob in dist
        )

    lo, hi = -14.0, 14.0
    f_lo, f_hi = implied(lo) - target, implied(hi) - target
    if f_lo > 0 or f_hi < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if implied(mid) - target > 0:
            hi = mid
        else:
            lo = mid
    delta = (lo + hi) / 2.0
    return {k: sigmoid(logit(v) + delta) for k, v in rows.items()}


def build(markets: dict, conditionals: dict) -> FactoredMarket:
    nodes = build_network_nodes(markets, conditionals)
    return FactoredMarket.from_nodes(nodes, LIQUIDITY, WIDTH_BUDGET)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposals", required=True)
    ap.add_argument("--seeds", default="backend/seeds_takeoff.json")
    ap.add_argument("--report", default="/tmp/bridge_report.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seeds = json.loads(Path(args.seeds).read_text())
    markets = seeds["markets"]
    conditionals = seeds.setdefault("conditionalMarginals", {})
    var_ids = {str(m.get("variableId")) for m in markets.values()}

    proposals = json.loads(Path(args.proposals).read_text())["bridges"]
    proposals.sort(key=lambda b: (-int(b.get("strength", 0)), str(b.get("externalId"))))

    dropped: list[dict] = []
    candidates: list[dict] = []
    for b in proposals:
        ext = str(b.get("externalId", ""))
        parents = sorted(str(p) for p in b.get("parents", []))
        reason = None
        if not ext.startswith("x") or ext not in markets:
            reason = "unknown external"
        elif ext in conditionals:
            reason = "already has CPT"
        elif int(b.get("strength", 0)) < MIN_STRENGTH:
            reason = "strength below threshold"
        elif not 1 <= len(parents) <= MAX_PARENTS:
            reason = "bad parent count"
        elif any(p not in var_ids for p in parents):
            reason = "unknown parent variable"
        elif markets[ext].get("variableId") in parents:
            reason = "self-parent"
        rows: dict[str, float] | None = None
        if reason is None:
            rows = parse_proposal_cpt(b.get("cpt", {}), parents)
            if rows is None:
                reason = "incomplete CPT"
            elif max(rows.values()) - min(rows.values()) < 0.02:
                reason = "flat CPT (no information)"
        if reason or rows is None:
            dropped.append({"externalId": ext, "reason": reason or "incomplete CPT"})
            continue
        candidates.append({**b, "externalId": ext, "parents": parents, "rows": rows})

    # De-dup: one bridge per external.
    seen: set[str] = set()
    unique = []
    for b in candidates:
        if b["externalId"] in seen:
            dropped.append({"externalId": b["externalId"], "reason": "duplicate proposal"})
            continue
        seen.add(b["externalId"])
        unique.append(b)
    candidates = unique

    # Width check. Single-parent bridges attach a leaf (clique of 2) and can
    # never raise treewidth, so they go in unconditionally; only multi-parent
    # bridges add a moral edge between parents and need individual testing.
    def tables(base: dict, bridges: list[dict]) -> dict:
        trial = dict(base)
        for b in bridges:
            trial[b["externalId"]] = {
                k: {"yes": round(p, 6), "no": round(1.0 - p, 6)}
                for k, p in b["rows"].items()
            }
        return trial

    work = copy.deepcopy(conditionals)
    active = [b for b in candidates if len(b["parents"]) == 1]
    fm = build(markets, tables(work, active))
    for b in (b for b in candidates if len(b["parents"]) > 1):
        try:
            fm = build(markets, tables(work, active + [b]))
            active.append(b)
        except JointMarketError as err:
            dropped.append({"externalId": b["externalId"],
                            "reason": f"width budget: {err}"})
            fm = build(markets, tables(work, active))

    # Exact leaf calibration against the bridged net's parent distributions.
    calibrated: list[dict] = []
    for b in active:
        target = clamp_row(markets[b["externalId"]]["marginals"]["yes"])
        dist = parent_context_dist(fm, b["parents"])
        if dist is None:
            dropped.append({"externalId": b["externalId"], "reason": "parent marginal query failed"})
            continue
        rows = calibrate_leaf(b["rows"], b["parents"], dist, target)
        if rows is None:
            dropped.append({"externalId": b["externalId"], "reason": "calibration infeasible"})
            continue
        calibrated.append({**b, "rows": rows, "target": target})

    # Final tables + verification build.
    for b in calibrated:
        work[b["externalId"]] = {
            k: {"yes": round(p, 6), "no": round(1.0 - p, 6)}
            for k, p in b["rows"].items()
        }
    fm2 = build(markets, work)
    worst = 0.0
    checks = []
    for b in calibrated:
        var = str(markets[b["externalId"]]["variableId"])
        got = fm2.marginal(var)["yes"]
        delta = abs(got - b["target"])
        worst = max(worst, delta)
        checks.append({"externalId": b["externalId"], "target": b["target"],
                       "implied": round(got, 6), "delta": round(delta, 8)})
    stats = fm2.stats()

    report = {
        "at": now, "dryRun": args.dry_run,
        "proposed": len(proposals), "applied": len(calibrated),
        "dropped": dropped, "worstMarginalDelta": worst,
        "stats": {k: stats[k] for k in ("treewidth", "cliqueCount", "maxCliqueStates", "statesLog2")
                  if k in stats},
        "checks": checks,
    }
    Path(args.report).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in
                      ("proposed", "applied", "worstMarginalDelta", "stats")}, indent=1))
    print(f"dropped: {len(dropped)} (see {args.report})")

    if args.dry_run:
        return
    if worst > 1e-6:
        sys.exit(f"ABORT: worst marginal delta {worst} > 1e-6; seeds unchanged")

    for b in calibrated:
        m = markets[b["externalId"]]
        m.setdefault("provenance", {})["bridge"] = {
            "parents": b["parents"], "strength": int(b.get("strength", 0)),
            "appliedAt": now,
        }
        note = f" Bridged into the FTM net: conditional on {', '.join(b['parents'])}."
        if note not in m.get("description", ""):
            m["description"] = m.get("description", "") + note
    seeds["conditionalMarginals"] = work
    backup = Path(args.seeds).with_suffix(".json.pre-bridge")
    backup.write_text(Path(args.seeds).read_text())
    Path(args.seeds).write_text(json.dumps(seeds, indent=1))
    print(f"seeds updated ({args.seeds}); backup at {backup}")


if __name__ == "__main__":
    main()
