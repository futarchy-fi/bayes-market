"""Automated world-model invariants for the Short-Timelines (2027-2035) +
Future-of-Humanity + Dwarkesh Podcast + AI Policy + Futurist/Doomer Bayesian Network.

Guards backend/seeds_takeoff.json, backend/seeds_external.json,
scripts/import/data/anchors.json, and scripts/dwarkesh/guest_trades.json
against structural, logical, temporal, calibration, provenance, and trade regressions.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from backend import server
from backend.inference.factored_market import FactoredMarket
from backend.inference.network_model import build_network_nodes

REPO_ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = REPO_ROOT / "backend" / "seeds_takeoff.json"
EXT_SEEDS_PATH = REPO_ROOT / "backend" / "seeds_external.json"
ANCHORS_PATH = REPO_ROOT / "scripts" / "import" / "data" / "anchors.json"
GUEST_TRADES_PATH = REPO_ROOT / "scripts" / "dwarkesh" / "guest_trades.json"

AS_OF_DATE = "2026-11-23"
MAX_TREEWIDTH = 8
FTM_MAX_YEAR = 2035
VAR_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
USERNAME_RE = re.compile(r"^[a-z0-9-]{1,40}$")


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
    """Return conservative causal year for any FTM, external, or curated market."""
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

    # Unique valid variableIds and server-level schema validation across all markets
    assert len(by_var) == len(markets), "Duplicate variableId detected across markets"
    for mid, m in markets.items():
        assert VAR_ID_RE.fullmatch(m["variableId"]), f"Invalid variableId on {mid}: {m['variableId']}"
        server._validate_seed_market_record(mid, m)

    parents_of: dict[str, tuple[str, ...]] = {}
    for node in nodes:
        vid = node["variable_id"]
        ps = tuple(node["parents"])
        assert vid not in ps, f"Self-loop on {vid}"
        for p in ps:
            assert p in by_var, f"Dangling parent reference {p} on {vid}"
        parents_of[vid] = ps

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

    max_delta = 0.0
    max_leaf_delta = 0.0
    worst_vid = None
    for mid, m in markets.items():
        vid = m["variableId"]
        implied = fm.marginal(vid)["yes"]
        delta = abs(implied - m["marginals"]["yes"])
        if delta > max_delta:
            max_delta = delta
            worst_vid = vid
        if not mid.startswith("f"):
            max_leaf_delta = max(max_leaf_delta, delta)
    assert max_delta < 1e-4, f"Marginal drift {max_delta:.6f} on {worst_vid}"
    assert max_leaf_delta < 1e-5, f"Leaf bridge marginal drift {max_leaf_delta:.6f}"


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

        if mode == "by":
            nxt = ftm_grid.get((slug, thr, mode, year + 1))
            if nxt is not None:
                leak = fm.marginal(nxt, {vid: "yes"})["no"]
                if leak > 1e-9:
                    temporal_leaks.append((vid, nxt, leak))
                p_nxt = fm.marginal(nxt)["yes"]
                if p_cur > p_nxt + 1e-6:
                    marginal_inversions.append((vid, p_cur, nxt, p_nxt))

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
        for year in range(2027, FTM_MAX_YEAR + 1):
            sub_v = f"{sub_pref}{year}"
            sup_v = f"{sup_pref}{year}"
            if sub_v in by_var and sup_v in by_var:
                checked += 1
                leak = fm.marginal(sup_v, {sub_v: "yes"})["no"]
                if leak > 1e-9:
                    leaks.append((sub_v, sup_v, leak))

    assert checked >= 50, f"Expected >=50 cross-metric implication pairs in 2027-2035, checked {checked}"
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


def test_no_expired_markets_no_post_2035_ftm_and_clean_formatting(world_model):
    markets = world_model["markets"]
    expired = []
    formatting = []
    post_2035_ftm = []

    for mid, m in markets.items():
        assert m.get("status") == "active", f"Non-active market {mid}: {m.get('status')}"
        exp = str(m.get("expires_at", ""))
        if exp[:10] <= AS_OF_DATE:
            expired.append((mid, exp, m.get("title")))
        title = str(m.get("title", ""))
        desc = str(m.get("description", ""))
        if ".." in desc or "?." in desc or "\u0391I" in title or "\u0391I" in desc:
            formatting.append((mid, title))

        vid = str(m.get("variableId", ""))
        if vid.startswith("ftm_"):
            parsed = _parse_ftm_var(vid)
            assert parsed is not None, f"Unparseable FTM variableId {vid}"
            if parsed[3] > FTM_MAX_YEAR:
                post_2035_ftm.append((mid, vid, parsed[3]))

    assert not expired, f"Expired markets still active ({len(expired)}): {expired[:5]}"
    assert not formatting, f"Formatting defects ({len(formatting)}): {formatting[:5]}"
    assert not post_2035_ftm, f"Post-2035 FTM markets still present ({len(post_2035_ftm)}): {post_2035_ftm[:5]}"


def test_strong_conditional_propagation_and_bridge_lifts(world_model):
    fm: FactoredMarket = world_model["fm"]
    markets = world_model["markets"]
    by_var = world_model["by_var"]
    nodes_by_var = world_model["nodes_by_var"]

    # 1. Strong FTM cross-family propagation from BOTH ftm_agi_by_2035 and ftm_agi_by_2032
    goods35 = (
        fm.marginal("ftm_auto_goods_t3_by_2035", {"ftm_agi_by_2035": "yes"})["yes"]
        - fm.marginal("ftm_auto_goods_t3_by_2035", {"ftm_agi_by_2035": "no"})["yes"]
    )
    rnd35 = (
        fm.marginal("ftm_auto_rnd_t3_by_2035", {"ftm_agi_by_2035": "yes"})["yes"]
        - fm.marginal("ftm_auto_rnd_t3_by_2035", {"ftm_agi_by_2035": "no"})["yes"]
    )
    gwp35 = (
        fm.marginal("ftm_gwp_growth_max_t1_by_2035", {"ftm_agi_by_2035": "yes"})["yes"]
        - fm.marginal("ftm_gwp_growth_max_t1_by_2035", {"ftm_agi_by_2035": "no"})["yes"]
    )
    assert goods35 >= 0.45, f"Weak goods-90% lift given AGI-2035: {goods35:.4f}"
    assert rnd35 >= 0.45, f"Weak R&D-90% lift given AGI-2035: {rnd35:.4f}"
    assert gwp35 >= 0.20, f"Weak GWP-10% lift given AGI-2035: {gwp35:.4f}"

    goods32 = (
        fm.marginal("ftm_auto_goods_t3_by_2032", {"ftm_agi_by_2032": "yes"})["yes"]
        - fm.marginal("ftm_auto_goods_t3_by_2032", {"ftm_agi_by_2032": "no"})["yes"]
    )
    rnd32 = (
        fm.marginal("ftm_auto_rnd_t3_by_2032", {"ftm_agi_by_2032": "yes"})["yes"]
        - fm.marginal("ftm_auto_rnd_t3_by_2032", {"ftm_agi_by_2032": "no"})["yes"]
    )
    gwp32 = (
        fm.marginal("ftm_gwp_growth_max_t1_by_2032", {"ftm_agi_by_2032": "yes"})["yes"]
        - fm.marginal("ftm_gwp_growth_max_t1_by_2032", {"ftm_agi_by_2032": "no"})["yes"]
    )
    assert goods32 >= 0.30, f"Weak goods-90% lift given AGI-2032: {goods32:.4f}"
    assert rnd32 >= 0.40, f"Weak R&D-90% lift given AGI-2032: {rnd32:.4f}"
    assert gwp32 >= 0.25, f"Weak GWP-10% lift given AGI-2032: {gwp32:.4f}"

    # 2. Strong propagation from ftm_agi_by_2035 and ftm_agi_by_2032 into dw_*, pol_*, fut_*
    for anchor in ("ftm_agi_by_2035", "ftm_agi_by_2032"):
        for prefix, min_max_lift in (("dw_", 0.20), ("pol_", 0.20), ("fut_", 0.20)):
            family_vars = [v for v in by_var if v.startswith(prefix)]
            assert family_vars, f"No markets found with prefix {prefix}"
            max_lift = max(
                abs(fm.marginal(v, {anchor: "yes"})["yes"] - fm.marginal(v, {anchor: "no"})["yes"])
                for v in family_vars
            )
            assert max_lift >= min_max_lift, (
                f"Weak propagation from {anchor} into {prefix}* markets: max|lift|={max_lift:.4f}"
            )

    # 3. Every bridged leaf market (x*, d*, p*, u*) must have >=1 parent and lift >= 0.10
    ext_markets = {mid: m for mid, m in markets.items() if mid.startswith("x")}
    dw_markets = {mid: m for mid, m in markets.items() if mid.startswith("d")}
    pol_markets = {mid: m for mid, m in markets.items() if mid.startswith("p")}
    fut_markets = {mid: m for mid, m in markets.items() if mid.startswith("u")}

    assert 60 <= len(ext_markets) <= 95, f"Unexpected Manifold external count: {len(ext_markets)}"
    assert len(dw_markets) >= 45, f"Unexpected Dwarkesh market count: {len(dw_markets)}"
    assert len(pol_markets) >= 12, f"Unexpected Policy market count: {len(pol_markets)}"
    assert len(fut_markets) >= 20, f"Unexpected Futurist market count: {len(fut_markets)}"

    weak_bridges = []
    for mid, m in markets.items():
        if mid.startswith("f"):
            continue
        node = nodes_by_var[m["variableId"]]
        assert len(node["parents"]) >= 1, f"Leaf market {mid} is unbridged"
        row_probs = [r["yes"] for r in node["rows"].values()]
        lift = max(row_probs) - min(row_probs)
        if lift < 0.10:
            weak_bridges.append((mid, lift))
    assert not weak_bridges, f"Weak leaf bridge CPTs (<0.10 lift): {weak_bridges[:10]}"

    # 4. Semantic direction sanity checks (negative and positive bridges)
    if "x0072" in markets:  # AI winter before AGI (negative vs AGI by 2035)
        v_winter = markets["x0072"]["variableId"]
        assert fm.marginal(v_winter, {"ftm_agi_by_2035": "yes"})["yes"] < fm.marginal(
            v_winter, {"ftm_agi_by_2035": "no"}
        )["yes"]
    if "x0216" in markets:  # Global AI pause before 2035 (negative vs AGI by 2035)
        v_pause = markets["x0216"]["variableId"]
        assert fm.marginal(v_pause, {"ftm_agi_by_2035": "yes"})["yes"] < fm.marginal(
            v_pause, {"ftm_agi_by_2035": "no"}
        )["yes"]
    if "x0070" in markets:  # Superintelligence by 2040 (positive vs ftm_agi_by_2035)
        v_asi40 = markets["x0070"]["variableId"]
        assert fm.marginal(v_asi40, {"ftm_agi_by_2035": "yes"})["yes"] > fm.marginal(
            v_asi40, {"ftm_agi_by_2035": "no"}
        )["yes"] + 0.25


def test_short_timelines_calibration_family_completeness_and_provenance(world_model):
    fm: FactoredMarket = world_model["fm"]
    markets = world_model["markets"]
    by_var = world_model["by_var"]

    # Required 2027-2035 short-timelines FTM families present; no rampup; no post-2035 FTM
    for y in range(2029, 2036):
        assert f"ftm_agi_by_{y}" in by_var, f"Missing ftm_agi_by_{y}"
    for y in range(2027, 2036):
        assert f"ftm_sub_agi_by_{y}" in by_var, f"Missing ftm_sub_agi_by_{y}"
        assert f"ftm_auto_rnd_t1_by_{y}" in by_var, f"Missing ftm_auto_rnd_t1_by_{y}"
    assert not any(v.startswith("ftm_rampup_") for v in by_var), "Redundant rampup family still present"

    # Short-timelines calibrated prior bands
    checks = [
        ("ftm_sub_agi_by_2027", 0.02, 0.07),
        ("ftm_sub_agi_by_2028", 0.06, 0.14),
        ("ftm_sub_agi_by_2030", 0.24, 0.38),
        ("ftm_sub_agi_by_2032", 0.45, 0.62),
        ("ftm_sub_agi_by_2035", 0.68, 0.84),
        ("ftm_agi_by_2029", 0.02, 0.06),
        ("ftm_agi_by_2030", 0.03, 0.10),
        ("ftm_agi_by_2032", 0.20, 0.35),
        ("ftm_agi_by_2035", 0.54, 0.70),
        ("ftm_auto_rnd_t1_by_2027", 0.02, 0.08),
        ("ftm_auto_rnd_t1_by_2028", 0.12, 0.24),
        ("ftm_auto_rnd_t1_by_2030", 0.36, 0.52),
        ("ftm_auto_rnd_t1_by_2032", 0.56, 0.74),
        ("ftm_auto_rnd_t1_by_2035", 0.76, 0.90),
    ]
    for vid, lo, hi in checks:
        p = fm.marginal(vid)["yes"]
        assert lo <= p <= hi, f"{vid} marginal {p:.4f} outside short-timelines band [{lo}, {hi}]"

    # FTM provenance records late-2026 weighting metadata with ESS >= 240
    agi_prov = by_var["ftm_agi_by_2035"]["provenance"]
    assert agi_prov["method"] == "mc-threshold-grid-v2-weighted"
    assert agi_prov["calibrationDate"] == AS_OF_DATE
    assert agi_prov["ess"] >= 240.0

    # Curated families carry proper source provenance
    for mid, m in markets.items():
        prov = m.get("provenance") or {}
        if mid.startswith("d"):
            assert prov.get("source") == "dwarkesh", f"Bad provenance on {mid}"
            assert str(prov.get("url", "")).startswith("https://www.dwarkesh.com/"), f"Missing URL on {mid}"
        elif mid.startswith("p"):
            assert prov.get("source") == "policy", f"Bad provenance on {mid}"
        elif mid.startswith("u"):
            assert prov.get("source") == "futurist", f"Bad provenance on {mid}"
            assert prov.get("school"), f"Missing school on {mid}"


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
        assert mid.startswith("x"), f"anchors.json must only cover x* Manifold markets, found {mid}"
        assert mid not in anchor_ids, f"Duplicate anchor for {mid}"
        anchor_ids.add(mid)
        assert mid in markets, f"Dangling anchor {mid} not present in seeds_takeoff.json"
        assert markets[mid]["variableId"] == a["variableId"], f"Anchor variableId mismatch on {mid}"
        assert a["fetchedAt"][:10] >= AS_OF_DATE, f"Stale anchor fetchedAt on {mid}: {a['fetchedAt']}"

    assert anchor_ids == ext_in_takeoff, "anchors.json must cover 100% of x* markets in seeds_takeoff.json"


def test_dwarkesh_guest_trades_integrity(world_model):
    by_var = world_model["by_var"]
    doc = json.loads(GUEST_TRADES_PATH.read_text())
    traders = doc.get("traders", [])
    assert len(traders) >= 15, f"Expected >=15 guest traders, found {len(traders)}"

    seen_users = set()
    total_trades = 0
    for tr in traders:
        u = tr.get("username", "")
        assert USERNAME_RE.fullmatch(u), f"Invalid guest username: {u!r}"
        assert u not in seen_users, f"Duplicate guest trader username: {u}"
        seen_users.add(u)
        assert tr.get("display_name", "").strip(), f"Missing display_name on {u}"
        assert str(tr.get("initial_credits", "")).strip() == "1000", f"Unexpected initial_credits on {u}"
        assert str(tr.get("episode_url", "")).startswith("https://www.dwarkesh.com/"), f"Bad episode_url on {u}"

        trades = tr.get("trades", [])
        assert len(trades) >= 1, f"Trader {u} has no trades"
        seen_vars = set()
        for td in trades:
            tv = td.get("target_var", "")
            assert tv in by_var, f"Guest trade {u} targets missing variableId {tv!r}"
            assert tv not in seen_vars, f"Duplicate trade on {tv} for trader {u}"
            seen_vars.add(tv)
            prob = float(td["target_prob"])
            assert 0.04 <= prob <= 0.96, f"Trade prob out of [0.04, 0.96] on {u}/{tv}: {prob}"
            assert str(td.get("rationale", "")).strip(), f"Empty rationale on {u}/{tv}"
            assert str(td.get("quote", "")).strip(), f"Empty quote on {u}/{tv}"
            total_trades += 1

    assert total_trades >= 150, f"Expected >=150 total guest trades, got {total_trades}"
