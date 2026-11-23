#!/usr/bin/env python3
"""Calibrator bot: trade anchored markets toward their live external forecast.

Calibration by trading, never by privileged overwrite: every adjustment is a
probability edit under the calibrator account, so it leaves an auditable order
trail, pays/stakes like any other participant, and propagates through the
combinatorial joint to every linked market.

Anchor refresh: Manifold and Polymarket values are fetched live (public read-only
APIs). Metaculus is auth-gated — with METACULUS_TOKEN set we refresh via the API;
otherwise the stored value from the last browser harvest is used and its age is
logged.

Exchange (report-only by default): set FUTARCHY_API_KEY and optionally
FUTARCHY_API_URL, then pass --execute to trade. Use --paper (or
CALIBRATOR_BACKEND=paper) for the legacy BAYES_API path.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

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
LOG = logging.getLogger("calibrator")
_TERMINAL_STATUSES = {"resolved", "void", "voided", "closed"}


@dataclass
class AnchorFetch:
    """Result of fetching an upstream anchor probability."""

    probability: float | None = None
    stale: bool = False
    resolved_upstream: bool = False
    resolution: str | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def http_json(url, payload=None, headers=None, timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_manifold_status(ref: str) -> AnchorFetch:
    """Fetch Manifold market probability or upstream resolution status."""
    try:
        m = http_json(f"https://api.manifold.markets/v0/market/{ref}")
        if not isinstance(m, dict):
            return AnchorFetch()
        if m.get("isResolved"):
            res = m.get("resolution")
            return AnchorFetch(
                probability=None,
                resolved_upstream=True,
                resolution=str(res) if res is not None else "UNKNOWN",
            )
        p = m.get("probability")
        return AnchorFetch(probability=float(p) if p is not None else None)
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        return AnchorFetch()


def fetch_manifold(ref: str) -> float | None:
    return fetch_manifold_status(ref).probability


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    return []


def fetch_polymarket_status(ref: str) -> AnchorFetch:
    """Fetch Polymarket Gamma API market probability or upstream resolution."""
    try:
        m = http_json(f"https://gamma-api.polymarket.com/markets/{ref}")
        if not isinstance(m, dict):
            return AnchorFetch()

        outcomes = [str(o).strip().lower() for o in _parse_json_list(m.get("outcomes"))]
        raw_prices = _parse_json_list(m.get("outcomePrices"))
        prices: list[float] = []
        for item in raw_prices:
            try:
                prices.append(float(item))
            except (TypeError, ValueError):
                prices = []
                break

        yes_idx = outcomes.index("yes") if "yes" in outcomes else 0
        closed = bool(
            m.get("closed")
            or m.get("resolved")
            or str(m.get("umaResolutionStatus", "")).lower() == "resolved"
        )
        if closed:
            resolution = m.get("resolution")
            if resolution is None and prices and outcomes and len(prices) == len(outcomes):
                for outcome_name, price in zip(outcomes, prices):
                    if price >= 0.99:
                        resolution = outcome_name.upper()
                        break
            return AnchorFetch(
                probability=None,
                resolved_upstream=True,
                resolution=str(resolution) if resolution is not None else "CLOSED",
            )

        if not prices or yes_idx >= len(prices):
            return AnchorFetch()
        prob = prices[yes_idx]
        if not 0.0 <= prob <= 1.0:
            return AnchorFetch()
        return AnchorFetch(probability=prob)
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        return AnchorFetch()


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


def fetch_anchor_status(anchor: dict, token: str) -> AnchorFetch:
    """Return live/fresh-enough anchor probability and upstream status."""
    source, ref = anchor["source"], anchor["ref"]
    if source == "manifold":
        result = fetch_manifold_status(ref)
        time.sleep(0.35)
        return result
    if source == "polymarket":
        result = fetch_polymarket_status(ref)
        time.sleep(0.2)
        return result
    if source == "metaculus":
        target = fetch_metaculus(ref, token) if token else None
        if target is not None:
            return AnchorFetch(probability=target)
        age = anchor_age_hours(anchor.get("fetchedAt", ""))
        if age <= STALE_WARN_HOURS:
            val = anchor.get("value")
            return AnchorFetch(probability=float(val) if val is not None else None)
        return AnchorFetch(probability=None, stale=True)
    return AnchorFetch()


def fetch_anchor(anchor: dict, token: str) -> tuple[float | None, bool]:
    """Return the live/fresh-enough anchor and whether a miss was stale."""
    result = fetch_anchor_status(anchor, token)
    return result.probability, result.stale


def append_log(entry: dict, path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _connected_market_ids(graph_markets: list[dict]) -> set[str]:
    """Return market IDs with degree > 0 (at least one parent or child)."""
    var_to_id = {
        str(m["variableId"]): str(m["id"])
        for m in graph_markets
        if isinstance(m, dict) and "variableId" in m and "id" in m
    }
    connected: set[str] = set()
    for m in graph_markets:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id", ""))
        parents = m.get("parents") or []
        if parents:
            if mid:
                connected.add(mid)
            for parent_var in parents:
                parent_mid = var_to_id.get(str(parent_var))
                if parent_mid:
                    connected.add(parent_mid)
    return connected


@dataclass
class ExchangeConfig:
    min_balance: Decimal = Decimal("100")
    run_budget: Decimal = Decimal("50")
    min_gap: Decimal = Decimal("0.02")
    max_step: Decimal = Decimal("0.05")
    execute: bool = False
    only_connected: bool = True


class HttpExchange:
    """Thin synchronous HTTP client; tests inject ``httpx.MockTransport``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=15,
        )

    def __enter__(self) -> HttpExchange:
        return self

    def __exit__(self, *_exc) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        response = self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as err:
            try:
                detail = response.json().get("error", {}).get("message")
            except (AttributeError, ValueError):
                detail = response.text
            raise RuntimeError(
                f"exchange {method} {path} failed ({response.status_code}): {detail}"
            ) from err
        return response.json()

    def account(self) -> dict:
        return self._request("GET", "/v1/me")

    def graph_markets(self) -> list[dict]:
        data = self._request("GET", "/v1/net/markets", params={"fields": "graph"})
        markets = data.get("markets")
        if not isinstance(markets, list):
            raise ValueError("graph response missing markets list")
        return markets

    def market(self, market_id: str) -> dict:
        return self._request("GET", f"/v1/net/markets/{market_id}")

    def preview(self, body: dict) -> dict:
        return self._request("POST", "/v1/net/orders/preview", json=body)

    def place(self, body: dict) -> dict:
        return self._request("POST", "/v1/net/orders", json=body)


