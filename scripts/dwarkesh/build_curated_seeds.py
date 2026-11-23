#!/usr/bin/env python3
"""Compile & merge FTM (2027-2035), Manifold (x*), Dwarkesh (d*), Policy (p*),
and Futurist/Doomer (u*) markets into backend/seeds_takeoff.json with exact
FactoredMarket bisection CPT calibration.

Usage:
  python3 scripts/dwarkesh/build_curated_seeds.py \
      --ftm /home/kelvin/worker-scratch.JgO5IcFb/seeds_ftm_short.json \
      --ext backend/seeds_external.json \
      --ext-proposals scripts/bridge/data/bridge_proposals_remapped.json \
      --episodes scripts/dwarkesh/episodes_curated.json \
      --policy scripts/dwarkesh/policy_curated.json \
      --futurist scripts/dwarkesh/futurist_doomer_curated.json \
      --guest-trades scripts/dwarkesh/guest_trades.json \
      --out backend/seeds_takeoff.json \
      --report scripts/bridge/data/bridge_report_corr.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "bridge"))

from apply_bridges import (  # noqa: E402
    MIN_CALIBRATED_LIFT,
    WIDTH_BUDGET,
    calibrate_leaf,
    row_key,
    extract_child_deadline_year,
    extract_var_year,
    logit,
    parent_context_dist,
    parse_proposal_cpt,
    sigmoid,
)
from backend.inference.factored_market import FactoredMarket  # noqa: E402
from backend.inference.network_model import build_network_nodes  # noqa: E402

AS_OF_DATE = "2026-11-23"
CREATED_AT = f"{AS_OF_DATE}T00:00:00Z"
LIQUIDITY = 10000.0
VAR_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def clean_text(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"\.{2,}", ".", s)
    s = s.replace("?.", "?")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def append_sentence(base: str, addition: str) -> str:
    base = clean_text(base)
    addition = clean_text(addition)
    if not addition or addition in base:
        return base
    if base and base[-1] not in ".?!":
        base += "."
    out = f"{base} {addition}".strip()
    return clean_text(out)


def calibrate_leaf_cpt(
    fm_base: FactoredMarket,
    parents: list[str],
    raw_cpt: dict,
    target_p: float,
    market_id: str,
) -> tuple[dict[str, dict[str, float]], float, float, bool]:
    """Calibrate leaf CPT by exact bisection against fm_base parent distribution.

    If the raw proposal's log-odds spread yields lift < MIN_CALIBRATED_LIFT
    under the updated FTM prior, preserves the exact directional ordering of the
    raw CPT and scales log-odds contrast upward until lift >= 0.14.
    """
    sorted_parents = sorted(parents)
    parsed = parse_proposal_cpt(raw_cpt, sorted_parents)
    if parsed is None:
        raise SystemExit(f"Incomplete CPT on {market_id} for parents {sorted_parents}: {raw_cpt}")
    ctx_dist = parent_context_dist(fm_base, sorted_parents)
    if ctx_dist is None:
        raise SystemExit(f"Cannot compute parent context distribution for {market_id}: {sorted_parents}")

    def _solve(raw_rows: dict[str, float]):
        cal = calibrate_leaf(raw_rows, sorted_parents, ctx_dist, target_p)
        if cal is None:
            return None, None, 0.0
        rows_dict = {
            k: {"yes": round(v, 6), "no": round(1.0 - v, 6)}
            for k, v in cal.items()
        }
        imp = sum(
            prob * rows_dict[row_key(assign, sorted_parents)]["yes"]
            for assign, prob in ctx_dist
        )
        ys = [r["yes"] for r in rows_dict.values()]
        return rows_dict, imp, max(ys) - min(ys)

    cpt_rows, implied, lift = _solve(parsed)
    if cpt_rows is None:
        raise SystemExit(f"Calibration infeasible on {market_id} ({sorted_parents})")
    widened = False

    if lift < MIN_CALIBRATED_LIFT:
        # Preserve exact sign / relative ordering while amplifying log-odds contrast
        mean_logit = sum(logit(v) for v in parsed.values()) / len(parsed)
        for mult in (1.4, 1.8, 2.3, 3.0, 4.0, 5.5, 7.5):
            scaled = {}
            for k, v in parsed.items():
                val = sigmoid(mean_logit + mult * (logit(v) - mean_logit))
                scaled[k] = min(max(val, 0.02), 0.98)
            cand_rows, cand_imp, cand_lift = _solve(scaled)
            if cand_rows is not None and cand_lift > lift:
                cpt_rows, implied, lift = cand_rows, cand_imp, cand_lift
                widened = True
            if lift >= 0.14:
                break

    if lift < MIN_CALIBRATED_LIFT:
        raise SystemExit(
            f"Bridge lift too weak on {market_id} ({sorted_parents}): "
            f"lift={lift:.4f} < {MIN_CALIBRATED_LIFT}"
        )
    if abs(implied - target_p) > 1e-5:
        raise SystemExit(
            f"Calibration residual too large on {market_id}: "
            f"implied={implied:.6f} vs target={target_p:.6f}"
        )
    return cpt_rows, implied, lift, widened


def build_curated_market_record(
    *,
    mid: str,
    slug: str,
    title: str,
    description: str,
    expires_at: str,
    prior: float,
    provenance: dict,
    parents: list[str],
) -> dict:
    if not VAR_ID_RE.fullmatch(slug):
        raise SystemExit(f"Invalid variableId {slug!r} on {mid}")
    if expires_at[:10] <= AS_OF_DATE:
        raise SystemExit(f"Expired curated market {mid} ({slug}): {expires_at}")
    p = round(float(prior), 6)
    if not (0.02 <= p <= 0.98):
        raise SystemExit(f"Prior out of bounds on {mid} ({slug}): {p}")

    bridge_note = f"Bridged into the FTM net: conditional on {', '.join(sorted(parents))}."
    desc = append_sentence(description, bridge_note)
    assert ".." not in desc and "?." not in desc, f"Punctuation artifact in {mid}: {desc}"

    return {
        "id": mid,
        "title": clean_text(title),
        "description": desc,
        "variableId": slug,
        "status": "active",
        "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
        "marginals": {"yes": p, "no": round(1.0 - p, 6)},
        "liquidity": LIQUIDITY,
        "volume": 0.0,
        "created_at": CREATED_AT,
        "expires_at": expires_at,
        "provenance": provenance,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ftm", default="/home/kelvin/worker-scratch.JgO5IcFb/seeds_ftm_short.json")
    ap.add_argument("--ext", default="backend/seeds_external.json")
    ap.add_argument("--ext-proposals", default="scripts/bridge/data/bridge_proposals_remapped.json")
    ap.add_argument("--episodes", default="scripts/dwarkesh/episodes_curated.json")
    ap.add_argument("--policy", default="scripts/dwarkesh/policy_curated.json")
    ap.add_argument("--futurist", default="scripts/dwarkesh/futurist_doomer_curated.json")
    ap.add_argument("--guest-trades", default="scripts/dwarkesh/guest_trades.json")
    ap.add_argument("--out", default="backend/seeds_takeoff.json")
    ap.add_argument("--report", default="scripts/bridge/data/bridge_report_corr.json")
    args = ap.parse_args()

    ftm = json.loads(Path(args.ftm).read_text())
    ext = json.loads(Path(args.ext).read_text())
    ext_props = json.loads(Path(args.ext_proposals).read_text())
    ep_doc = json.loads(Path(args.episodes).read_text())
    pol_doc = json.loads(Path(args.policy).read_text())
    fut_doc = json.loads(Path(args.futurist).read_text())

    # 1. Start with FTM backbone and build baseline FactoredMarket for exact leaf calibration
    markets: dict[str, dict] = {}
    conds: dict[str, dict] = {}
    seen_vars: set[str] = set()

    for mid, m in ftm["markets"].items():
        vid = m["variableId"]
        assert VAR_ID_RE.fullmatch(vid), f"Bad FTM variableId {vid}"
        assert mid not in markets and vid not in seen_vars
        markets[mid] = m
        seen_vars.add(vid)
    for mid, rows in ftm.get("conditionalMarginals", {}).items():
        conds[mid] = rows

    ftm_vars = set(seen_vars)
    ftm_nodes = build_network_nodes(markets, conds)
    fm_base = FactoredMarket.from_nodes(ftm_nodes, LIQUIDITY, WIDTH_BUDGET)
    base_stats = fm_base.stats()
    print(f"FTM backbone loaded: {len(markets)} markets, treewidth={base_stats['treewidth']}")

    leaf_proposals: list[tuple[str, dict, list[str], dict, str]] = []

    # 2. External Manifold markets (x*)
    prop_by_ext = {b["externalId"]: b for b in ext_props["bridges"]}
    for mid, m in ext["markets"].items():
        vid = m["variableId"]
        assert VAR_ID_RE.fullmatch(vid), f"Bad external variableId {vid}"
        assert mid not in markets and vid not in seen_vars
        b = prop_by_ext.get(mid)
        if b is None:
            raise SystemExit(f"Missing bridge proposal for external market {mid}")
        m_copy = json.loads(json.dumps(m))
        parents = sorted(b["parents"])
        bridge_note = f"Bridged into the FTM net: conditional on {', '.join(parents)}."
        m_copy["description"] = append_sentence(m_copy.get("description", ""), bridge_note)
        markets[mid] = m_copy
        seen_vars.add(vid)
        leaf_proposals.append((mid, m_copy, parents, b["cpt"], "manifold"))

    # 3. Dwarkesh Podcast markets (d0001.., dw_*)
    d_idx = 0
    for ep in ep_doc["episodes"]:
        ep_url = ep["url"]
        for raw_m in ep["markets"]:
            d_idx += 1
            mid = f"d{d_idx:04d}"
            slug = raw_m["slug"]
            parents = sorted(raw_m["parents"])
            desc = raw_m["description"]
            if ep_url not in desc:
                desc = append_sentence(desc, f"Source episode: {ep['title']} ({ep_url}).")
            prov = {
                "source": "dwarkesh",
                "method": "dwarkesh-curated-v1",
                "episodeSlug": ep["slug"],
                "episodeTitle": ep["title"],
                "episodeDate": ep["date"],
                "url": ep_url,
                "guests": ep["guests"],
                "quote": raw_m.get("quote", ""),
                "asOfDate": AS_OF_DATE,
            }
            rec = build_curated_market_record(
                mid=mid,
                slug=slug,
                title=raw_m["title"],
                description=desc,
                expires_at=raw_m["expires_at"],
                prior=raw_m["consensus_prior"],
                provenance=prov,
                parents=parents,
            )
            assert mid not in markets and slug not in seen_vars, f"Collision {mid}/{slug}"
            markets[mid] = rec
            seen_vars.add(slug)
            leaf_proposals.append((mid, rec, parents, raw_m["cpt"], "dwarkesh"))

    # 4. AI Policy & Regulation markets (p0001.., pol_*)
    for p_idx, raw_m in enumerate(pol_doc["markets"], start=1):
        mid = f"p{p_idx:04d}"
        slug = raw_m["slug"]
        parents = sorted(raw_m["parents"])
        prov = {
            "source": "policy",
            "method": "policy-curated-v1",
            "category": raw_m.get("category", "ai_policy"),
            "asOfDate": AS_OF_DATE,
        }
        rec = build_curated_market_record(
            mid=mid,
            slug=slug,
            title=raw_m["title"],
            description=raw_m["description"],
            expires_at=raw_m["expires_at"],
            prior=raw_m["consensus_prior"],
            provenance=prov,
            parents=parents,
        )
        assert mid not in markets and slug not in seen_vars, f"Collision {mid}/{slug}"
        markets[mid] = rec
        seen_vars.add(slug)
        leaf_proposals.append((mid, rec, parents, raw_m["cpt"], "policy"))

    # 5. Futurist & Doomer markets (u0001.., fut_*)
    for u_idx, raw_m in enumerate(fut_doc["markets"], start=1):
        mid = f"u{u_idx:04d}"
        slug = raw_m["slug"]
        parents = sorted(raw_m["parents"])
        prov = {
            "source": "futurist",
            "method": "futurist-doomer-curated-v1",
            "school": raw_m.get("source_school", "Futurist"),
            "citation": raw_m.get("citation", ""),
            "asOfDate": AS_OF_DATE,
        }
        rec = build_curated_market_record(
            mid=mid,
            slug=slug,
            title=raw_m["title"],
            description=raw_m["description"],
            expires_at=raw_m["expires_at"],
            prior=raw_m["consensus_prior"],
            provenance=prov,
            parents=parents,
        )
        assert mid not in markets and slug not in seen_vars, f"Collision {mid}/{slug}"
        markets[mid] = rec
        seen_vars.add(slug)
        leaf_proposals.append((mid, rec, parents, raw_m["cpt"], "futurist"))

    # 6. Validate & calibrate EVERY leaf bridge against fm_base
    bridge_details = []
    worst_delta = 0.0
    min_lift = 1.0
    widened_count = 0

    for mid, mrec, parents, raw_cpt, family in leaf_proposals:
        for p in parents:
            if p not in ftm_vars:
                raise SystemExit(f"Leaf {mid} ({mrec['variableId']}) references non-FTM parent {p}")
        child_year = extract_child_deadline_year(mrec)
        for p in parents:
            py = extract_var_year(p)
            if py is not None and child_year is not None and py > child_year:
                raise SystemExit(
                    f"Backwards-in-time bridge on {mid} ({mrec['variableId']}): "
                    f"{p} ({py}) > child ({child_year})"
                )

        target_p = mrec["marginals"]["yes"]
        cpt_rows, implied, lift, widened = calibrate_leaf_cpt(
            fm_base, parents, raw_cpt, target_p, mid
        )
        conds[mid] = cpt_rows
        delta = abs(implied - target_p)
        worst_delta = max(worst_delta, delta)
        min_lift = min(min_lift, lift)
        if widened:
            widened_count += 1
        bridge_details.append({
            "marketId": mid,
            "variableId": mrec["variableId"],
            "family": family,
            "parents": parents,
            "seedMarginal": round(target_p, 6),
            "impliedMarginal": round(implied, 6),
            "delta": round(delta, 8),
            "lift": round(lift, 4),
            "widenedSpread": widened,
        })

    # 7. Full-network verification on merged seeds
    all_nodes = build_network_nodes(markets, conds)
    fm_full = FactoredMarket.from_nodes(all_nodes, 50.0, WIDTH_BUDGET)
    full_stats = fm_full.stats()
    assert full_stats["treewidth"] <= WIDTH_BUDGET, f"Treewidth exceeded: {full_stats}"

    full_worst_delta = 0.0
    for mid, mrec, _, _, _ in leaf_proposals:
        imp = fm_full.marginal(mrec["variableId"])["yes"]
        d = abs(imp - mrec["marginals"]["yes"])
        full_worst_delta = max(full_worst_delta, d)
    assert full_worst_delta < 1e-5, f"Full-net marginal delta too high: {full_worst_delta}"

    # Verify guest_trades.json against compiled seeds
    gt_path = Path(args.guest_trades)
    if gt_path.exists():
        gt = json.loads(gt_path.read_text())
        for tr in gt["traders"]:
            for td in tr["trades"]:
                tv = td["target_var"]
                assert tv in seen_vars, f"Guest trade {tr['username']} targets missing var {tv}"
                assert 0.04 <= float(td["target_prob"]) <= 0.96
                assert td.get("rationale", "").strip() and td.get("quote", "").strip()

    # 8. Write seeds_takeoff.json and bridge_report_corr.json
    seeds_out = {
        "version": "seeds-v1",
        "markets": markets,
        "conditionalMarginals": conds,
    }
    Path(args.out).write_text(json.dumps(seeds_out, indent=1) + "\n")

    counts = {
        "ftm": sum(1 for k in markets if k.startswith("f")),
        "manifold": sum(1 for k in markets if k.startswith("x")),
        "dwarkesh": sum(1 for k in markets if k.startswith("d")),
        "policy": sum(1 for k in markets if k.startswith("p")),
        "futurist": sum(1 for k in markets if k.startswith("u")),
    }
    total_edges = sum(len(n["parents"]) for n in all_nodes)

    report = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asOfDate": AS_OF_DATE,
        "totalMarkets": len(markets),
        "countsByFamily": counts,
        "totalEdges": total_edges,
        "bridgedLeaves": len(leaf_proposals),
        "widenedSpreadCount": widened_count,
        "treewidth": full_stats["treewidth"],
        "cliqueCount": full_stats["cliqueCount"],
        "worstMarginalDelta": round(full_worst_delta, 8),
        "minCalibratedLift": round(min_lift, 4),
        "bridges": bridge_details,
    }
    Path(args.report).write_text(json.dumps(report, indent=1) + "\n")

    print(json.dumps({
        "totalMarkets": len(markets),
        "countsByFamily": counts,
        "totalEdges": total_edges,
        "bridgedLeaves": len(leaf_proposals),
        "widenedSpreadCount": widened_count,
        "treewidth": full_stats["treewidth"],
        "worstMarginalDelta": round(full_worst_delta, 8),
        "minCalibratedLift": round(min_lift, 4),
    }, indent=1))


if __name__ == "__main__":
    main()
