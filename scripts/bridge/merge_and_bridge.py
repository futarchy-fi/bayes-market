#!/usr/bin/env python3
"""Merge corrected FTM seeds with external seeds; remap stale bridge parents.

Run on farol from ~/bayes-market:
  python3 /tmp/merge_and_bridge.py
Then apply bridges against the merged file (separate step, apply_bridges.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FTM = Path("/tmp/seeds_ftm_corr.json")
EXT = Path("backend/seeds_external.json")
OUT = Path("/tmp/seeds_takeoff_corr.json")
PROPOSALS_IN = Path("/tmp/bridge_proposals.json")
PROPOSALS_OUT = Path("/tmp/bridge_proposals_remapped.json")

ftm = json.loads(FTM.read_text())
ext = json.loads(EXT.read_text())

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
OUT.write_text(json.dumps(merged, indent=1))

# Remap bridge parents that no longer exist to the nearest surviving year
# within the same family prefix (ties break later).
available = {m["variableId"] for m in merged["markets"].values()}
by_prefix = {}
for v in available:
    m = re.match(r"^(.*_(?:by|in)_)(\d{4})$", v)
    if m:
        by_prefix.setdefault(m.group(1), []).append(int(m.group(2)))

def remap(var: str) -> str | None:
    if var in available:
        return var
    m = re.match(r"^(.*_(?:by|in)_)(\d{4})$", var)
    if not m or m.group(1) not in by_prefix:
        return None
    year = int(m.group(2))
    best = min(by_prefix[m.group(1)], key=lambda y: (abs(y - year), -y))
    return f"{m.group(1)}{best}"

doc = json.loads(PROPOSALS_IN.read_text())
remapped, dropped = 0, []
for b in doc["bridges"]:
    mapping = {}
    for p in b["parents"]:
        target = remap(p)
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
            b["rationale"] += f" [parent remapped: {mapping}]"
            remapped += 1
PROPOSALS_OUT.write_text(json.dumps(doc, indent=1))

print(json.dumps({
    "mergedMarkets": len(merged["markets"]),
    "mergedCpts": len(merged["conditionalMarginals"]),
    "bridgesRemapped": remapped,
    "bridgesUnmappable": dropped,
}, indent=1))
