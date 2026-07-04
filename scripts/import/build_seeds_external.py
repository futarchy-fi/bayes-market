#!/usr/bin/env python3
"""Convert harvested Metaculus/Manifold candidates into seeds-v1 markets.

Externals import as independent root markets whose prices ARE the external
forecast at import time; each also gets an `anchor` record so the calibrator
bot keeps trading it toward the live external value. Cross-anchors map a few
external questions onto EXISTING markets instead of creating duplicates.

Run on farol from ~/bayes-market:
  python3 scripts/import/build_seeds_external.py \
      --out backend/seeds_external.json --anchors scripts/import/data/anchors.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# External question -> existing market: anchor only, never a new market.
CROSS_ANCHORS = {
    ("metaculus", "39149"): "m13",   # US-China AGI-limiting treaty ~ m13 treaty market
}

# Off-topic Metaculus harvest noise (qid): not AI-takeoff-relevant.
METACULUS_DROP = {
    "4334",   # chess solved -> forced draw
    "10426",  # Mochizuki abc retraction
    "11319",  # quantum tolerance
    "40972",  # NVDA share price
    "43900",  # metaculus cup bots
    "20110",  # krantz data
    "43525",  # Atlas browser on Windows
    "43314",  # Claude Pro pricing
    "44163",  # SpaceX acquisition
    "1651",   # protein prediction (resolved-ish tech, weak takeoff link)
}

MANIFOLD_MAX_TIER = 2


def slugify(title: str, used: set[str]) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_title.lower()).strip("_")
    slug = ("x_" + slug)[:60].rstrip("_") or "x_question"
    base, k = slug, 2
    while slug in used:
        slug = f"{base[:57]}_{k}"
        k += 1
    used.add(slug)
    return slug


def year_from_title(title: str, default: int = 2031) -> int:
    years = [int(y) for y in re.findall(r"\b(20[2-6]\d)\b", title)]
    return max(years) if years else default


def clamp(p: float) -> float:
    return min(max(p, 0.01), 0.99)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifold", default="scripts/import/data/manifold_candidates.json")
    ap.add_argument("--metaculus", default="scripts/import/data/metaculus_candidates.json")
    ap.add_argument("--out", default="backend/seeds_external.json")
    ap.add_argument("--anchors", default="scripts/import/data/anchors.json")
    ap.add_argument("--max-manifold", type=int, default=250)
    ap.add_argument("--id-prefix", default="x")
    ap.add_argument("--id-start", type=int, default=1)
    args = ap.parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    used_slugs: set[str] = set()
    markets: dict[str, dict] = {}
    anchors: list[dict] = []
    idx = args.id_start
    skipped = {"cross": 0, "dropped": 0, "tier": 0, "cap": 0}

    def add_market(source, ref, url, title, prob, forecasters, close_iso, extra_desc=""):
        nonlocal idx
        mid = f"{args.id_prefix}{idx:04d}"
        idx += 1
        vid = slugify(title, used_slugs)
        p = clamp(prob)
        markets[mid] = {
            "id": mid,
            "title": title[:160],
            "description": (
                f"{title}. Imported from {source} ({url}); resolution follows the "
                f"source question's criteria. {extra_desc}"
                f"External forecast at import ({now}): {prob:.1%} "
                f"({forecasters} forecasters)."
            ),
            "variableId": vid,
            "status": "active",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "marginals": {"yes": round(p, 6), "no": round(1 - p, 6)},
            "liquidity": 10000.0,
            "volume": 0.0,
            "created_at": now,
            "expires_at": close_iso,
            "provenance": {"source": source, "ref": str(ref), "url": url,
                           "method": "external-import-v1", "forecasters": forecasters},
            "anchor": {"source": source, "ref": str(ref), "url": url,
                       "value": round(p, 6), "fetchedAt": now},
        }
        anchors.append({"marketId": mid, "variableId": vid, "source": source,
                        "ref": str(ref), "url": url, "value": round(p, 6),
                        "fetchedAt": now})

    # -- Metaculus ------------------------------------------------------------
    meta = json.loads(Path(args.metaculus).read_text())
    for c in meta["candidates"]:
        key = ("metaculus", c["qid"])
        if key in CROSS_ANCHORS:
            anchors.append({"marketId": CROSS_ANCHORS[key], "variableId": None,
                            "source": "metaculus", "ref": c["qid"], "url": c["url"],
                            "value": round(c["pct"] / 100.0, 6), "fetchedAt": meta["harvestedAt"]})
            skipped["cross"] += 1
            continue
        if c["qid"] in METACULUS_DROP or not c["title"]:
            skipped["dropped"] += 1
            continue
        year = year_from_title(c["title"])
        add_market("metaculus", c["qid"], c["url"], c["title"], c["pct"] / 100.0,
                   c["forecasters"], f"{year}-12-31T23:59:59Z")

    # -- Manifold -------------------------------------------------------------
    mani = json.loads(Path(args.manifold).read_text())
    cands = mani if isinstance(mani, list) else mani.get("candidates", mani.get("markets", []))
    added = 0
    for c in cands:
        if c.get("tier", 9) > MANIFOLD_MAX_TIER:
            skipped["tier"] += 1
            continue
        if added >= args.max_manifold:
            skipped["cap"] += 1
            continue
        close_ms = c.get("closeTime")
        if isinstance(close_ms, (int, float)) and close_ms > 1e12:
            close_iso = datetime.fromtimestamp(close_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(close_ms, str) and close_ms[:2] == "20":
            close_iso = close_ms
        else:
            close_iso = f"{year_from_title(c['question'])}-12-31T23:59:59Z"
        extra = "Flagged conditional-form question. " if c.get("conditional") else ""
        add_market("manifold", c["id"], c.get("url", ""), c["question"],
                   float(c["probability"]), int(c.get("uniqueBettorCount", 0)),
                   close_iso, extra)
        added += 1

    seeds = {"version": "seeds-v1", "markets": markets, "conditionalMarginals": {}}
    Path(args.out).write_text(json.dumps(seeds, indent=1))
    Path(args.anchors).write_text(json.dumps(
        {"builtAt": now, "anchors": anchors}, indent=1))
    print(json.dumps({"markets": len(markets), "anchors": len(anchors),
                      "skipped": skipped}, indent=1))


if __name__ == "__main__":
    main()
