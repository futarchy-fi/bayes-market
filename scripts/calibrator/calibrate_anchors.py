#!/usr/bin/env python3
"""Calibrator bot: trade anchored markets toward their live external forecast.

Calibration by trading, never by admin overwrite: every adjustment is an
LMSR probability-edit through the normal API under the `acct_calibrator`
account, so it leaves an auditable order trail, pays the maker like anyone
else, and propagates through the combinatorial joint to every linked market.

Anchor refresh: Manifold values are fetched live (public API). Metaculus is
auth-gated — with METACULUS_TOKEN set we refresh via the API; otherwise the
stored value from the last browser harvest is used and its age is logged.

Run (staging): BAYES_API=http://127.0.0.1:3206 python3 scripts/calibrator/calibrate_anchors.py
Env: BAYES_API (required), CAL_DEADBAND (default 0.015), CAL_MAX_STEP (0.05),
     CAL_BUDGET (2000 cost units/run), CAL_LOG (default scripts/calibrator/trades.jsonl),
     METACULUS_TOKEN (optional), CAL_DRY_RUN=1 to preview.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("BAYES_API", "").rstrip("/")
DEADBAND = float(os.environ.get("CAL_DEADBAND", "0.015"))
MAX_STEP = float(os.environ.get("CAL_MAX_STEP", "0.05"))
BUDGET = float(os.environ.get("CAL_BUDGET", "2000"))
DRY = os.environ.get("CAL_DRY_RUN") == "1"
ANCHORS_PATH = Path(os.environ.get(
    "CAL_ANCHORS", "scripts/import/data/anchors.json"))
LOG_PATH = Path(os.environ.get("CAL_LOG", "scripts/calibrator/trades.jsonl"))
UA = "bayes-market-calibrator/1.0 (futarchy.ai)"
STALE_WARN_HOURS = 72


def http_json(url, payload=None, headers=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_manifold(ref: str) -> float | None:
    try:
        m = http_json(f"https://api.manifold.markets/v0/market/{ref}")
        if m.get("isResolved"):
            return None
        p = m.get("probability")
        return float(p) if p is not None else None
    except (urllib.error.URLError, ValueError, KeyError):
        return None


def fetch_metaculus(ref: str, token: str) -> float | None:
    try:
        q = http_json(f"https://www.metaculus.com/api/posts/{ref}/",
                      headers={"Authorization": f"Token {token}"})
        agg = (q.get("question") or {}).get("aggregations", {})
        latest = (agg.get("recency_weighted") or {}).get("latest") or {}
        centers = latest.get("centers") or []
        return float(centers[0]) if centers else None
    except (urllib.error.URLError, ValueError, KeyError, IndexError):
        return None


def anchor_age_hours(fetched_at: str) -> float:
    try:
        then = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600
    except ValueError:
        return 1e9


def main():
    if not API:
        sys.exit("BAYES_API is required (e.g. http://127.0.0.1:3206)")
    doc = json.loads(ANCHORS_PATH.read_text())
    anchors = doc["anchors"]
    token = os.environ.get("METACULUS_TOKEN", "")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    spent = 0.0
    stats = {"checked": 0, "traded": 0, "within_deadband": 0, "stale_skipped": 0,
             "fetch_failed": 0, "market_missing": 0, "cost": 0.0}

    for anchor in anchors:
        stats["checked"] += 1
        source, ref = anchor["source"], anchor["ref"]
        target = None
        stale = False
        if source == "manifold":
            target = fetch_manifold(ref)
            time.sleep(0.35)
        elif source == "metaculus":
            if token:
                target = fetch_metaculus(ref, token)
            if target is None:
                age = anchor_age_hours(anchor.get("fetchedAt", ""))
                if age <= STALE_WARN_HOURS:
                    target = anchor.get("value")
                else:
                    stale = True
        if target is None:
            stats["stale_skipped" if stale else "fetch_failed"] += 1
            continue
        target = min(max(float(target), 0.01), 0.99)

        try:
            market = http_json(f"{API}/v1/markets/{anchor['marketId']}")["market"]
        except (urllib.error.URLError, KeyError, ValueError):
            stats["market_missing"] += 1
            continue
        if market.get("status") != "active":
            continue
        price = float(market["marginals"]["yes"])
        gap = target - price
        if abs(gap) < DEADBAND:
            stats["within_deadband"] += 1
            continue
        step_target = price + max(-MAX_STEP, min(MAX_STEP, gap))
        step_target = min(max(step_target, 0.01), 0.99)

        entry = {"at": now, "marketId": anchor["marketId"], "source": source,
                 "ref": ref, "price": price, "anchor": target,
                 "stepTarget": round(step_target, 6)}
        if DRY:
            entry["dryRun"] = True
            print(json.dumps(entry))
            continue
        try:
            resp = http_json(
                f"{API}/v1/markets/{anchor['marketId']}/orders/probability-edit",
                payload={
                    "accountId": "acct_calibrator",
                    "variableId": market["variableId"],
                    "target": {"kind": "marginal", "outcomeId": "yes",
                               "probability": round(step_target, 6)},
                    "context": [],
                })
            fill = (resp.get("order") or {}).get("jointRepricing") or {}
            cost = abs(float(fill.get("cost", 0.0)))
            spent += cost
            stats["traded"] += 1
            stats["cost"] = round(stats["cost"] + cost, 4)
            entry.update({"orderId": (resp.get("order") or {}).get("id"),
                          "cost": fill.get("cost"),
                          "repriced": len(fill.get("marketsRepriced", []))})
        except urllib.error.HTTPError as err:
            entry["error"] = f"HTTP {err.code}"
        except (urllib.error.URLError, ValueError) as err:
            entry["error"] = str(err)[:120]
        with LOG_PATH.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        if spent >= BUDGET:
            entry = {"at": now, "haltedBudget": spent}
            with LOG_PATH.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
            break

    print(json.dumps(stats))


if __name__ == "__main__":
    main()
