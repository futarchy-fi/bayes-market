"""Automated world-model invariants for the compiled AI Futures Bayesian Network.

Guards backend/seeds_takeoff.json, backend/seeds_external.json, and
scripts/import/data/anchors.json against structural, logical, temporal,
calibration, and anchor regressions.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from backend.inference.factored_market import FactoredMarket
from backend.inference.network_model import build_network_nodes

REPO_ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = REPO_ROOT / "backend" / "seeds_takeoff.json"
EXT_SEEDS_PATH = REPO_ROOT / "backend" / "seeds_external.json"
ANCHORS_PATH = REPO_ROOT / "scripts" / "import" / "data" / "anchors.json"

AS_OF_DATE = "2026-11-23"
MAX_TREEWIDTH = 8


def _parse_ftm_var(var_id: str) -> tuple[str, int, str, int] | None:
    """Parse ftm_<slug>[_t<k>]_(by|in)_<year> -> (slug, thr_idx, mode, year)."""
    m = re.match(r"^ftm_([a-z_]+?)_t(\d+)_(by|in)_(\d{4})$", var_id)
    if m:
        return m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    m = re.match(r"^ftm_([a-z_]+?)_(by|in)_(\d{4})$", var_id)
    if m:
        return m.group(1), 0, m.group(2), int(m.group(3))
    return None


def _extract_market_year(market: dict) -> int | None:
    """Return conservative causal year for any FTM or external market."""
    vid = str(market.get("variableId", ""))
    parsed = _parse_ftm_var(vid)
    if parsed is not None:
        return parsed[3]

    candidates: list[int] = []
    exp = str(market.get("expires_at", ""))
    if len(exp) >= 4 and exp[:4].isdigit():
        candidates.append(int(exp[:4]))

    title = str(market.get("title", ""))
    for m in re.finditer(r"\bbefore\s+(?:the\s+year\s+)?(20\d{2}|2100)\b", title, re.IGNORECASE):
        candidates.append(int(m.group(1)) - 1)
    for m in re.finditer(
        r"\b(?:by|in|end\s+of|eoy|oct|may|june\s+\d+,?)\s+(20\d{2}|2100)\b",
        title,
        re.IGNORECASE,
    ):
        candidates.append(int(m.group(1)))
    m_lead = re.match(r"^\s*(20\d{2})\b", title)
    if m_lead:
        candidates.append(int(m_lead.group(1)))

    future = [y for y in candidates if y >= 2027]
    return min(future) if future else (min(candidates) if candidates else None)


@pytest.fixture(scope="module")
def world_model():
    seeds = json.loads(SEEDS_PATH.read_text())
    markets = seeds["markets"]
    conds = seeds.get("conditionalMarginals", {})
    nodes = build_network_nodes(markets, conds)
    fm = FactoredMarket.from_nodes(nodes, 50.0, MAX_TREEWIDTH)
    by_var = {m["variableId"]: m for m in markets.values()}
    nodes_by_var = {n["variable_id"]: n for n in nodes}
    return {
        "seeds": seeds,
        "markets": markets,
        "conds": conds,
        "nodes": nodes,
        "fm": fm,
        "by_var": by_var,
        "nodes_by_var": nodes_by_var,
    }


def test_valid_dag_no_cycles_self_loops_or_dangling_refs(world_model):
    markets = world_model["markets"]
    nodes = world_model["nodes"]
    by_var = world_model["by_var"]

    # Unique variableIds across all markets
    assert len(by_var) == len(markets), "Duplicate variableId detected across markets"

    parents_of: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        vid = node["variable_id"]
        ps = tuple(node["parents"])
        assert vid not in ps, f"Self-loop on {vid}"
        for p in ps:
            assert p in by_var, f"Dangling parent reference {p} on {vid}"
        parents_of[vid] = ps

        # Every CPT row must be a valid probability distribution over yes/no
        for key, row in node["rows"].items():
            py, pn = row["yes"], row["no"]
            assert 0.0 <= py <= 1.0 and 0.0 <= pn <= 1.0, f"Invalid CPT prob on {vid} {key}: {row}"
            assert abs((py + pn) - 1.0) <= 1e-5, f"CPT row does not sum to 1 on {vid} {key}: {row}"

    # Kahn topological sort verifies strict DAG (0 cycles)
    in_deg = {v: len(ps) for v, ps in parents_of.items()}
    children = defaultdict(list)
    for v, ps in parents_of.items():
        for p in ps:
            children[p].append(v)
    queue = [v for v, d in in_deg.items() if d == 0]
    visited = 0
    while queue:
        u = queue.pop()
        visited += 1
        for c in children[u]:
            in_deg[c] -= 1
            if in_deg[c] == 0:
                queue.append(c)
    assert visited == len(parents_of), f"DAG cycle detected: visited {visited}/{len(parents_of)}"


def test_factored_market_treewidth_and_marginal_coherence(world_model):
    fm: FactoredMarket = world_model["fm"]
    markets = world_model["markets"]
    stats = fm.stats()
    assert stats["treewidth"] <= MAX_TREEWIDTH, f"Treewidth {stats['treewidth']} exceeds {MAX_TREEWIDTH}"

    # Every market's seed marginal must agree with the live FactoredMarket implied marginal
    max_delta = 0.0
    worst_vid = None
    for m in markets.values():
        vid = m["variableId"]
        implied = fm.marginal(vid)["yes"]
        delta = abs(implied - m["marginals"]["yes"])
        if delta > max_delta:
            max_delta = delta
            worst_vid = vid
    assert max_delta < 1e-4, f"Marginal drift {max_delta:.6f} on {worst_vid}"


def test_single_connected_component_zero_singletons(world_model):
    nodes = world_model["nodes"]
    adj: dict[str, set[str]] = {n["variable_id"]: set() for n in nodes}
    for n in nodes:
        v = n["variable_id"]
        for p in n["parents"]:
            adj[v].add(p)
            adj[p].add(v)

    singletons = [v for v, nbs in adj.items() if len(nbs) == 0]
    assert not singletons, f"Found {len(singletons)} isolated singleton(s): {singletons[:10]}"

    seen: set[str] = set()
    comp_sizes: list[int] = []
    for v in adj:
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
        comp_sizes.append(cnt)

    assert len(comp_sizes) == 1, f"Expected 1 connected component, got {len(comp_sizes)}: {sorted(comp_sizes, reverse=True)}"


def test_zero_within_family_temporal_and_threshold_leaks(world_model):
    fm: FactoredMarket = world_model["fm"]
    by_var = world_model["by_var"]

    ftm_grid: dict[tuple[str, int, str, int], str] = {}
    for vid in by_var:
        parsed = _parse_ftm_var(vid)
        if parsed is not None:
            ftm_grid[parsed] = vid

    temporal_leaks = []
    threshold_leaks = []
    marginal_inversions = []

    for (slug, thr, mode, year), vid in ftm_grid.items():
        p_cur = fm.marginal(vid)["yes"]

        # Monotone temporal monotonicity: v_Y = yes => v_(Y+1) = yes
        if mode == "by":
            nxt = ftm_grid.get((slug, thr, mode, year + 1))
            if nxt is not None:
                leak = fm.marginal(nxt, {vid: "yes"})["no"]
                if leak > 1e-9:
                    temporal_leaks.append((vid, nxt, leak))
                p_nxt = fm.marginal(nxt)["yes"]
                if p_cur > p_nxt + 1e-6:
                    marginal_inversions.append((vid, p_cur, nxt, p_nxt))

        # Threshold monotonicity: v_tK_Y = yes => v_t(K-1)_Y = yes
        if thr > 0:
            low = ftm_grid.get((slug, thr - 1, mode, year))
            if low is not None:
                leak = fm.marginal(low, {vid: "yes"})["no"]
                if leak > 1e-9:
                    threshold_leaks.append((vid, low, leak))
                p_low = fm.marginal(low)["yes"]
                if p_cur > p_low + 1e-6:
                    marginal_inversions.append((vid, p_cur, low, p_low))

    assert not temporal_leaks, f"Temporal implication leaks ({len(temporal_leaks)}): {temporal_leaks[:5]}"
    assert not threshold_leaks, f"Threshold implication leaks ({len(threshold_leaks)}): {threshold_leaks[:5]}"
    assert not marginal_inversions, f"Monotonicity marginal inversions: {marginal_inversions[:5]}"


def test_zero_cross_metric_logical_leaks(world_model):
    fm: FactoredMarket = world_model["fm"]
    by_var = world_model["by_var"]

    cross_pairs = [
        ("ftm_full_auto_by_", "ftm_auto_goods_t3_by_"),
        ("ftm_full_auto_rnd_by_", "ftm_auto_rnd_t3_by_"),
        ("ftm_agi_by_", "ftm_sub_agi_by_"),
        ("ftm_gwp_growth_t0_in_", "ftm_gwp_growth_max_t0_by_"),
        ("ftm_gwp_growth_t1_in_", "ftm_gwp_growth_max_t1_by_"),
        ("ftm_gwp_growth_t2_in_", "ftm_gwp_growth_max_t2_by_"),
        ("ftm_gwp_growth_t3_in_", "ftm_gwp_growth_max_t3_by_"),
    ]
    checked = 0
    leaks = []
    for sub_pref, sup_pref in cross_pairs:
        for year in range(2027, 2046):
            sub_v = f"{sub_pref}{year}"
            sup_v = f"{sup_pref}{year}"
            if sub_v in by_var and sup_v in by_var:
                checked += 1
                leak = fm.marginal(sup_v, {sub_v: "yes"})["no"]
                if leak > 1e-9:
                    leaks.append((sub_v, sup_v, leak))

    assert checked >= 100, f"Expected >=100 cross-metric implication pairs, only checked {checked}"
    assert not leaks, f"Cross-metric logical leaks ({len(leaks)}): {leaks[:5]}"


def test_zero_backwards_in_time_edges(world_model):
    by_var = world_model["by_var"]
    nodes = world_model["nodes"]

    backwards = []
    for node in nodes:
        child_vid = node["variable_id"]
        child_year = _extract_market_year(by_var[child_vid])
        if child_year is None:
            continue
        for parent_vid in node["parents"]:
            parent_year = _extract_market_year(by_var[parent_vid])
            if parent_year is not None and parent_year > child_year:
                backwards.append((parent_vid, parent_year, child_vid, child_year))

    assert not backwards, f"Backwards-in-time edges ({len(backwards)}): {backwards[:10]}"


def test_no_expired_markets_and_clean_formatting(world_model):
    markets = world_model["markets"]
    expired = []
    formatting = []

    for mid, m in markets.items():
        assert m.get("status") == "active", f"Non-active market {mid}: {m.get('status')}"
        exp = str(m.get("expires_at", ""))
        if exp[:10] <= AS_OF_DATE:
            expired.append((mid, exp, m.get("title")))
        title = str(m.get("title", ""))
        desc = str(m.get("description", ""))
        if ".." in desc or "?." in desc or "\u0391I" in title or "\u0391I" in desc:
            formatting.append((mid, title))

    assert not expired, f"Expired markets still active ({len(expired)}): {expired[:5]}"
    assert not formatting, f"Formatting defects ({len(formatting)}): {formatting[:5]}"


def test_strong_conditional_propagation_and_bridge_lifts(world_model):
    fm: FactoredMarket = world_model["fm"]
    markets = world_model["markets"]
    nodes_by_var = world_model["nodes_by_var"]

    # Core FTM cross-family propagation from ftm_agi_by_2040
    goods_lift = (
        fm.marginal("ftm_auto_goods_t3_by_2040", {"ftm_agi_by_2040": "yes"})["yes"]
        - fm.marginal("ftm_auto_goods_t3_by_2040", {"ftm_agi_by_2040": "no"})["yes"]
    )
    rnd_lift = (
        fm.marginal("ftm_auto_rnd_t3_by_2040", {"ftm_agi_by_2040": "yes"})["yes"]
        - fm.marginal("ftm_auto_rnd_t3_by_2040", {"ftm_agi_by_2040": "no"})["yes"]
    )
    gwp_lift = (
        fm.marginal("ftm_gwp_growth_max_t1_by_2040", {"ftm_agi_by_2040": "yes"})["yes"]
        - fm.marginal("ftm_gwp_growth_max_t1_by_2040", {"ftm_agi_by_2040": "no"})["yes"]
    )
    assert goods_lift >= 0.40, f"Weak goods-90% lift given AGI-2040: {goods_lift:.4f}"
    assert rnd_lift >= 0.40, f"Weak R&D-90% lift given AGI-2040: {rnd_lift:.4f}"
    assert gwp_lift >= 0.15, f"Weak GWP-10% lift given AGI-2040: {gwp_lift:.4f}"

    # Every external market must be bridged with meaningful lift >= 0.10
    ext_markets = {mid: m for mid, m in markets.items() if mid.startswith("x")}
    assert 50 <= len(ext_markets) <= 120, f"Unexpected external market count: {len(ext_markets)}"

    weak_bridges = []
    for mid, m in ext_markets.items():
        node = nodes_by_var[m["variableId"]]
        assert len(node["parents"]) >= 1, f"External market {mid} is unbridged"
        row_probs = [r["yes"] for r in node["rows"].values()]
        lift = max(row_probs) - min(row_probs)
        if lift < 0.10:
            weak_bridges.append((mid, lift))
    assert not weak_bridges, f"Weak external bridge CPTs (<0.10 lift): {weak_bridges[:10]}"

    # Semantic direction sanity checks (positive and negative bridges)
    if "x0072" in markets:  # AI winter before AGI (negative vs early AGI)
        v_winter = markets["x0072"]["variableId"]
        assert fm.marginal(v_winter, {"ftm_agi_by_2035": "yes"})["yes"] < fm.marginal(
            v_winter, {"ftm_agi_by_2035": "no"}
        )["yes"]
    if "x0216" in markets:  # Global AI pause before 2035 (negative vs AGI by 2035)
        v_pause = markets["x0216"]["variableId"]
        assert fm.marginal(v_pause, {"ftm_agi_by_2035": "yes"})["yes"] < fm.marginal(
            v_pause, {"ftm_agi_by_2035": "no"}
        )["yes"]
    if "x0103" in markets:  # AGI before 2040 (positive vs ftm_agi_by_2040)
        v_agi40_ext = markets["x0103"]["variableId"]
        assert fm.marginal(v_agi40_ext, {"ftm_agi_by_2040": "yes"})["yes"] > fm.marginal(
            v_agi40_ext, {"ftm_agi_by_2040": "no"}
        )["yes"] + 0.30


def test_late_2026_calibration_and_family_completeness(world_model):
    fm: FactoredMarket = world_model["fm"]
    by_var = world_model["by_var"]

    # Required families exist; redundant rampup / rampup_rnd are gone; no dropped AGI years
    assert "ftm_agi_by_2040" in by_var
    for y in range(2030, 2046):
        assert f"ftm_agi_by_{y}" in by_var, f"Missing ftm_agi_by_{y}"
    for y in range(2027, 2046):
        assert f"ftm_sub_agi_by_{y}" in by_var, f"Missing ftm_sub_agi_by_{y}"
    assert not any(v.startswith("ftm_rampup_") for v in by_var), "Redundant rampup family still present"

    # Late-2026 calibrated prior bands
    checks = [
        ("ftm_sub_agi_by_2028", 0.04, 0.12),
        ("ftm_sub_agi_by_2030", 0.18, 0.32),
        ("ftm_sub_agi_by_2035", 0.52, 0.68),
        ("ftm_sub_agi_by_2040", 0.78, 0.90),
        ("ftm_agi_by_2030", 0.02, 0.08),
        ("ftm_agi_by_2032", 0.12, 0.25),
        ("ftm_agi_by_2035", 0.40, 0.55),
        ("ftm_agi_by_2040", 0.70, 0.84),
        ("ftm_train_run_t0_by_2030", 0.70, 0.90),
        ("ftm_auto_rnd_t1_by_2030", 0.25, 0.45),
        ("ftm_auto_rnd_t1_by_2035", 0.62, 0.78),
    ]
    for vid, lo, hi in checks:
        p = fm.marginal(vid)["yes"]
        assert lo <= p <= hi, f"{vid} marginal {p:.4f} outside late-2026 band [{lo}, {hi}]"

    # Provenance records late-2026 weighting metadata
    agi_prov = by_var["ftm_agi_by_2040"]["provenance"]
    assert agi_prov["method"] == "mc-threshold-grid-v2-weighted"
    assert agi_prov["calibrationDate"] == AS_OF_DATE
    assert agi_prov["ess"] >= 350.0


def test_anchors_and_external_seeds_integrity(world_model):
    markets = world_model["markets"]
    ext_seeds = json.loads(EXT_SEEDS_PATH.read_text())["markets"]
    anchors_doc = json.loads(ANCHORS_PATH.read_text())
    anchors = anchors_doc["anchors"]

    ext_in_takeoff = {mid for mid in markets if mid.startswith("x")}
    assert set(ext_seeds) == ext_in_takeoff, "seeds_external.json and seeds_takeoff.json external sets differ"

    anchor_ids = set()
    for a in anchors:
        mid = a["marketId"]
        assert mid not in anchor_ids, f"Duplicate anchor for {mid}"
        anchor_ids.add(mid)
        assert mid in markets, f"Dangling anchor {mid} not present in seeds_takeoff.json"
        assert markets[mid]["variableId"] == a["variableId"], f"Anchor variableId mismatch on {mid}"
        assert a["fetchedAt"][:10] >= AS_OF_DATE, f"Stale anchor fetchedAt on {mid}: {a['fetchedAt']}"

    assert anchor_ids == ext_in_takeoff, "anchors.json must cover 100% of external markets in seeds_takeoff.json"