def run_exchange(
    anchors: list[dict],
    client: HttpExchange,
    config: ExchangeConfig,
    *,
    token: str = "",
    log_path: Path = LOG_PATH,
) -> dict:
    """Calibrate the exchange book within balance and new-stake limits."""
    stats = {
        "checked": 0, "traded": 0, "reported": 0, "within_min_gap": 0,
        "stale_skipped": 0, "fetch_failed": 0, "resolved_upstream": 0,
        "isolated_skipped": 0, "market_missing": 0,
        "budget_skipped": 0, "stake": "0",
    }
    available = Decimal(str(client.account()["available"]))
    if available < config.min_balance:
        LOG.warning(
            "LOW BALANCE: calibrator has %s available (< %s); skipping all "
            "trades. Top up the calibrator service account externally.",
            available, config.min_balance,
        )
        return stats

    graph_by_id: dict[str, dict] = {}
    connected_ids: set[str] | None = None
    if config.only_connected and hasattr(client, "graph_markets"):
        try:
            graph_markets = client.graph_markets()
            graph_by_id = {
                str(m["id"]): m
                for m in graph_markets
                if isinstance(m, dict) and "id" in m
            }
            connected_ids = _connected_market_ids(graph_markets)
        except (RuntimeError, KeyError, TypeError, ValueError) as err:
            LOG.warning(
                "graph endpoint unavailable (%s); falling back to all markets",
                err,
            )
            graph_by_id = {}
            connected_ids = None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidates: list[tuple[Decimal, dict, Decimal, dict]] = []

    # Phase 1: filter, fetch upstream anchors, and measure gaps.
    for anchor in anchors:
        stats["checked"] += 1
        mid = str(anchor["marketId"])
        if connected_ids is not None and mid in graph_by_id and mid not in connected_ids:
            stats["isolated_skipped"] += 1
            continue

        fetched = fetch_anchor_status(anchor, token)
        if fetched.resolved_upstream:
            stats["resolved_upstream"] += 1
            LOG.warning(
                "upstream resolved: marketId=%s resolution=%s (source=%s ref=%s)",
                mid, fetched.resolution or "UNKNOWN",
                anchor["source"], anchor["ref"],
            )
            continue
        if fetched.probability is None:
            stats["stale_skipped" if fetched.stale else "fetch_failed"] += 1
            continue
        target = min(
            max(Decimal(str(fetched.probability)), Decimal("0.01")),
            Decimal("0.99"),
        )

        market = graph_by_id.get(mid)
        if (
            market is None
            or "variableId" not in market
            or not isinstance(market.get("marginals"), dict)
            or "yes" not in market["marginals"]
        ):
            try:
                market = client.market(mid)
            except RuntimeError:
                stats["market_missing"] += 1
                continue

        if str(market.get("status", "active")).lower() in _TERMINAL_STATUSES:
            continue

        current = Decimal(str(market["marginals"]["yes"]))
        gap = target - current
        if abs(gap) < config.min_gap:
            stats["within_min_gap"] += 1
            continue

        candidates.append((abs(gap), anchor, target, market))

    # Phase 2: prioritize largest |gap| first so limited run_budget always
    # fixes the biggest mispricings first (Timsort preserves input order on ties).
    candidates.sort(key=lambda item: item[0], reverse=True)

    spent = Decimal("0")
    for _, anchor, target, market in candidates:
        mid = str(anchor["marketId"])
        # Re-read live marginal after prior trades so Bayesian propagation from
        # an earlier connected trade does not cause overshoot or whipsaw.
        if config.execute and stats["traded"] > 0:
            try:
                market = client.market(mid)
            except RuntimeError:
                stats["market_missing"] += 1
                continue
            if str(market.get("status", "active")).lower() in _TERMINAL_STATUSES:
                continue

        current = Decimal(str(market["marginals"]["yes"]))
        gap = target - current
        if abs(gap) < config.min_gap:
            stats["within_min_gap"] += 1
            continue

        step_target = current + max(-config.max_step, min(config.max_step, gap))
        step_target = min(max(step_target, Decimal("0.01")), Decimal("0.99"))
        step_target = step_target.quantize(Decimal("0.000001"))
        body = {
            "variableId": market["variableId"],
            "outcomeId": "yes",
            "target": float(step_target),
        }
        entry = {
            "at": now, "venue": "net", "marketId": anchor["marketId"],
            "source": anchor["source"], "ref": anchor["ref"],
            "price": float(current), "anchor": float(target),
            "stepTarget": float(step_target),
        }

        if not config.execute:
            stats["reported"] += 1
            print(json.dumps({**entry, "reportOnly": True}))
            continue

        try:
            preview = client.preview(body)
            stake = Decimal(str(preview["stake"]))
            if stake > config.run_budget - spent:
                stats["budget_skipped"] += 1
                print(json.dumps({**entry, "skippedBudget": str(stake)}))
                continue
            order = client.place(body)
            actual_stake = Decimal(str(order.get("stake", preview["stake"])))
            spent += actual_stake
            stats["traded"] += 1
            stats["stake"] = str(spent)
            entry.update({
                "orderId": order.get("orderId"),
                "stake": str(actual_stake),
            })
        except (RuntimeError, KeyError, ValueError) as err:
            entry["error"] = str(err)[:120]
        append_log(entry, log_path)

    return stats


