#!/usr/bin/env python3
"""Coherence scanner: bayes-market joint prices vs live external forecasts.

Stage 1 (read-only) of the arbitrage pipeline: for every live bayes-market
with an anchor, fetch the CURRENT external forecast (Manifold / Metaculus)
and report
  - divergence between the coherent joint's price and the external price
    ("money on the table" for anyone who trusts the joint),
  - anchor staleness (how far the world moved since the seed import),
  - externals that already RESOLVED or CLOSED while the bayes market
    still prices them as open (resolution-feed gap).

Stdlib only, like the rest of the repo. No key needed for either API.

Usage:
    python3 scripts/arb/scan_manifold.py --out /tmp/scan.json
    python3 scripts/arb/scan_manifold.py --limit 20          # smoke test
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # optional; fixes macOS pythons that lack a CA bundle

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()

BAYES_BASE = "https://bayes.futarchy.ai"
MANIFOLD_BASE = "https://api.manifold.markets/v0"
METACULUS_BASE = "https://www.metaculus.com/api2"
USER_AGENT = (
    "bayes-market-coherence-scanner/0.1 "
    "(research script for futarchy.ai bayes-market)"
)
MAX_RETRIES = 4
BACKOFF_BASE_SEC = 1.5


def fetch_json(url: str, timeout: float = 20.0) -> dict | list | None:
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("METACULUS_TOKEN")
    if token and url.startswith(METACULUS_BASE):
        headers["Authorization"] = f"Token {token}"
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=SSL_CTX) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                return None
            if error.code == 429 or error.code >= 500:
                time.sleep(BACKOFF_BASE_SEC * (2**attempt))
                continue
            return None
        except Exception:
            time.sleep(BACKOFF_BASE_SEC * (2**attempt))
    return None


def bayes_anchor_markets(base: str) -> list[dict]:
    payload = fetch_json(f"{base}/v1/markets")
    markets = payload["markets"] if isinstance(payload, dict) else payload
    return [m for m in markets if m.get("anchor")]


def manifold_now(ref: str) -> dict:
    data = fetch_json(f"{MANIFOLD_BASE}/market/{ref}")
    if not isinstance(data, dict):
        return {"ok": False}
    return {
        "ok": True,
        "probability": data.get("probability"),
        "is_resolved": bool(data.get("isResolved")),
        "resolution": data.get("resolution"),
        "closed": (data.get("closeTime") or 0) / 1000.0 < time.time(),
        "volume": data.get("volume"),
        "bettors": data.get("uniqueBettorCount"),
        "url": data.get("url"),
        "outcome_type": data.get("outcomeType"),
    }


def _metaculus_community(question: dict) -> float | None:
    # API shape has changed across versions; try known paths defensively.
    try:
        centers = question["aggregations"]["recency_weighted"]["latest"]["centers"]
        if centers:
            return float(centers[0])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        return float(question["community_prediction"]["full"]["q2"])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def metaculus_now(ref: str) -> dict:
    data = fetch_json(f"{METACULUS_BASE}/questions/{ref}/")
    if not isinstance(data, dict):
        return {"ok": False}
    question = data.get("question") if isinstance(data.get("question"), dict) else data
    status = data.get("status") or question.get("status")
    resolution = question.get("resolution")
    return {
        "ok": True,
        "probability": _metaculus_community(question),
        "is_resolved": status == "resolved" or resolution not in (None, ""),
        "resolution": resolution,
        "closed": status in ("closed", "resolved"),
        "volume": None,
        "bettors": data.get("nr_forecasters") or question.get("nr_forecasters"),
        "url": f"https://www.metaculus.com/questions/{ref}/",
        "outcome_type": question.get("type"),
    }


def edge_metrics(p_bayes: float, p_ext: float) -> dict:
    """EV per $1 staked on the external market, assuming the joint is right."""
    side = "YES" if p_bayes > p_ext else "NO"
    if side == "YES":
        price, p_win = p_ext, p_bayes
    else:
        price, p_win = 1.0 - p_ext, 1.0 - p_bayes
    if price <= 0.0 or price >= 1.0:
        return {"side": side, "ev_per_dollar": 0.0, "kelly": 0.0}
    ev = p_win / price - 1.0
    kelly = max(0.0, (p_win - price) / (1.0 - price))
    return {"side": side, "ev_per_dollar": round(ev, 4), "kelly": round(kelly, 4)}


def scan(base: str, limit: int | None, workers: int) -> dict:
    markets = bayes_anchor_markets(base)
    if limit:
        markets = markets[:limit]
    print(f"anchored markets to check: {len(markets)}", file=sys.stderr)

    def check(market: dict) -> dict:
        anchor = market["anchor"]
        source, ref = anchor.get("source"), str(anchor.get("ref"))
        time.sleep(0.1)  # stay polite under concurrency
        now = manifold_now(ref) if source == "manifold" else metaculus_now(ref)
        p_bayes = (market.get("marginals") or {}).get("yes")
        row = {
            "id": market["id"],
            "title": market.get("title", "")[:110],
            "source": source,
            "url": now.get("url") or anchor.get("url"),
            "p_bayes": p_bayes,
            "p_anchor_import": anchor.get("value"),
            "p_ext_now": now.get("probability"),
            "fetch_ok": now.get("ok", False),
            "is_resolved": now.get("is_resolved", False),
            "resolution": now.get("resolution"),
            "closed": now.get("closed", False),
            "ext_volume": now.get("volume"),
            "ext_bettors": now.get("bettors"),
        }
        if row["fetch_ok"] and row["p_ext_now"] is not None and p_bayes is not None:
            row["gap_now"] = round(p_bayes - row["p_ext_now"], 4)
            row["anchor_drift"] = round(row["p_ext_now"] - (anchor.get("value") or 0), 4)
            row.update(edge_metrics(p_bayes, row["p_ext_now"]))
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(check, markets))

    fetched = [r for r in rows if r["fetch_ok"]]
    priced = [r for r in fetched if r.get("gap_now") is not None]
    resolved = [r for r in fetched if r["is_resolved"]]
    closed_only = [r for r in fetched if r["closed"] and not r["is_resolved"]]
    live = [r for r in priced if not r["is_resolved"] and not r["closed"]]
    live.sort(key=lambda r: abs(r["gap_now"]), reverse=True)

    gaps = [abs(r["gap_now"]) for r in live]
    summary = {
        "checked": len(rows),
        "fetch_failed": len(rows) - len(fetched),
        "resolved_externally": len(resolved),
        "closed_not_resolved": len(closed_only),
        "live_compared": len(live),
        "mean_abs_gap": round(sum(gaps) / len(gaps), 4) if gaps else None,
        "n_gap_over_5pp": sum(1 for g in gaps if g > 0.05),
        "n_gap_over_10pp": sum(1 for g in gaps if g > 0.10),
        "n_gap_over_20pp": sum(1 for g in gaps if g > 0.20),
    }
    return {"summary": summary, "live_sorted": live, "resolved": resolved,
            "closed_not_resolved": closed_only,
            "failed": [r for r in rows if not r["fetch_ok"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BAYES_BASE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default=None, help="write full JSON report here")
    args = parser.parse_args()

    report = scan(args.base, args.limit, args.workers)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))
        print(f"report written: {args.out}", file=sys.stderr)

    print(json.dumps(report["summary"], indent=1))
    print("\nTOP DIVERGENCES (live, |bayes - external now|):")
    for row in report["live_sorted"][:20]:
        print(
            f"  {row['gap_now']:+.2f}  bayes={row['p_bayes']:.2f} ext={row['p_ext_now']:.2f}"
            f"  [{row['source']}] {row['title']}"
        )
    if report["resolved"]:
        print("\nRESOLVED EXTERNALLY BUT STILL OPEN IN BAYES:")
        for row in report["resolved"][:15]:
            print(f"  resolved={row['resolution']}  bayes={row['p_bayes']}  {row['title']}")


if __name__ == "__main__":
    main()
