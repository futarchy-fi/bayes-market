#!/usr/bin/env python3
"""Merge compiled FTM seeds with curated external seeds; optionally remap parents.

Run from repo root:
  python3 scripts/bridge/merge_and_bridge.py \
      --ftm /tmp/seeds_ftm_v2.json \
      --ext backend/seeds_external.json \
      --out backend/seeds_takeoff.json \
      --proposals-in scripts/bridge/data/bridge_proposals_remapped.json \
      --proposals-out scripts/bridge/data/bridge_proposals_remapped.json
Then run apply_bridges.py against the merged file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_bridges import extract_child_deadline_year  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ftm", default="/tmp/seeds_ftm_v2.json")
    ap.add_argument("--ext", default="backend/seeds_external.json")
    ap.add_argument("--out", default="backend/seeds_takeoff.json")
    ap.add_argument("--proposals-in", default="scripts/bridge/data/bridge_proposals_remapped.json")
    ap.add_argument("--proposals-out", default="scripts/bridge/data/bridge_proposals_remapped.json")
    args = ap.parse_args()

    ftm = json.loads(Path(args.ftm).read_text())
    ext = json.loads(Path(args.ext).read_text())

    id_overlap = set(ftm["markets"]) & set(ext["markets"])
    var_overlap = (
        {m["variableId"] for m in ftm["markets"].values()}
        & {m["variableId"] for m in ext["markets"].values()}
    )
    assert not id_overlap and not var_overlap, (id_overlap, var_overlap)

    merged = {
        "version": "seeds-v1",
        "markets": {**ftm["markets"], **ext["markets"]},
        "conditionalMarginals": {
            **ftm.get("conditionalMarginals", {}),
            **ext.get("conditionalMarginals", {}),
        },
    }
    Path(args.out).write_text(json.dumps(merged, indent=1) + "\n")

    available = {m["variableId"] for m in merged["markets"].values()}
    by_prefix: dict[str, list[int]] = {}
    for v in available:
        m = re.match(r"^(.*_(?:by|in)_)(\d{4})$", v)
        if m:
            by_prefix.setdefault(m.group(1), []).append(int(m.group(2)))

    def remap(var: str, max_year: int | None) -> str | None:
        if var in available:
            return var
        m = re.match(r"^(.*_(?:by|in)_)(\d{4})$", var)
        if not m or m.group(1) not in by_prefix:
            return None
        year = int(m.group(2))
        cands = by_prefix[m.group(1)]
        if max_year is not None:
            cands = [y for y in cands if y <= max_year]
        if not cands:
            return None
        best = min(cands, key=lambda y: (abs(y - year), -y))
        return f"{m.group(1)}{best}"

    doc = json.loads(Path(args.proposals_in).read_text())
    remapped, dropped = 0, []
    for b in doc["bridges"]:
        ext_m = merged["markets"].get(b["externalId"])
        max_year = extract_child_deadline_year(ext_m) if ext_m else None
        mapping = {}
        for p in b["parents"]:
            target = remap(p, max_year)
            if target is None:
                dropped.append((b["externalId"], p))
                break
            if target != p:
                mapping[p] = target
        else:
            if mapping:
                b["parents"] = [mapping.get(p, p) for p in b["parents"]]
                b["cpt"] = {
                    "|".join(
                        f"{mapping.get(a.split('=')[0], a.split('=')[0])}={a.split('=', 1)[1]}"
                        for a in key.split("|")
                    ): val
                    for key, val in b["cpt"].items()
                }
                b["rationale"] = b.get("rationale", "") + f" [parent remapped: {mapping}]"
                remapped += 1
    Path(args.proposals_out).write_text(json.dumps(doc, indent=1) + "\n")

    print(json.dumps({
        "mergedMarkets": len(merged["markets"]),
        "mergedCpts": len(merged["conditionalMarginals"]),
        "bridgesRemapped": remapped,
        "bridgesUnmappable": dropped,
    }, indent=1))


if __name__ == "__main__":
    main()