def run_paper() -> None:
    if not API:
        sys.exit("BAYES_API is required (e.g. http://127.0.0.1:3206)")
    doc = json.loads(ANCHORS_PATH.read_text())
    anchors = doc["anchors"]
    token = os.environ.get("METACULUS_TOKEN", "")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    spent = 0.0
    stats = {"checked": 0, "traded": 0, "within_deadband": 0, "stale_skipped": 0,
             "fetch_failed": 0, "resolved_upstream": 0, "market_missing": 0, "cost": 0.0}

    for anchor in anchors:
        stats["checked"] += 1
        source, ref = anchor["source"], anchor["ref"]
        fetched = fetch_anchor_status(anchor, token)
        if fetched.resolved_upstream:
            stats["resolved_upstream"] += 1
            LOG.warning(
                "upstream resolved: marketId=%s resolution=%s (source=%s ref=%s)",
                anchor["marketId"], fetched.resolution or "UNKNOWN", source, ref,
            )
            continue
        if fetched.probability is None:
            stats["stale_skipped" if fetched.stale else "fetch_failed"] += 1
            continue
        target = min(max(float(fetched.probability), 0.01), 0.99)

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
        append_log(entry)
        if spent >= BUDGET:
            entry = {"at": now, "haltedBudget": spent}
            append_log(entry)
            break

    print(json.dumps(stats))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="place exchange trades")
    mode.add_argument(
        "--report-only", action="store_true",
        help="report exchange edits without POST requests (default)",
    )
    parser.add_argument("--paper", action="store_true", help="force the legacy paper backend")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    api_key = os.environ.get("FUTARCHY_API_KEY", "")
    force_paper = args.paper or os.environ.get("CALIBRATOR_BACKEND", "").lower() == "paper"
    if not api_key or force_paper:
        run_paper()
        return

    anchors = json.loads(ANCHORS_PATH.read_text())["anchors"]
    config = ExchangeConfig(
        min_balance=Decimal(os.environ.get("CALIBRATOR_MIN_BALANCE", "100")),
        run_budget=Decimal(os.environ.get("CALIBRATOR_RUN_BUDGET", "50")),
        min_gap=Decimal(os.environ.get("CALIBRATOR_MIN_GAP", "0.02")),
        max_step=Decimal(os.environ.get("CAL_MAX_STEP", "0.05")),
        execute=args.execute,
        only_connected=_env_bool("CALIBRATOR_ONLY_CONNECTED", True),
    )
    with HttpExchange(
        os.environ.get("FUTARCHY_API_URL", "http://127.0.0.1:3210"), api_key,
    ) as client:
        stats = run_exchange(
            anchors, client, config, token=os.environ.get("METACULUS_TOKEN", ""),
        )
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
