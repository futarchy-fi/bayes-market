#!/usr/bin/env python3
"""Compile FTM Monte-Carlo samples into a treewidth-bounded market network.

Pipeline: mc_metrics.csv + mc_series.csv (one row per trial / per trial-year)
  -> optional late-2026 Bayesian importance reweighting (observed 2026 training
     run compute, AI compute capex share of GWP, early R&D automation, and
     bounded AGI-timeline calibration)
  -> binary threshold-by-year variables (bitmask over trials, per-slug dedup)
  -> domain-causal structure: per-metric implication lattice + exact cross-metric
     logical implications + forward-in-time (u.year <= v.year) leading-indicator
     2-hub separator and upstream infrastructure causal chain, width-checked
     against the FactoredMarket treewidth budget (<= max_width)
  -> CPTs from ESS-weighted trial counts with exact 0/1 implication rows
     (forced_zero strictly takes precedence over forced_one) and context-aware
     fallback priors
  -> exact topological-level marginal calibration (preserving 0/1 implication rows)
  -> seeds-v1 JSON for the bayes-market server, with net-implied marginals
     (ftmImplied) so displayed prices are coherent with the CPTs at birth.

Usage:
  python3 compile_takeoff_net.py --export-dir /home/kelvin/ftm_export_corr \
      --out /tmp/seeds_ftm_v2.json --report scripts/compile/ftm_report_corr.json \
      --max-width 8 [--late-2026-weights | --no-late-2026-weights]
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.inference import FactoredMarket, JointMarketError  # noqa: E402

YEARS = list(range(2027, 2036))
CALIBRATION_DATE = "2026-11-23"


def popcount(x: int) -> int:
    """int.bit_count() equivalent that also runs on Python 3.9."""
    try:
        return x.bit_count()
    except AttributeError:
        return bin(x).count("1")


# Domain-causal ordering across FTM families (all cross-metric edges strictly
# flow forward in this order AND forward/same-year in time: u.year <= v.year).
CAUSAL_ORDER = [
    "gwp_compute",
    "hw_ratio",
    "sw_ratio",
    "train_run",
    "auto_rnd",
    "full_auto_rnd",
    "sub_agi",
    "agi",
    "full_auto",
    "auto_goods",
    "gwp_growth_max",
    "gwp_growth",
]
CAUSAL_RANK = {slug: idx for idx, slug in enumerate(CAUSAL_ORDER)}

# Exact cross-metric logical implications verified against raw FTM MC:
# (sub_slug, sub_thr, sup_slug, sup_thr, orient)
# - orient == "sup_parent": sup -> sub with forced_zero when sup == no
# - orient == "sub_parent": sub -> sup with forced_one  when sub == yes
CROSS_METRIC_IMPLICATIONS = [
    ("full_auto", 0, "auto_goods", 3, "sub_parent"),
    ("full_auto_rnd", 0, "auto_rnd", 3, "sup_parent"),
    ("agi", 0, "sub_agi", 0, "sup_parent"),
    ("gwp_growth", 0, "gwp_growth_max", 0, "sup_parent"),
    ("gwp_growth", 1, "gwp_growth_max", 1, "sup_parent"),
    ("gwp_growth", 2, "gwp_growth_max", 2, "sup_parent"),
    ("gwp_growth", 3, "gwp_growth_max", 3, "sup_parent"),
]

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
# Redundant rampup / rampup_rnd (20% goods / 20% R&D) are omitted because
# auto_goods_t1 and auto_rnd_t1 already represent those exact milestones.
SCALAR_SPECS = [
    {
        "metric_candidates": [
            "automation_gns_100%", "full_automation_year",
            "automation_gns_100", "full_economic_automation_year",
        ],
        "title": "Full automation of goods-and-services work by {year}",
        "slug": "full_auto",
    },
    {
        "metric_candidates": [
            "automation_rnd_100%", "full_rnd_automation_year",
        ],
        "title": "Full automation of R&D work by {year}",
        "slug": "full_auto_rnd",
    },
    {
        "metric_candidates": ["sub_agi_year"],
        "title": "Weakly general AI (Sub-AGI) threshold reached by {year}",
        "slug": "sub_agi",
    },
    {
        "metric_candidates": ["agi_year"],
        "title": "AGI training requirements are met by {year}",
        "slug": "agi",
    },
]

# Per-family operationalized resolution criteria ({thr}/{year} templates);
# missing file falls back to the generic sentence.
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


MIN_P = 0.02
MIN_EFF_SIDE = 3.0
SMOOTH = 0.05
SHRINK_N = 0.25
CROSS_EDGE_MIN_MI = 0.015  # nats
VIOLATION_REPAIR_PTS = 1e-6


class TrialWeights:
    """Fast weighted mask accumulator via 10-bit chunk lookup tables."""

    CHUNK = 10
    MASK_CHUNK = (1 << CHUNK) - 1

    def __init__(self, weights: list[float]):
        n = len(weights)
        total = sum(weights)
        if total <= 0:
            raise ValueError("trial weights must sum to a positive number")
        self.weights = [w / total for w in weights]
        self.n = n
        self.full_mask = (1 << n) - 1
        self.ess = 1.0 / sum(w * w for w in self.weights)

        n_chunks = (n + self.CHUNK - 1) // self.CHUNK
        self._w_tables: list[list[float]] = []
        self._w2_tables: list[list[float]] = []
        for c in range(n_chunks):
            base = c * self.CHUNK
            lim = min(self.CHUNK, n - base)
            size = 1 << lim
            wt = [0.0] * size
            w2t = [0.0] * size
            for b in range(lim):
                wb = self.weights[base + b]
                w2b = wb * wb
                step = 1 << b
                for idx in range(step, size):
                    if idx & step:
                        wt[idx] = wt[idx ^ step] + wb
                        w2t[idx] = w2t[idx ^ step] + w2b
            self._w_tables.append(wt)
            self._w2_tables.append(w2t)

    def prob(self, mask: int) -> float:
        tot = 0.0
        m = mask
        c = 0
        w_tables = self._w_tables
        mc = self.MASK_CHUNK
        ch_shift = self.CHUNK
        while m:
            ch = m & mc
            if ch:
                tot += w_tables[c][ch]
            m >>= ch_shift
            c += 1
        return tot

    def sum_w2(self, mask: int) -> float:
        tot = 0.0
        m = mask
        c = 0
        w2_tables = self._w2_tables
        mc = self.MASK_CHUNK
        ch_shift = self.CHUNK
        while m:
            ch = m & mc
            if ch:
                tot += w2_tables[c][ch]
            m >>= ch_shift
            c += 1
        return tot

    def min_side_ess(self, mask: int) -> float:
        p = self.prob(mask)
        sy2 = self.sum_w2(mask)
        sn2 = self.sum_w2(self.full_mask ^ mask)
        ess_y = (p * p / sy2) if sy2 > 0 else 0.0
        ess_n = ((1.0 - p) * (1.0 - p) / sn2) if sn2 > 0 else 0.0
        return min(ess_y, ess_n)

    def mutual_information(self, a: int, b: int) -> float:
        p11 = self.prob(a & b)
        p1_ = self.prob(a)
        p_1 = self.prob(b)
        p10 = max(p1_ - p11, 0.0)
        p01 = max(p_1 - p11, 0.0)
        p00 = max(1.0 - p1_ - p_1 + p11, 0.0)
        p0_ = max(1.0 - p1_, 0.0)
        p_0 = max(1.0 - p_1, 0.0)
        mi = 0.0
        for cell, row, col in (
            (p11, p1_, p_1),
            (p10, p1_, p_0),
            (p01, p0_, p_1),
            (p00, p0_, p_0),
        ):
            if cell > 1e-15 and row > 1e-15 and col > 1e-15:
                mi += cell * math.log(cell / (row * col))
        return mi


def compute_late_2026_weights(series, scalar_cols, trial_ids) -> tuple[TrialWeights, dict]:
    """Bayesian importance weights updating June-2026 FTM MC to late-2026 short-timelines reality.

    Observables anchored to Nov 2026:
      1. Largest training run compute in 2026 ~ log10 N(26.75, 0.60^2) (~6e26 FLOP).
      2. AI compute capex share of GWP in 2026 ~ log10 N(log10(0.0035), 0.55^2) (~0.35% GWP).
      3. Early AI R&D automation in 2026 >= 1% (+0.65 log-likelihood bonus).
      4. Bounded exponential tilt on agi_year (-0.16 * (min(agi_year, 2060) - 2035)),
         yielding a crisp short-timelines (2027-2035) prior while preserving healthy
         effective sample size (ESS >= 240 / 2000).
    """
    tr_series = series.get("biggest_training_run", {})
    cap_series = series.get("frac_gwp_compute", {})
    rnd_series = series.get("frac_tasks_automated_rnd", {})
    agi_col = scalar_cols.get("agi_year", {})

    log_cap_target = math.log10(0.0035)
    log_ws: list[float] = []
    for t in trial_ids:
        lw = 0.0
        tr26 = tr_series.get(t, {}).get(2026)
        if tr26 is not None and tr26 > 0:
            lw += -0.5 * ((math.log10(tr26) - 26.75) / 0.60) ** 2
        cap26 = cap_series.get(t, {}).get(2026)
        if cap26 is not None and cap26 > 0:
            lw += -0.5 * ((math.log10(cap26) - log_cap_target) / 0.55) ** 2
        rnd26 = rnd_series.get(t, {}).get(2026, 0.0)
        if rnd26 is not None and rnd26 >= 0.01:
            lw += 0.65
        ay = agi_col.get(t, 2060.0)
        if math.isnan(ay):
            ay = 2060.0
        lw += -0.16 * (min(ay, 2060.0) - 2035.0)
        log_ws.append(lw)

    mx = max(log_ws)
    raw = [math.exp(x - mx) for x in log_ws]
    tw = TrialWeights(raw)
    meta = {
        "enabled": True,
        "calibrationDate": CALIBRATION_DATE,
        "ess": round(tw.ess, 2),
        "observables": {
            "log10_biggest_training_run_2026": {"mean": 26.75, "sd": 0.60},
            "log10_frac_gwp_compute_2026": {"mean": round(log_cap_target, 4), "sd": 0.55},
            "frac_tasks_automated_rnd_2026_ge_0.01_log_bonus": 0.65,
            "agi_year_exp_tilt": -0.16,
        },
    }
    return tw, meta

class Variable:
    __slots__ = ("vid", "title", "mask", "metric", "slug", "year", "thr_idx",
                 "sample_p", "spec")

    def __init__(self, vid, title, mask, metric, slug, year, thr_idx, sample_p, spec):
        self.vid = vid
        self.title = title
        self.mask = mask
        self.metric = metric
        self.slug = slug
        self.year = year
        self.thr_idx = thr_idx
        self.sample_p = sample_p
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


def build_variables(series, scalar_cols, trial_ids, tw: TrialWeights):
    tpos = {t: i for i, t in enumerate(trial_ids)}
    variables: list[Variable] = []
    # Deduplicate bitmasks ONLY within the same slug (never across families!).
    seen_masks_by_slug: dict[str, dict[int, str]] = defaultdict(dict)
    dropped = {"degenerate": 0, "duplicate": 0, "missing": 0}

    def add(vid, title, mask, metric, slug, year, thr_idx, spec):
        p = tw.prob(mask)
        if not (MIN_P <= p <= 1.0 - MIN_P):
            dropped["degenerate"] += 1
            return
        if tw.min_side_ess(mask) < MIN_EFF_SIDE:
            dropped["degenerate"] += 1
            return
        slug_seen = seen_masks_by_slug[slug]
        if mask in slug_seen:
            dropped["duplicate"] += 1
            return
        slug_seen[mask] = vid
        variables.append(Variable(vid, title, mask, metric, slug, year, thr_idx, p, spec))

    for spec in SERIES_SPECS:
        source = spec.get("derived_from", spec["metric"])
        per_trial = series.get(source)
        if not per_trial:
            dropped["missing"] += 1
            continue
        if "derive" in spec:
            per_trial = derive_series(spec["derive"], per_trial)
        for thr_idx, thr in enumerate(spec["thresholds"]):
            running: dict[int, float] = {}
            for year in YEARS:
                mask = 0
                for trial, years in per_trial.items():
                    if trial not in tpos:
                        continue
                    value = years.get(year)
                    if spec.get("monotone") and "derive" not in spec:
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


def _min_fill_width(parents: dict[str, list[str]], max_width: int) -> int:
    """Fast incremental min-fill treewidth upper bound on the moralized DAG."""
    adj: dict[str, set[str]] = {v: set() for v in parents}
    for v, pvs in parents.items():
        for p in pvs:
            adj[v].add(p)
            adj[p].add(v)
        for i in range(len(pvs)):
            for j in range(i + 1, len(pvs)):
                adj[pvs[i]].add(pvs[j])
                adj[pvs[j]].add(pvs[i])

    def fill_count(u: str) -> int:
        nbs = list(adj[u])
        cnt = 0
        for i in range(len(nbs)):
            ni = adj[nbs[i]]
            for j in range(i + 1, len(nbs)):
                if nbs[j] not in ni:
                    cnt += 1
        return cnt

    heap = [(fill_count(u), len(adj[u]), u) for u in adj]
    heapq.heapify(heap)
    alive = set(adj)
    width = 0
    while alive:
        fc, deg, u = heapq.heappop(heap)
        if u not in alive:
            continue
        cur_deg = len(adj[u])
        if cur_deg != deg:
            heapq.heappush(heap, (fill_count(u), cur_deg, u))
            continue
        cur_fc = fill_count(u)
        if cur_fc != fc:
            heapq.heappush(heap, (cur_fc, cur_deg, u))
            continue
        if cur_deg > width:
            width = cur_deg
            if width > max_width:
                return width
        nbs = list(adj[u])
        alive.remove(u)
        for x in nbs:
            adj[x].discard(u)
        for i in range(len(nbs)):
            xi = nbs[i]
            for j in range(i + 1, len(nbs)):
                xj = nbs[j]
                adj[xi].add(xj)
                adj[xj].add(xi)
        for x in nbs:
            heapq.heappush(heap, (fill_count(x), len(adj[x]), x))
    return width


def _connected_components(parents: dict[str, list[str]]) -> list[int]:
    adj: dict[str, set[str]] = {v: set() for v in parents}
    for v, pvs in parents.items():
        for p in pvs:
            adj[v].add(p)
            adj[p].add(v)
    seen: set[str] = set()
    sizes: list[int] = []
    for v in parents:
        if v in seen:
            continue
        stack = [v]
        seen.add(v)
        cnt = 0
        while stack:
            cur = stack.pop()
            cnt += 1
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        sizes.append(cnt)
    sizes.sort(reverse=True)
    return sizes


def build_structure(variables: list[Variable], tw: TrialWeights, max_width: int, log):
    """Build domain-causal, zero-backwards, treewidth-bounded DAG structure.

    Key design invariants:
      1. Every edge (u -> v) satisfies u.year <= v.year (ZERO backwards-in-time edges)
         and CAUSAL_RANK[u.slug] <= CAUSAL_RANK[v.slug] (strict DAG by construction).
      2. Within-family implication lattices guarantee 0 temporal and 0 threshold leaks.
         - auto_goods is oriented top-down (full_auto -> t3 -> t2 -> t1 -> t0) so
           full_auto => auto_goods_t3 has no collider blocking propagation.
         - gwp_growth (non-monotone single-year) attaches directly under
           gwp_growth_max_tK_by_Y (same year) with no horizontal year edges, keeping
           the GWP lattice width <= 4 and preventing forced-yes inflation.
      3. All 4 cross-metric exact logical implications are verified against raw MC
         (0 trial violations) and wired directly as structural implication edges.
      4. Cross-metric coupling uses a 2-hub forward-in-time leading-indicator
         separator from auto_rnd / full_auto_rnd into all downstream families
         (sub_agi, agi, full_auto, auto_goods, gwp_growth_max) plus a forward-in-time
         upstream infrastructure causal chain (gwp_compute -> hw_ratio -> sw_ratio
         -> train_run -> auto_rnd), uniting all 12 families into 1 connected
         component within treewidth <= max_width.
    """
    by_key = {(v.slug, v.thr_idx, v.year): v for v in variables}
    by_vid = {v.vid: v for v in variables}
    parents: dict[str, list[str]] = {v.vid: [] for v in variables}
    # implication pairs (a, b) mean: a=yes => b=yes (equivalently b=no => a=no).
    implication: set[tuple[str, str]] = set()

    def prev_year_var(v: Variable):
        for back in range(1, 5):
            u = by_key.get((v.slug, v.thr_idx, v.year - back))
            if u:
                return u
        return None

    def lower_thr_var(v: Variable):
        for down in range(1, 4):
            u = by_key.get((v.slug, v.thr_idx - down, v.year))
            if u:
                return u
        return None

    def higher_thr_var(v: Variable):
        for up in range(1, 4):
            u = by_key.get((v.slug, v.thr_idx + up, v.year))
            if u:
                return u
        return None

    # 1. Within-family implication lattices
    for v in variables:
        if v.slug == "auto_goods":
            hi = higher_thr_var(v)
            if hi is not None:
                parents[v.vid].append(hi.vid)
                implication.add((hi.vid, v.vid))  # higher thr yes => lower thr yes
        else:
            low = lower_thr_var(v)
            if low is not None:
                parents[v.vid].append(low.vid)
                implication.add((v.vid, low.vid))  # higher thr yes => lower thr yes

        if not v.spec.get("in_year"):
            prev = prev_year_var(v)
            if prev is not None:
                parents[v.vid].append(prev.vid)
                implication.add((prev.vid, v.vid))  # prev year yes => curr year yes

    # 2. Exact cross-metric implications (verified 0 violations in raw MC)
    cross_imp_added = 0
    for sub_s, sub_t, sup_s, sup_t, orient in CROSS_METRIC_IMPLICATIONS:
        for y in YEARS:
            u_sub = by_key.get((sub_s, sub_t, y))
            u_sup = by_key.get((sup_s, sup_t, y))
            if u_sub is None or u_sup is None:
                continue
            viol = popcount(u_sub.mask & ~u_sup.mask)
            if viol != 0:
                raise SystemExit(
                    f"Cross-metric implication {u_sub.vid} => {u_sup.vid} violated "
                    f"in {viol} raw MC trials!"
                )
            if orient == "sup_parent":
                if u_sup.vid not in parents[u_sub.vid]:
                    parents[u_sub.vid].append(u_sup.vid)
                    implication.add((u_sub.vid, u_sup.vid))
                    cross_imp_added += 1
            else:
                if u_sub.vid not in parents[u_sup.vid]:
                    parents[u_sup.vid].append(u_sub.vid)
                    implication.add((u_sub.vid, u_sup.vid))
                    cross_imp_added += 1
    log(f"exact cross-metric implication edges added: {cross_imp_added}")

    def check_width(ps: dict[str, list[str]]) -> bool:
        if _min_fill_width(ps, max_width) > max_width:
            return False
        nodes = _nodes_stub(variables, ps)
        try:
            FactoredMarket.from_nodes(nodes, 300.0, max_width)
            return True
        except JointMarketError:
            return False

    if not check_width(parents):
        raise SystemExit("implication lattice + exact cross-implications exceed width budget")

    # 3. Domain-causal 2-hub forward-in-time separator from R&D automation to all
    #    downstream takeoff/economic families. Selecting two chronological boundary
    #    hubs keeps treewidth <= 8 while propagating strong conditional shifts across
    #    all thresholds of sub_agi, agi, full_auto, auto_goods, and gwp_growth_max.
    downstream_targets = [
        ("sub_agi", 0), ("agi", 0), ("full_auto", 0),
        ("auto_goods", 0), ("auto_goods", 1), ("auto_goods", 2), ("auto_goods", 3),
        ("gwp_growth_max", 0), ("gwp_growth_max", 1), ("gwp_growth_max", 2),
    ]

    # Pick 3 chronological phase hubs across the 2027-2035 short-timelines horizon:
    #   early (auto_rnd t1 ~2029) -> 2029..2031
    #   mid   (full_auto_rnd ~2032) -> 2032..2033
    #   late  (full_auto_rnd ~2034) -> 2034..2035
    # Disjoint year slices keep parents <= 3 and treewidth <= 8 while giving
    # strong causal lifts from both ftm_agi_by_2032 and ftm_agi_by_2035.
    early_hub = by_key.get(("auto_rnd", 1, 2029)) or next(
        (v for v in sorted(variables, key=lambda x: x.year)
         if v.slug == "auto_rnd" and v.thr_idx in (0, 1) and v.sample_p >= 0.20),
        None,
    )
    mid_hub = by_key.get(("full_auto_rnd", 0, 2032)) or next(
        (v for v in sorted(variables, key=lambda x: x.year)
         if v.slug == "full_auto_rnd" and v.thr_idx == 0 and v.year >= 2031 and v.sample_p >= 0.20),
        None,
    )
    late_hub = by_key.get(("full_auto_rnd", 0, 2034)) or next(
        (v for v in sorted(variables, key=lambda x: x.year)
         if v.slug == "full_auto_rnd" and v.thr_idx == 0 and v.year >= 2033 and v.sample_p >= 0.40),
        None,
    )

    ordered_hubs: list[Variable] = []
    for h in (early_hub, mid_hub, late_hub):
        if h is not None and (not ordered_hubs or h.year > ordered_hubs[-1].year):
            ordered_hubs.append(h)

    hub_blocks: list[tuple[Variable, list[int]]] = []
    for idx, hub in enumerate(ordered_hubs):
        nxt_year = ordered_hubs[idx + 1].year if idx + 1 < len(ordered_hubs) else (max(YEARS) + 1)
        hub_blocks.append((hub, [y for y in YEARS if hub.year <= y < nxt_year]))

    cross_added = 0
    for hub, target_years in hub_blocks:
        trial_all = {k: list(ps) for k, ps in parents.items()}
        proposed = 0
        for dy in target_years:
            assert hub.year <= dy
            for ds, dt in downstream_targets:
                assert CAUSAL_RANK[hub.slug] < CAUSAL_RANK[ds]
                v = by_key.get((ds, dt, dy))
                if v is not None and hub.vid not in trial_all[v.vid] and len(trial_all[v.vid]) < 3:
                    trial_all[v.vid].append(hub.vid)
                    proposed += 1
        if proposed and check_width(trial_all):
            parents = trial_all
            cross_added += proposed
        else:
            for dy in target_years:
                for ds, dt in downstream_targets:
                    v = by_key.get((ds, dt, dy))
                    if v is None or hub.vid in parents[v.vid] or len(parents[v.vid]) >= 3:
                        continue
                    trial = {k: list(ps) for k, ps in parents.items()}
                    trial[v.vid].append(hub.vid)
                    if check_width(trial):
                        parents = trial
                        cross_added += 1

    # 4. Upstream infrastructure causal chain:
    #    gwp_compute -> hw_ratio -> sw_ratio -> train_run -> auto_rnd
    #    All strictly forward-in-time (u.year <= v.year) and forward in CAUSAL_RANK.
    upstream_specs = [
        ("gwp_compute", 0, 2029, "hw_ratio", 0, range(2029, 2036)),
        ("gwp_compute", 1, 2030, "hw_ratio", 1, range(2030, 2036)),
        ("gwp_compute", 0, 2029, "train_run", 0, range(2029, 2033)),
        ("gwp_compute", 1, 2030, "train_run", 2, range(2030, 2036)),
        ("hw_ratio", 0, 2029, "sw_ratio", 0, range(2029, 2036)),
        ("hw_ratio", 1, 2030, "sw_ratio", 1, range(2030, 2036)),
        ("sw_ratio", 0, 2029, "train_run", 1, range(2029, 2035)),
        ("sw_ratio", 1, 2030, "train_run", 2, range(2030, 2036)),
        ("train_run", 1, 2030, "auto_rnd", 0, range(2030, 2036)),
        ("train_run", 2, 2032, "auto_rnd", 1, range(2032, 2036)),
    ]
    for ss, st, sy, ds, dt, dys in upstream_specs:
        assert CAUSAL_RANK[ss] < CAUSAL_RANK[ds]
        u = by_key.get((ss, st, sy))
        if u is None:
            # Fallback to nearest available year <= min(dys) in same (slug, thr)
            avail = [v for v in variables if v.slug == ss and v.thr_idx == st and v.year <= min(dys)]
            u = max(avail, key=lambda x: x.year) if avail else None
        if u is None:
            continue
        trial_block = {k: list(ps) for k, ps in parents.items()}
        block_cnt = 0
        for dy in dys:
            if u.year > dy:
                continue
            v = by_key.get((ds, dt, dy))
            if v is not None and u.vid not in trial_block[v.vid] and len(trial_block[v.vid]) < 3:
                trial_block[v.vid].append(u.vid)
                block_cnt += 1
        if block_cnt and check_width(trial_block):
            parents = trial_block
            cross_added += block_cnt
        else:
            for dy in dys:
                if u.year > dy:
                    continue
                v = by_key.get((ds, dt, dy))
                if v is None or u.vid in parents[v.vid] or len(parents[v.vid]) >= 3:
                    continue
                trial = {k: list(ps) for k, ps in parents.items()}
                trial[v.vid].append(u.vid)
                if check_width(trial):
                    parents = trial
                    cross_added += 1

    # Verify strict causal + temporal invariants on every edge
    for child, pvs in parents.items():
        vc = by_vid[child]
        for pid in pvs:
            vp = by_vid[pid]
            assert vp.year <= vc.year, f"Backwards edge {pid} ({vp.year}) -> {child} ({vc.year})"
            assert CAUSAL_RANK[vp.slug] <= CAUSAL_RANK[vc.slug], (
                f"Anti-causal edge {pid} ({vp.slug}) -> {child} ({vc.slug})"
            )

    comps = _connected_components(parents)
    log(f"cross-metric causal edges added: {cross_added}; connected components: {comps}")
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


def fit_cpts(variables: list[Variable], parents: dict[str, list[str]],
             implication: set[tuple[str, str]], tw: TrialWeights):
    """Fit weighted CPTs with exact implication constraints.

    Bug fix: forced_zero and forced_one are tracked explicitly, and forced_zero
    STRICTLY takes precedence over forced_one so contradictory parent rows
    (which have zero probability mass in any coherent parent distribution) can
    never force 1.0 when a subset implication requires 0.0.
    """
    by_vid = {v.vid: v for v in variables}
    nodes = []
    low_support = 0
    full = tw.full_mask
    ess = tw.ess

    for v in variables:
        pv = parents[v.vid]
        cross_parents = [pid for pid in pv if by_vid[pid].slug != v.slug]
        prev_parent = next(
            (pid for pid in pv
             if by_vid[pid].slug == v.slug
             and by_vid[pid].thr_idx == v.thr_idx
             and by_vid[pid].year < v.year),
            None,
        )
        if prev_parent is not None:
            no_prev_mask = full ^ by_vid[prev_parent].mask
            w_no_prev = tw.prob(no_prev_mask)
            prior_np = (tw.prob(no_prev_mask & v.mask) / w_no_prev) if w_no_prev > 1e-12 else v.sample_p
        else:
            prior_np = v.sample_p

        rows = {}
        for combo in range(1 << len(pv)):
            ctx_mask = full
            key_pairs = []
            for j, pid in enumerate(pv):
                bit = (combo >> j) & 1
                pmask = by_vid[pid].mask
                ctx_mask &= pmask if bit else (full ^ pmask)
                key_pairs.append((pid, "yes" if bit else "no"))
            key = frozenset(key_pairs)

            # Exact implication rows: forced_zero strictly overrides forced_one
            forced_zero = any(
                (v.vid, pid) in implication and outcome == "no"
                for pid, outcome in key_pairs
            )
            forced_one = any(
                (pid, v.vid) in implication and outcome == "yes"
                for pid, outcome in key_pairs
            )
            if forced_zero:
                p = 0.0
            elif forced_one:
                p = 1.0
            else:
                ctx_eff = tw.prob(ctx_mask) * ess
                yes_eff = tw.prob(ctx_mask & v.mask) * ess

                # Context-aware fallback prior: condition on cross-metric parent(s)
                # when a joint cell is sparse, rather than shrinking to unconditional
                # marginals (which would erase cross-metric coupling).
                base_prior = prior_np if prev_parent is not None else v.sample_p
                if cross_parents:
                    cm_cross = full
                    for pid, outcome in key_pairs:
                        if pid in cross_parents:
                            pmask = by_vid[pid].mask
                            cm_cross &= pmask if outcome == "yes" else (full ^ pmask)
                    wc = tw.prob(cm_cross)
                    if wc > 1e-12:
                        p_cross = tw.prob(cm_cross & v.mask) / wc
                        if p_cross > 0.90 or p_cross < 0.10 or ctx_eff < 0.5:
                            base_prior = p_cross

                p_hat = (yes_eff + SMOOTH * base_prior) / (ctx_eff + SMOOTH) if ctx_eff > 0 else base_prior
                lam = ctx_eff / (ctx_eff + SHRINK_N)
                p = lam * p_hat + (1.0 - lam) * base_prior
                if ctx_eff < MIN_EFF_SIDE:
                    low_support += 1
                p = min(max(p, 0.0005), 0.9995)
            rows[key] = {"yes": round(p, 6), "no": round(1.0 - p, 6)}
        nodes.append({
            "variable_id": v.vid, "outcomes": ("yes", "no"),
            "parents": tuple(pv), "rows": rows,
        })
    return nodes, low_support


def measure_violations(market: FactoredMarket, variables: list[Variable]):
    """Check ALL within-family temporal, within-family threshold, and cross-metric leaks."""
    worst: list[tuple[float, str, str, str]] = []
    by_key = {(v.slug, v.thr_idx, v.year): v for v in variables}

    # 1. Within-family temporal monotonicity: v_Y = yes => v_(Y+1) = yes
    for v in variables:
        if not v.spec.get("in_year"):
            nxt = by_key.get((v.slug, v.thr_idx, v.year + 1))
            if nxt is not None:
                cond = market.marginal(nxt.vid, {v.vid: "yes"})
                if cond is not None and cond["no"] > 1e-12:
                    worst.append((cond["no"], v.vid, nxt.vid, "temporal"))

        # 2. Within-family threshold monotonicity: v_tK_Y = yes => v_t(K-1)_Y = yes
        if v.thr_idx is not None and v.thr_idx > 0:
            low = by_key.get((v.slug, v.thr_idx - 1, v.year))
            if low is not None:
                cond = market.marginal(low.vid, {v.vid: "yes"})
                if cond is not None and cond["no"] > 1e-12:
                    worst.append((cond["no"], v.vid, low.vid, "threshold"))

    # 3. Cross-metric logical implications: sub = yes => sup = yes
    for sub_s, sub_t, sup_s, sup_t, _ in CROSS_METRIC_IMPLICATIONS:
        for y in YEARS:
            u_sub = by_key.get((sub_s, sub_t, y))
            u_sup = by_key.get((sup_s, sup_t, y))
            if u_sub is None or u_sup is None:
                continue
            cond = market.marginal(u_sup.vid, {u_sub.vid: "yes"})
            if cond is not None and cond["no"] > 1e-12:
                worst.append((cond["no"], u_sub.vid, u_sup.vid, "cross_metric"))

    worst.sort(reverse=True)
    return worst


def _topo_levels(nodes) -> list[list[str]]:
    parents_of = {n["variable_id"]: set(n["parents"]) for n in nodes}
    levels: list[list[str]] = []
    pending = dict(parents_of)
    while pending:
        ready = sorted(v for v, deps in pending.items() if not deps & set(pending))
        if not ready:
            raise SystemExit("cycle in compiled structure")
        levels.append(ready)
        for v in ready:
            del pending[v]
    return levels


def calibrate_marginals(nodes, variables, max_width):
    """Exact topological-level calibration (one Gauss-Seidel sweep by DAG depth).

    Nodes in the same topological level have all their parents strictly in earlier
    levels, so their parent-context distributions are mutually independent of each
    other's CPT updates. Rebuilding FactoredMarket once per DAG level (~35 rebuilds
    vs 549) is mathematically identical to node-by-node calibration and ~15x faster.
    """
    def logit(p):
        return math.log(p / (1.0 - p))

    def sigmoid(x):
        return 1.0 / (1.0 + math.exp(-x))

    by_vid = {v.vid: (v, node) for v, node in zip(variables, nodes)}
    levels = _topo_levels(nodes)
    market = FactoredMarket.from_nodes(nodes, 300.0, max_width)
    worst = 0.0

    for lvl in levels:
        changed = False
        for vid in lvl:
            v, node = by_vid[vid]
            target = min(max(v.sample_p, 0.002), 0.998)
            parent_ids = sorted({p for key in node["rows"] for p, _ in key})
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
            forced_yes = sum(
                p for key, p in ctx_probs.items() if node["rows"][key]["yes"] >= 1.0
            )
            free = [
                (key, p) for key, p in ctx_probs.items()
                if 0.0 < node["rows"][key]["yes"] < 1.0 and p > 0.0
            ]

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
                    mid = (lo + hi) / 2.0
                    if implied_at(mid) < target:
                        lo = mid
                    else:
                        hi = mid
                d = (lo + hi) / 2.0
            worst = max(worst, abs(implied_at(d) - target))
            if abs(d) > 1e-9:
                for key, _ in free:
                    q = min(max(node["rows"][key]["yes"], 0.0005), 0.9995)
                    q2 = min(max(sigmoid(logit(q) + d), 0.0005), 0.9995)
                    node["rows"][key]["yes"] = round(q2, 6)
                    node["rows"][key]["no"] = round(1.0 - q2, 6)
                changed = True
        if changed:
            market = FactoredMarket.from_nodes(nodes, 300.0, max_width)
    return market, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--max-width", type=int, default=8)
    ap.add_argument("--liquidity", type=float, default=10000.0)
    ap.add_argument("--id-prefix", default="f")
    ap.add_argument(
        "--late-2026-weights",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply Bayesian importance weights calibrated to late-2026 reality (default: enabled)",
    )
    args = ap.parse_args()

    export = Path(args.export_dir).expanduser()
    manifest = json.loads((export / "manifest.json").read_text())
    series = load_series(export / "mc_series.csv")
    trial_ids, scalar_cols = load_metrics(export / "mc_metrics.csv")
    n = len(trial_ids)
    print(f"trials: {n}; series metrics: {sorted(series)}")

    def log(msg):
        print(f"[compile] {msg}")

    if args.late_2026_weights:
        tw, weight_meta = compute_late_2026_weights(series, scalar_cols, trial_ids)
        method_tag = "mc-threshold-grid-v2-weighted"
        log(f"late-2026 importance weights enabled: ESS = {tw.ess:.2f} / {n}")
    else:
        tw = TrialWeights([1.0] * n)
        weight_meta = {"enabled": False, "calibrationDate": CALIBRATION_DATE, "ess": float(n)}
        method_tag = "mc-threshold-grid-v2"
        log(f"uniform trial weights: ESS = {tw.ess:.2f} / {n}")

    variables, dropped = build_variables(series, scalar_cols, trial_ids, tw)
    log(f"variables kept: {len(variables)}; dropped: {dropped}")

    parents, implication = build_structure(variables, tw, args.max_width, log)
    nodes, low_support = fit_cpts(variables, parents, implication, tw)
    log(f"CPT rows with low support: {low_support}")

    market = FactoredMarket.from_nodes(nodes, 300.0, args.max_width)
    stats = market.stats()
    log(f"net: width={stats['treewidth']:.0f} cliques={stats['cliqueCount']:.0f}")

    violations = measure_violations(market, variables)
    max_leak = violations[0][0] if violations else 0.0
    log(f"pre-calibration max residual implication leak: {max_leak:.6f} ({len(violations)} pairs)")

    market, worst_after_cal = calibrate_marginals(nodes, variables, args.max_width)
    log(f"marginal calibration: worst |implied - sample| = {worst_after_cal:.6f}")

    # Structure repair (only if any node is > 0.03 off; strictly forward in time & causal order)
    by_vid = {v.vid: v for v in variables}

    def ancestors(vid, ps):
        out, stack = set(), list(ps[vid])
        while stack:
            u = stack.pop()
            if u not in out:
                out.add(u)
                stack.extend(ps[u])
        return out

    for round_ in range(3):
        residuals = sorted(
            ((abs(market.marginal(v.vid, None)["yes"] - v.sample_p), v) for v in variables),
            reverse=True,
            key=lambda t: t[0],
        )
        stuck = [(r, v) for r, v in residuals if r > 0.03][:12]
        if not stuck:
            break
        changed = False
        for _, v in stuck:
            if len(parents[v.vid]) >= 4:
                continue
            cands = sorted(
                (u for u in variables
                 if u.vid != v.vid and u.vid not in parents[v.vid]
                 and u.year <= v.year
                 and CAUSAL_RANK[u.slug] <= CAUSAL_RANK[v.slug]
                 and v.vid not in ancestors(u.vid, parents)),
                key=lambda u: -tw.mutual_information(v.mask, u.mask),
            )[:4]
            for u in cands:
                trial_parents = {k: list(ps) for k, ps in parents.items()}
                trial_parents[v.vid].append(u.vid)
                if _min_fill_width(trial_parents, args.max_width) > args.max_width:
                    continue
                trial_nodes, _ = fit_cpts(variables, trial_parents, implication, tw)
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
        log(f"calibration repair round {round_ + 1}: worst residual = {worst_after_cal:.6f}")

    post_leak = measure_violations(market, variables)
    max_leak = max(max_leak, post_leak[0][0] if post_leak else 0.0)
    log(f"post-calibration max residual implication leak: {max_leak:.6f} ({len(post_leak)} pairs)")
    if max_leak > 1e-9:
        raise SystemExit(f"ABORT: non-zero residual implication leak {max_leak}: {post_leak[:5]}")

    stats = market.stats()
    comps = _connected_components(parents)

    # Emit seeds-v1 JSON
    created = f"{CALIBRATION_DATE}T00:00:00Z" if args.late_2026_weights else manifest.get("timestamp", "2026-07-04T00:00:00Z")
    markets = {}
    conditional = {}
    proj_deltas = []
    for i, (v, node) in enumerate(zip(variables, nodes), start=1):
        mid = f"{args.id_prefix}{i:04d}"
        implied = market.marginal(v.vid, None)["yes"]
        proj_deltas.append(abs(implied - v.sample_p))
        if args.late_2026_weights:
            prior_note = (
                f"Prior from the FTM Monte Carlo ({manifest.get('n_trials', n)} trials, "
                f"late-2026 Bayesian importance reweighting as of {CALIBRATION_DATE}, "
                f"ESS {tw.ess:.1f}): {v.sample_p:.1%}."
            )
        else:
            prior_note = (
                f"Prior from the FTM Monte Carlo ({manifest.get('n_trials', n)} trials, "
                f"{manifest.get('parameter_table', 'observed_2026-06-28')}): {v.sample_p:.1%}."
            )
        prov = {
            "source": "ftm",
            "method": method_tag,
            "calibration": manifest.get("parameter_table", "observed_2026-06-28"),
            "calibrationDate": CALIBRATION_DATE,
            "trials": n,
            "ess": round(tw.ess, 2),
            "sampleMarginal": round(v.sample_p, 6),
            "metric": v.metric,
        }
        markets[mid] = {
            "id": mid,
            "title": v.title,
            "description": f"{v.title}. {resolution_text(v)} {prior_note}",
            "variableId": v.vid,
            "status": "active",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "marginals": {"yes": round(implied, 6), "no": round(1.0 - implied, 6)},
            "liquidity": args.liquidity,
            "volume": 0.0,
            "created_at": created,
            "expires_at": f"{v.year}-12-31T23:59:59Z",
            "ftmImplied": round(implied, 6),
            "provenance": prov,
        }
        if parents[v.vid]:
            rows = {}
            for key, row in node["rows"].items():
                ctx = "|".join(f"{pid}={out}" for pid, out in sorted(key))
                rows[ctx] = row
            conditional[mid] = rows

    seeds = {"version": "seeds-v1", "markets": markets, "conditionalMarginals": conditional}
    Path(args.out).write_text(json.dumps(seeds, indent=1) + "\n")

    # Summary conditional propagation diagnostics (both 2035 and 2032 AGI anchors)
    lifts_2035 = {}
    if "ftm_agi_by_2035" in by_vid:
        for tgt in (
            "ftm_auto_goods_t3_by_2035",
            "ftm_auto_rnd_t3_by_2035",
            "ftm_gwp_growth_max_t1_by_2035",
            "ftm_sub_agi_by_2032",
        ):
            if tgt in by_vid:
                py = market.marginal(tgt, {"ftm_agi_by_2035": "yes"})["yes"]
                pn = market.marginal(tgt, {"ftm_agi_by_2035": "no"})["yes"]
                lifts_2035[tgt] = {"given_yes": round(py, 4), "given_no": round(pn, 4), "lift": round(py - pn, 4)}

    lifts_2032 = {}
    if "ftm_agi_by_2032" in by_vid:
        for tgt in (
            "ftm_auto_goods_t3_by_2032",
            "ftm_auto_rnd_t3_by_2032",
            "ftm_gwp_growth_max_t1_by_2032",
            "ftm_sub_agi_by_2030",
        ):
            if tgt in by_vid:
                py = market.marginal(tgt, {"ftm_agi_by_2032": "yes"})["yes"]
                pn = market.marginal(tgt, {"ftm_agi_by_2032": "no"})["yes"]
                lifts_2032[tgt] = {"given_yes": round(py, 4), "given_no": round(pn, 4), "lift": round(py - pn, 4)}

    report = {
        "variables": len(variables),
        "horizon": [min(YEARS), max(YEARS)],
        "dropped": dropped,
        "edges": sum(len(p) for p in parents.values()),
        "implicationEdges": len(implication),
        "connectedComponents": comps,
        "treewidth": stats["treewidth"],
        "cliqueCount": stats["cliqueCount"],
        "maxResidualLeak": max_leak,
        "maxProjectionDelta": round(max(proj_deltas), 6) if proj_deltas else 0.0,
        "meanProjectionDelta": round(sum(proj_deltas) / len(proj_deltas), 6) if proj_deltas else 0.0,
        "lowSupportRows": low_support,
        "trials": n,
        "method": method_tag,
        "weighting": weight_meta,
        "agi2035ConditionalLifts": lifts_2035,
        "agi2032ConditionalLifts": lifts_2032,
    }
    Path(args.report).write_text(json.dumps(report, indent=1) + "\n")
    log(f"wrote {args.out} ({len(markets)} markets) and {args.report}")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
