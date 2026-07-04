#!/usr/bin/env python3
"""Compile FTM Monte-Carlo samples into a treewidth-bounded market network.

Pipeline: mc_metrics.csv + mc_series.csv (one row per trial / per trial-year)
  -> binary threshold-by-year variables (bitmask over trials)
  -> structure: per-metric comb (within-year threshold chain, exact
     implication zeros; year chain at base threshold) + greedy cross-metric
     MI edges + violation-repair edges, every batch width-checked by
     actually building the FactoredMarket at the target budget
  -> CPTs from smoothed trial counts (implication rows stay exact 0/1)
  -> seeds-v1 JSON for the bayes-market server, with net-implied marginals
     (ftmImplied) so displayed prices are coherent with the CPTs at birth.

Usage:
  python3 compile_takeoff_net.py --export-dir ~/ftm/_output_/bayes_export \
      --out seeds_takeoff.json --report net_report.json [--max-width 8]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.inference import FactoredMarket, JointMarketError  # noqa: E402

YEARS = list(range(2027, 2046))


def popcount(x: int) -> int:
    """int.bit_count() equivalent that also runs on Python 3.9."""
    try:
        return x.bit_count()
    except AttributeError:
        return bin(x).count("1")


# metric key in mc_series.csv (or derived) -> question spec.
# monotone=True: use the running max, questions read "by <year>".
SERIES_SPECS = [
    {
        "metric": "frac_tasks_automated_goods", "monotone": True,
        "thresholds": [0.05, 0.20, 0.50, 0.90],
        "fmt": lambda t: f"{t:.0%}",
        "title": "AI automates {thr} of goods-and-services tasks by {year}",
        "slug": "auto_goods",
    },
    {
        "metric": "frac_tasks_automated_rnd", "monotone": True,
        "thresholds": [0.05, 0.20, 0.50, 0.90],
        "fmt": lambda t: f"{t:.0%}",
        "title": "AI automates {thr} of R&D tasks by {year}",
        "slug": "auto_rnd",
    },
    {
        "metric": "gwp_growth", "monotone": False, "derived_from": "gwp",
        "derive": "yoy_growth",
        "thresholds": [0.05, 0.10, 0.20, 0.30],
        "fmt": lambda t: f"{t:.0%}",
        "title": "World economic growth exceeds {thr}/year in {year}",
        "slug": "gwp_growth", "in_year": True,
    },
    {
        "metric": "gwp_growth_max", "monotone": True, "derived_from": "gwp",
        "derive": "yoy_growth_running_max",
        "thresholds": [0.05, 0.10, 0.20, 0.30],
        "fmt": lambda t: f"{t:.0%}",
        "title": "World economic growth has exceeded {thr}/year by {year}",
        "slug": "gwp_growth_max",
    },
    {
        "metric": "biggest_training_run", "monotone": True,
        "thresholds": [1e28, 1e29, 1e31, 1e33],
        "fmt": lambda t: f"1e{int(round(math.log10(t)))} FLOP",
        "title": "Largest training run exceeds {thr} by {year}",
        "slug": "train_run", "log_scale": True,
    },
    {
        "metric": "frac_gwp_compute", "monotone": True,
        "thresholds": [0.005, 0.01, 0.02, 0.05],
        "fmt": lambda t: f"{t:.1%}",
        "title": "Compute investment exceeds {thr} of world output by {year}",
        "slug": "gwp_compute",
    },
    {
        "metric": "hardware_ratio", "monotone": True,
        "derived_from": "hardware_performance", "derive": "ratio_base",
        "thresholds": [10.0, 100.0, 10000.0],
        "fmt": lambda t: f"{t:,.0f}x",
        "title": "Hardware price-performance improves {thr} over 2026 by {year}",
        "slug": "hw_ratio",
    },
    {
        "metric": "software_ratio", "monotone": True,
        "derived_from": "software", "derive": "ratio_base",
        "thresholds": [10.0, 100.0, 10000.0],
        "fmt": lambda t: f"{t:,.0f}x",
        "title": "AI software efficiency improves {thr} over 2026 by {year}",
        "slug": "sw_ratio",
    },
]

# scalar metric in mc_metrics.csv -> "happens by year Y" chain.
# {"metric": csv column, "title": ..., "slug": ...}; thresholds = YEARS.
SCALAR_SPECS = [
    {
        "metric_candidates": [
            "automation_gns_100%", "full_automation_year", "agi_year",
            "automation_gns_100", "full_economic_automation_year",
        ],
        "title": "Full automation of goods-and-services work by {year}",
        "slug": "full_auto",
    },
    {
        "metric_candidates": [
            "automation_gns_20%", "automation_gns_20", "rampup_start",
            "wake_up_year", "rampup_start_year",
        ],
        "title": "AI economic ramp-up (20% automation) begins by {year}",
        "slug": "rampup",
    },
    {
        "metric_candidates": [
            "automation_rnd_100%", "full_rnd_automation_year",
        ],
        "title": "Full automation of R&D work by {year}",
        "slug": "full_auto_rnd",
    },
    {
        "metric_candidates": ["agi_year"],
        "title": "AGI training requirements are met by {year}",
        "slug": "agi",
    },
    {
        "metric_candidates": ["automation_rnd_20%"],
        "title": "AI automates 20% of R&D work by {year}",
        "slug": "rampup_rnd",
    },
]

# Per-family operationalized resolution criteria ({thr}/{year} templates,
# editorial pass 2026-07-04); missing file falls back to the generic sentence.
_RESOLUTIONS_PATH = Path(__file__).resolve().parent / "resolution_templates.json"
try:
    RESOLUTIONS: dict[str, str] = json.loads(_RESOLUTIONS_PATH.read_text())["templates"]
except (OSError, ValueError, KeyError):
    RESOLUTIONS = {}


def resolution_text(v: "Variable") -> str:
    tpl = RESOLUTIONS.get(v.slug)
    if not tpl:
        return (
            f"Resolution: per the metric definition in the Epoch Full Takeoff "
            f"Model ('{v.metric}'), estimated from public data (Epoch AI, "
            f"official statistics) at resolution time."
        )
    if v.thr_idx is not None and "thresholds" in v.spec:
        thr = v.spec["fmt"](v.spec["thresholds"][v.thr_idx])
        return tpl.format(thr=thr, year=v.year)
    return tpl.format(year=v.year)


MIN_P = 0.03
MIN_SIDE_TRIALS = 8
SMOOTH = 0.5
SHRINK_N = 15.0
CROSS_EDGE_MIN_MI = 0.015  # nats; below this a cross edge isn't worth width
VIOLATION_REPAIR_PTS = 0.02


class Variable:
    __slots__ = ("vid", "title", "mask", "metric", "slug", "year", "thr_idx",
                 "sample_p", "spec")

    def __init__(self, vid, title, mask, metric, slug, year, thr_idx, n, spec):
        self.vid = vid
        self.title = title
        self.mask = mask
        self.metric = metric
        self.slug = slug
        self.year = year
        self.thr_idx = thr_idx
        self.sample_p = popcount(mask) / n
        self.spec = spec


def load_series(path: Path) -> dict[str, dict[int, dict[int, float]]]:
    """metric -> trial -> year -> value"""
    out: dict[str, dict[int, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    with path.open() as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["metric"]][int(row["trial"])][int(float(row["year"]))] = float(row["value"])
            except (KeyError, ValueError):
                continue
    return out


def load_metrics(path: Path) -> tuple[list[int], dict[str, dict[int, float]]]:
    trials: list[int] = []
    cols: dict[str, dict[int, float]] = defaultdict(dict)
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            trial = int(row.get("trial") or row.get("trial_id") or len(trials))
            trials.append(trial)
            for key, value in row.items():
                if key in ("trial", "trial_id") or value in (None, "", "nan"):
                    continue
                try:
                    cols[key][trial] = float(value)
                except ValueError:
                    continue
    return trials, cols


def derive_series(kind: str, per_trial: dict[int, dict[int, float]]):
    out: dict[int, dict[int, float]] = {}
    for trial, years in per_trial.items():
        derived: dict[int, float] = {}
        if kind == "ratio_base":
            ordered = sorted(years)
            base = next((years[y] for y in ordered if years[y] > 0), None)
            if base:
                for year in ordered:
                    derived[year] = years[year] / base
            out[trial] = derived
            continue
        prev_max = -math.inf
        for year in sorted(years):
            if year - 1 in years and years[year - 1] > 0:
                g = years[year] / years[year - 1] - 1.0
                if kind == "yoy_growth":
                    derived[year] = g
                else:  # running max
                    prev_max = max(prev_max, g)
                    derived[year] = prev_max
        out[trial] = derived
    return out


def build_variables(series, scalar_cols, trial_ids):
    n = len(trial_ids)
    tpos = {t: i for i, t in enumerate(trial_ids)}
    variables: list[Variable] = []
    seen_masks: dict[int, str] = {}
    dropped = {"degenerate": 0, "duplicate": 0, "missing": 0}

    def add(vid, title, mask, metric, slug, year, thr_idx, spec):
        p = popcount(mask) / n
        if not (MIN_P <= p <= 1 - MIN_P):
            dropped["degenerate"] += 1
            return
        side = min(popcount(mask), n - popcount(mask))
        if side < MIN_SIDE_TRIALS:
            dropped["degenerate"] += 1
            return
        if mask in seen_masks:
            dropped["duplicate"] += 1
            return
        seen_masks[mask] = vid
        variables.append(Variable(vid, title, mask, metric, slug, year, thr_idx, n, spec))

    for spec in SERIES_SPECS:
        source = spec.get("derived_from", spec["metric"])
        per_trial = series.get(source)
        if not per_trial:
            dropped["missing"] += 1
            continue
        if "derive" in spec:
            per_trial = derive_series(spec["derive"], per_trial)
        for thr_idx, thr in enumerate(spec["thresholds"]):
            running: dict[int, bool] = {}
            for year in YEARS:
                mask = 0
                for trial, years in per_trial.items():
                    if trial not in tpos:
                        continue
                    value = years.get(year)
                    if spec.get("monotone") and "derive" not in spec:
                        # running max of the raw series up to this year
                        prior = running.get(trial, -math.inf)
                        if value is not None:
                            prior = max(prior, value)
                            running[trial] = prior
                        value = prior if prior > -math.inf else None
                    if value is not None and value >= thr:
                        mask |= 1 << tpos[trial]
                thr_s = spec["fmt"](thr)
                word = "in" if spec.get("in_year") else "by"
                vid = f"ftm_{spec['slug']}_t{thr_idx}_{word}_{year}"
                title = spec["title"].format(thr=thr_s, year=year)
                add(vid, title, mask, spec["metric"], spec["slug"], year, thr_idx, spec)
    for spec in SCALAR_SPECS:
        col = None
        for cand in spec["metric_candidates"]:
            if cand in scalar_cols:
                col = cand
                break
        if col is None:
            dropped["missing"] += 1
            continue
        values = scalar_cols[col]
        for year in YEARS:
            mask = 0
            for trial, value in values.items():
                if trial in tpos and not math.isnan(value) and value <= year:
                    mask |= 1 << tpos[trial]
            vid = f"ftm_{spec['slug']}_by_{year}"
            add(vid, spec["title"].format(year=year), mask, col, spec["slug"], year, 0, spec)
    return variables, dropped


def mutual_information(a: int, b: int, n: int) -> float:
    n11 = popcount(a & b)
    n1_ = popcount(a)
    n_1 = popcount(b)
    mi = 0.0
    for cell, row, col in (
        (n11, n1_, n_1),
        (n1_ - n11, n1_, n - n_1),
        (n_1 - n11, n - n1_, n_1),
        (n - n1_ - n_1 + n11, n - n1_, n - n_1),
    ):
        if cell > 0 and row > 0 and col > 0:
            mi += (cell / n) * math.log(cell * n / (row * col))
    return mi


def build_structure(variables: list[Variable], n: int, max_width: int, log):
    """Return parents dict vid -> list[vid]; width-checked incrementally."""
    by_key = {(v.slug, v.thr_idx, v.year): v for v in variables}
    parents: dict[str, list[str]] = {v.vid: [] for v in variables}
    implication: set[tuple[str, str]] = set()  # (child, parent): child=yes -> ... exact rows

    def prev_year_var(v):
        for back in range(1, 4):
            u = by_key.get((v.slug, v.thr_idx, v.year - back))
            if u:
                return u
        return None

    def lower_thr_var(v):
        for down in range(1, 4):
            u = by_key.get((v.slug, v.thr_idx - down, v.year))
            if u:
                return u
        return None

    # Full implication lattice per metric: every node gets its year
    # predecessor AND its lower-threshold sibling (both exact implications
    # for monotone metrics). Lattice treewidth = min(#thresholds, #years),
    # so thresholds are capped at 4 per metric in the specs above.
    for v in variables:
        low = lower_thr_var(v)
        if low is not None:
            parents[v.vid].append(low.vid)
            implication.add((v.vid, low.vid))  # v yes -> low yes (subset)
        prev = prev_year_var(v)
        if prev is not None:
            parents[v.vid].append(prev.vid)
            if not v.spec.get("in_year"):
                implication.add((prev.vid, v.vid))  # prev yes -> v yes

    def check_width(ps):
        nodes = _nodes_stub(variables, ps)
        try:
            FactoredMarket.from_nodes(nodes, 300.0, max_width)
            return True
        except JointMarketError:
            return False

    if not check_width(parents):
        raise SystemExit("implication lattice alone exceeds width budget — reduce grid")

    # Cross-metric edges: for each metric's base-threshold chain nodes, best
    # single extra parent from OTHER metrics by MI, batched width checks.
    slugs = sorted({v.slug for v in variables})
    order = {s: i for i, s in enumerate(slugs)}
    candidates: list[tuple[float, str, str]] = []
    for v in variables:
        if v.thr_idx != 0 or len(parents[v.vid]) >= 3:
            continue
        best = None
        for u in variables:
            if u.slug == v.slug or order[u.slug] >= order[v.slug]:
                continue
            if abs(u.year - v.year) > 2 or u.thr_idx != 0:
                continue
            mi = mutual_information(v.mask, u.mask, n)
            if best is None or mi > best[0]:
                best = (mi, u.vid)
        if best and best[0] >= CROSS_EDGE_MIN_MI:
            candidates.append((best[0], v.vid, best[1]))
    candidates.sort(reverse=True)

    added = 0
    for i in range(0, len(candidates), 20):
        batch = candidates[i:i + 20]
        trial_parents = {k: list(ps) for k, ps in parents.items()}
        for _, child, parent in batch:
            if parent not in trial_parents[child] and len(trial_parents[child]) < 3:
                trial_parents[child].append(parent)
        if check_width(trial_parents):
            parents = trial_parents
            added += len(batch)
        else:
            for _, child, parent in batch:  # one by one
                trial = {k: list(ps) for k, ps in parents.items()}
                if parent not in trial[child] and len(trial[child]) < 3:
                    trial[child].append(parent)
                    if check_width(trial):
                        parents = trial
                        added += 1
    log(f"cross-metric edges added: {added}/{len(candidates)}")
    return parents, implication


def _nodes_stub(variables, parents):
    """Uniform-CPT nodes just for structure/width checking."""
    nodes = []
    for v in variables:
        pv = parents[v.vid]
        rows = {}
        for combo in range(1 << len(pv)):
            key = frozenset(
                (pv[j], "yes" if combo >> j & 1 else "no") for j in range(len(pv))
            )
            rows[key] = {"yes": 0.5, "no": 0.5}
        nodes.append({
            "variable_id": v.vid, "outcomes": ("yes", "no"),
            "parents": tuple(pv), "rows": rows,
        })
    return nodes


def fit_cpts(variables, parents, implication, n):
    by_vid = {v.vid: v for v in variables}
    nodes = []
    low_support = 0
    full = (1 << n) - 1
    for v in variables:
        pv = parents[v.vid]
        rows = {}
        for combo in range(1 << len(pv)):
            ctx_mask = full
            key_pairs = []
            for j, pid in enumerate(pv):
                bit = combo >> j & 1
                pmask = by_vid[pid].mask
                ctx_mask &= pmask if bit else (full & ~pmask)
                key_pairs.append((pid, "yes" if bit else "no"))
            key = frozenset(key_pairs)
            # exact implication rows
            forced = None
            for pid, outcome in key_pairs:
                if (v.vid, pid) in implication and outcome == "no":
                    forced = 0.0   # v yes -> pid yes; pid no => v no
                if (pid, v.vid) in implication and outcome == "yes":
                    forced = 1.0   # pid yes -> v yes
            if forced is not None:
                p = forced
            else:
                ctx_n = popcount(ctx_mask)
                yes = popcount(ctx_mask & v.mask)
                p_hat = (yes + SMOOTH) / (ctx_n + 2 * SMOOTH) if ctx_n else v.sample_p
                lam = ctx_n / (ctx_n + SHRINK_N)
                p = lam * p_hat + (1 - lam) * v.sample_p
                if ctx_n < MIN_SIDE_TRIALS:
                    low_support += 1
                p = min(max(p, 0.0005), 0.9995)
            rows[key] = {"yes": round(p, 6), "no": round(1 - p, 6)}
        nodes.append({
            "variable_id": v.vid, "outcomes": ("yes", "no"),
            "parents": tuple(pv), "rows": rows,
        })
    return nodes, low_support


def measure_violations(market, variables):
    """Largest P(child=yes, parent-implication=no) style leaks in the net."""
    worst = []
    by_key = {(v.slug, v.thr_idx, v.year): v for v in variables}
    for v in variables:
        if v.spec.get("in_year"):
            continue
        nxt = by_key.get((v.slug, v.thr_idx, v.year + 1))
        if nxt is None:
            continue
        cond = market.marginal(nxt.vid, {v.vid: "yes"})
        if cond is None:
            continue
        leak = cond["no"]  # P(not by y+1 | by y) should be 0
        if leak > 0:
            worst.append((leak, v.vid, nxt.vid))
    worst.sort(reverse=True)
    return worst


def calibrate_marginals(nodes, variables, max_width):
    """Exact topological calibration: one Gauss-Seidel sweep.

    In topological order, each family's statistical rows get the single
    log-odds shift that makes the NET-implied marginal equal the sample
    marginal exactly (bisection on a monotone function of the shift), with
    the parent-context distribution taken from the current market — upstream
    families are already exact and are unaffected by this node's rows, so
    one sweep is exact by induction. Implication rows (0/1) never move, so
    logical coherence is preserved; if forced mass alone exceeds the target
    the shift saturates and the residual is reported.
    """
    def logit(p):
        return math.log(p / (1 - p))

    def sigmoid(x):
        return 1 / (1 + math.exp(-x))

    by_vid = {v.vid: (v, node) for v, node in zip(variables, nodes)}
    order = _topo_order(nodes)
    market = FactoredMarket.from_nodes(nodes, 300.0, max_width)
    worst = 0.0
    for vid in order:
        v, node = by_vid[vid]
        target = min(max(v.sample_p, 0.002), 0.998)
        parent_ids = sorted({p for key in node["rows"] for p, _ in key})
        # parent-context distribution under the current (upstream-exact) net
        ctx_probs = {}
        for key in node["rows"]:
            assignment = dict(key)
            p_ctx = 1.0
            evidence: dict[str, str] = {}
            for pid in parent_ids:
                m = market.marginal(pid, evidence)
                if m is None:
                    p_ctx = 0.0
                    break
                p_ctx *= m.get(assignment[pid], 0.0)
                evidence[pid] = assignment[pid]
                if p_ctx == 0.0:
                    break
            ctx_probs[key] = p_ctx
        total_ctx = sum(ctx_probs.values())
        if total_ctx <= 0.0:
            continue
        forced_yes = sum(p for key, p in ctx_probs.items()
                         if node["rows"][key]["yes"] >= 1.0)
        free = [(key, p) for key, p in ctx_probs.items()
                if 0.0 < node["rows"][key]["yes"] < 1.0 and p > 0.0]

        def implied_at(d):
            s = forced_yes
            for key, p_ctx in free:
                q = min(max(node["rows"][key]["yes"], 0.0005), 0.9995)
                s += p_ctx * sigmoid(logit(q) + d)
            return s / total_ctx

        lo, hi = -14.0, 14.0
        if implied_at(lo) > target:
            d = lo
        elif implied_at(hi) < target:
            d = hi
        else:
            for _ in range(50):
                mid = (lo + hi) / 2
                if implied_at(mid) < target:
                    lo = mid
                else:
                    hi = mid
            d = (lo + hi) / 2
        worst = max(worst, abs(implied_at(d) - target))
        if abs(d) > 1e-9:
            for key, _ in free:
                q = min(max(node["rows"][key]["yes"], 0.0005), 0.9995)
                q2 = min(max(sigmoid(logit(q) + d), 0.0005), 0.9995)
                node["rows"][key]["yes"] = round(q2, 6)
                node["rows"][key]["no"] = round(1 - q2, 6)
            market = FactoredMarket.from_nodes(nodes, 300.0, max_width)
    return market, worst


def _topo_order(nodes) -> list[str]:
    parents_of = {n["variable_id"]: set(n["parents"]) for n in nodes}
    order: list[str] = []
    pending = dict(parents_of)
    while pending:
        ready = sorted(v for v, deps in pending.items() if not deps & set(pending))
        if not ready:
            raise SystemExit("cycle in compiled structure")
        for v in ready:
            order.append(v)
            del pending[v]
    return order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--max-width", type=int, default=8)
    ap.add_argument("--liquidity", type=float, default=10000.0)
    ap.add_argument("--id-prefix", default="f")
    args = ap.parse_args()

    export = Path(args.export_dir).expanduser()
    manifest = json.loads((export / "manifest.json").read_text())
    series = load_series(export / "mc_series.csv")
    trial_ids, scalar_cols = load_metrics(export / "mc_metrics.csv")
    n = len(trial_ids)
    print(f"trials: {n}; series metrics: {sorted(series)}")

    def log(msg):
        print(f"[compile] {msg}")

    variables, dropped = build_variables(series, scalar_cols, trial_ids)
    log(f"variables kept: {len(variables)}; dropped: {dropped}")

    parents, implication = build_structure(variables, n, args.max_width, log)
    nodes, low_support = fit_cpts(variables, parents, implication, n)
    log(f"CPT rows with low support: {low_support}")

    market = FactoredMarket.from_nodes(nodes, 300.0, args.max_width)
    stats = market.stats()
    log(f"net: width={stats['treewidth']:.0f} cliques={stats['cliqueCount']:.0f}")

    # violation repair
    violations = measure_violations(market, variables)
    repaired = 0
    for leak, vid, nxt_vid in violations:
        if leak < VIOLATION_REPAIR_PTS:
            break
        if len(parents[nxt_vid]) >= 3 or vid in parents[nxt_vid]:
            continue
        trial = {k: list(ps) for k, ps in parents.items()}
        trial[nxt_vid].append(vid)
        implication.add((vid, nxt_vid))
        try:
            trial_nodes, _ = fit_cpts(variables, trial, implication, n)
            market = FactoredMarket.from_nodes(trial_nodes, 300.0, args.max_width)
            parents, nodes = trial, trial_nodes
            repaired += 1
        except JointMarketError:
            implication.discard((vid, nxt_vid))
    if repaired:
        log(f"violation-repair edges added: {repaired}")
        violations = measure_violations(market, variables)
    max_leak = violations[0][0] if violations else 0.0
    log(f"max residual implication leak: {max_leak:.4f}")

    market, worst_after_cal = calibrate_marginals(nodes, variables, args.max_width)
    log(f"marginal calibration: worst |implied - sample| = {worst_after_cal:.4f}")

    # Structure repair for calibration: nodes still far from their sample
    # marginal need a better family, not a bigger shift — add the most
    # informative extra parent (cycle-safe, width-checked) and recalibrate.
    n_trials = n
    by_vid = {v.vid: v for v in variables}

    def ancestors(vid, ps):
        out, stack = set(), list(ps[vid])
        while stack:
            u = stack.pop()
            if u not in out:
                out.add(u)
                stack.extend(ps[u])
        return out

    for round_ in range(4):
        residuals = sorted(
            ((abs(market.marginal(v.vid, None)["yes"] - v.sample_p), v)
             for v in variables), reverse=True, key=lambda t: t[0])
        stuck = [(r, v) for r, v in residuals if r > 0.03][:12]
        if not stuck:
            break
        changed = False
        for _, v in stuck:
            if len(parents[v.vid]) >= 4:
                continue
            anc_v = ancestors(v.vid, parents)
            cands = sorted(
                (u for u in variables
                 if u.vid != v.vid and u.vid not in parents[v.vid]
                 and v.vid not in ancestors(u.vid, parents)),
                key=lambda u: -mutual_information(v.mask, u.mask, n_trials))[:4]
            for u in cands:
                trial_parents = {k: list(ps) for k, ps in parents.items()}
                trial_parents[v.vid].append(u.vid)
                if u.slug == v.slug and not v.spec.get("in_year"):
                    if u.thr_idx == v.thr_idx and u.year < v.year:
                        implication.add((u.vid, v.vid))
                    elif u.year == v.year and u.thr_idx < v.thr_idx:
                        implication.add((v.vid, u.vid))
                trial_nodes, _ = fit_cpts(variables, trial_parents, implication, n_trials)
                try:
                    market = FactoredMarket.from_nodes(trial_nodes, 300.0, args.max_width)
                    parents, nodes = trial_parents, trial_nodes
                    changed = True
                    break
                except JointMarketError:
                    continue
        if not changed:
            break
        market, worst_after_cal = calibrate_marginals(nodes, variables, args.max_width)
        log(f"calibration repair round {round_ + 1}: worst residual = {worst_after_cal:.4f}")
    del by_vid

    post_leak = measure_violations(market, variables)
    max_leak = max(max_leak, post_leak[0][0] if post_leak else 0.0)

    # emit seeds
    created = manifest.get("timestamp", "2026-07-04T00:00:00Z")
    markets = {}
    conditional = {}
    proj_deltas = []
    for i, (v, node) in enumerate(zip(variables, nodes), start=1):
        mid = f"{args.id_prefix}{i:04d}"
        implied = market.marginal(v.vid, None)["yes"]
        proj_deltas.append(abs(implied - v.sample_p))
        markets[mid] = {
            "id": mid,
            "title": v.title,
            "description": (
                f"{v.title}. {resolution_text(v)} Prior from "
                f"the FTM Monte Carlo ({manifest.get('n_trials', n)} trials, "
                f"observed-2026-06-28 recalibration): {v.sample_p:.1%}."
            ),
            "variableId": v.vid,
            "status": "active",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "marginals": {"yes": round(implied, 6), "no": round(1 - implied, 6)},
            "liquidity": args.liquidity,
            "volume": 0.0,
            "created_at": created,
            "expires_at": f"{v.year}-12-31T23:59:59Z",
            "ftmImplied": round(implied, 6),
            "provenance": {
                "source": "ftm",
                "method": "mc-threshold-grid-v1",
                "calibration": manifest.get("parameter_table", "observed_2026-06-28"),
                "trials": n,
                "sampleMarginal": round(v.sample_p, 6),
                "metric": v.metric,
            },
        }
        if parents[v.vid]:
            rows = {}
            for key, row in node["rows"].items():
                ctx = "|".join(f"{pid}={out}" for pid, out in sorted(key))
                rows[ctx] = row
            conditional[mid] = rows

    seeds = {"version": "seeds-v1", "markets": markets, "conditionalMarginals": conditional}
    Path(args.out).write_text(json.dumps(seeds, indent=1))
    report = {
        "variables": len(variables),
        "dropped": dropped,
        "edges": sum(len(p) for p in parents.values()),
        "implicationEdges": len(implication),
        "treewidth": stats["treewidth"],
        "cliqueCount": stats["cliqueCount"],
        "maxResidualLeak": max_leak,
        "maxProjectionDelta": max(proj_deltas) if proj_deltas else 0.0,
        "meanProjectionDelta": sum(proj_deltas) / len(proj_deltas) if proj_deltas else 0.0,
        "lowSupportRows": low_support,
        "trials": n,
    }
    Path(args.report).write_text(json.dumps(report, indent=1))
    log(f"wrote {args.out} ({len(markets)} markets) and {args.report}")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
