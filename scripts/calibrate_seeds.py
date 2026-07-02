"""Generate backend/seed_calibration.json: priors calibrated to public forecasts.

Method: targets below come from live Metaculus/Manifold forecasts retrieved
2026-07-02 (close analogs only; loose analogs keep the house prior). Every
market keeps its CPT *structure*; each family's rows are shifted by a single
log-odds constant so the joint-implied marginal hits the target, processed in
topological order so parent distributions are already calibrated. Association
strengths (row-to-row spreads in log-odds) are preserved exactly.

Run from the repo root: python3 scripts/calibrate_seeds.py
"""

import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("srv", "backend/server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

from backend.inference import build_market_network  # noqa: E402
from backend.inference.network_model import parse_cpt_key  # noqa: E402

MARKETS = {mid: dict(m) for mid, m in srv.MARKETS.items()}
CPTS = {mid: {k: dict(v) for k, v in rows.items()} for mid, rows in srv.CONDITIONAL_MARGINALS.items()}

# Evidence-backed targets (see attribution). Markets absent here keep their
# current joint-implied marginal.
TARGETS = {
    "m16": 0.82,  # industry buildout baselines put 50 GW at/below trend
    "m4": 0.60,   # Manifold 1e27-FLOP-by-2030 ~93%, Metaculus #30336 ~77% (weaker thresholds)
    "m9": 0.78,   # Manifold open-weight gap ~86%; Metaculus #19300 resolved YES
    "m6": 0.45,   # Metaculus incident ladder: #7814 ~76%, #21553 ~40% (by 2032)
    "m12": 0.27,  # Manifold "ASI before 2033" ~27%
    "m13": 0.10,  # Metaculus US-China treaty #39149/#38418 ~4%; moratorium ~22%
}

ATTRIBUTION = {
    "m16": "Prior calibrated Jul 2026 to industry buildout baselines (Goldman Sachs ~134 GW US data-center demand by 2030; McKinsey ~156 GW AI capacity).",
    "m4": "Prior informed Jul 2026 by Metaculus #30336 (~77%) and a Manifold 10^27-FLOP-by-2030 analog (~93%), both weaker thresholds than 100x.",
    "m9": "Prior calibrated Jul 2026 to open-weight frontier-gap analogs (Manifold ~86%; Metaculus #19300 resolved YES for Jan 2025).",
    "m6": "Prior calibrated Jul 2026 to the Metaculus AI-incident ladder (#7814 ~76% and #21553 ~40%, both by 2032).",
    "m12": "Prior calibrated Jul 2026 to Manifold 'ASI before 2033' (~27%).",
    "m13": "Prior calibrated Jul 2026 to Metaculus US-China AI-treaty forecasts (#39149, #38418, ~4%) and a Manifold moratorium analog (~22%).",
}

var_of = {mid: str(m["variableId"]) for mid, m in MARKETS.items()}
mid_of = {v: k for k, v in var_of.items()}

model0 = build_market_network(MARKETS, CPTS)
for mid in MARKETS:
    if mid not in TARGETS:
        TARGETS[mid] = model0.marginal(var_of[mid], {})["yes"]


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


parents: dict[str, list[str]] = {}
for mid, rows in CPTS.items():
    variables: set[str] = set()
    for key in rows:
        variables.update(v for v, _ in (parse_cpt_key(key) or ()))
    parents[mid] = sorted(variables)

order: list[str] = []
placed: set[str] = set()
while len(order) < len(MARKETS):
    progressed = False
    for mid in sorted(MARKETS, key=lambda x: int(x[1:])):
        if mid in placed:
            continue
        if all(mid_of[p] in placed for p in parents.get(mid, [])):
            order.append(mid)
            placed.add(mid)
            progressed = True
    if not progressed:
        raise SystemExit("cycle in seed CPTs")

report = []
for mid in order:
    target = TARGETS[mid]
    if mid not in CPTS:
        MARKETS[mid]["marginals"] = {"yes": round(target, 4), "no": round(1 - round(target, 4), 4)}
        report.append((mid, target, target, "root"))
        continue

    pvars = parents[mid]
    model = build_market_network(MARKETS, CPTS)
    combos = []
    for combo in itertools.product(["yes", "no"], repeat=len(pvars)):
        weight = 1.0
        evidence: dict[str, str] = {}
        for variable, outcome in zip(pvars, combo):
            weight *= model.marginal(variable, evidence)[outcome]
            evidence[variable] = outcome
        combos.append((frozenset(zip(pvars, combo)), weight))

    rows = CPTS[mid]
    canon = {frozenset(parse_cpt_key(k) or ()): row for k, row in rows.items()}

    def implied(delta: float) -> float:
        return sum(w * sigmoid(logit(canon[a]["yes"]) + delta) for a, w in combos)

    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid_delta = (lo + hi) / 2
        if implied(mid_delta) < target:
            lo = mid_delta
        else:
            hi = mid_delta
    delta = (lo + hi) / 2

    CPTS[mid] = {
        key: {
            "yes": round(sigmoid(logit(row["yes"]) + delta), 4),
            "no": round(1 - round(sigmoid(logit(row["yes"]) + delta), 4), 4),
        }
        for key, row in rows.items()
    }
    achieved = build_market_network(MARKETS, CPTS).marginal(var_of[mid], {})["yes"]
    report.append((mid, target, achieved, f"delta={delta:+.3f}"))

out = {
    "generated": "2026-07-02",
    "method": "log-odds shift per CPT family, fitted in topological order",
    "rootMarginals": {mid: MARKETS[mid]["marginals"] for mid in MARKETS if mid not in CPTS},
    "conditionalMarginals": CPTS,
    "attribution": ATTRIBUTION,
}
Path("backend/seed_calibration.json").write_text(json.dumps(out, indent=1, sort_keys=True))

print(f"{'mid':4} {'target':>8} {'achieved':>9}")
for mid, target, achieved, note in report:
    flag = " <-- off" if abs(target - achieved) > 0.005 else ""
    print(f"{mid:4} {target:8.4f} {achieved:9.4f}  {note}{flag}")
print("WROTE backend/seed_calibration.json")
