#!/usr/bin/env python3
"""Minimal Bayes Market backend restoring the documented HTTP surface."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FORMULA_SCHEMA_MODULE_PATH = Path(__file__).with_name("formula_schema.py")
_FORMULA_SCHEMA_SPEC = importlib.util.spec_from_file_location(
    "bayes_market_formula_schema",
    FORMULA_SCHEMA_MODULE_PATH,
)
if _FORMULA_SCHEMA_SPEC is None or _FORMULA_SCHEMA_SPEC.loader is None:
    raise RuntimeError(f"Unable to load formula schema module from {FORMULA_SCHEMA_MODULE_PATH}")
formula_schema = importlib.util.module_from_spec(_FORMULA_SCHEMA_SPEC)
_FORMULA_SCHEMA_SPEC.loader.exec_module(formula_schema)

INITIAL_MARKETS: dict[str, dict[str, Any]] = {
    "m1": {
        "id": "m1",
        "title": "ETH Price > $3000 on March 15",
        "description": "Will ETH trade above $3000 at any point on March 15, 2026?",
        "variableId": "eth_price_gt_3000_mar15",
        "status": "active",
        "outcomes": [
            {"id": "yes", "name": "Yes"},
            {"id": "no", "name": "No"},
        ],
        "marginals": {"yes": 0.65, "no": 0.35},
        "liquidity": 150000.0,
        "volume": 45000.0,
        "created_at": "2026-03-01T00:00:00Z",
        "expires_at": "2026-03-15T23:59:59Z",
    },
    "m2": {
        "id": "m2",
        "title": "BTC ETF Approval This Week",
        "description": "Will a new BTC ETF be approved this week?",
        "variableId": "btc_etf_approval_week",
        "status": "active",
        "outcomes": [
            {"id": "yes", "name": "Yes"},
            {"id": "no", "name": "No"},
            {"id": "delayed", "name": "Delayed"},
        ],
        "marginals": {"yes": 0.25, "no": 0.60, "delayed": 0.15},
        "liquidity": 89000.0,
        "volume": 23000.0,
        "created_at": "2026-03-08T00:00:00Z",
        "expires_at": "2026-03-14T23:59:59Z",
    },
    "m3": {
        "id": "m3",
        "title": "Fed Rate Cut in March",
        "description": "Will the Fed announce a rate cut in March 2026?",
        "variableId": "fed_rate_cut_mar_2026",
        "status": "resolved",
        "resolution": "no",
        "outcomes": [
            {"id": "yes", "name": "Yes"},
            {"id": "no", "name": "No"},
        ],
        "marginals": {"yes": 0.12, "no": 0.88},
        "liquidity": 200000.0,
        "volume": 120000.0,
        "created_at": "2026-02-15T00:00:00Z",
        "expires_at": "2026-03-10T00:00:00Z",
    },
}

ALLOWED_MARKET_STATUSES = frozenset({"active", "resolved", "closed", "draft"})
MARKET_SUMMARY_FIELDS = (
    "id",
    "title",
    "status",
    "liquidity",
    "volume",
    "expires_at",
)

ACCOUNT_RISK_LIMIT = 100.0
MAX_EVENT_FORMULA_CLAUSES = 16
MAX_EVENT_FORMULA_CLAUSE_LITERALS = 8
ALLOWED_EVENT_TRADE_SIDES = frozenset({"buy", "sell"})
AGENT_ID_HEADER = "X-Bayes-Agent-Id"
AUTH_REQUIRE_AGENT_ID_ENV = "BAYES_REQUIRE_AGENT_ID"
RATE_LIMIT_PER_MIN_ENV = "BAYES_RATE_LIMIT_PER_MIN"
RATE_LIMIT_POLICY_VERSION = "bayes-agent-id-v1"
RATE_LIMIT_WINDOW_SECONDS = 60
ENGINE_MODE = "EXACT"
ENGINE_BACKEND = "junction_tree"
ENGINE_VERSION = "0.1.0"
ENGINE_PRECISION = "float64"
ENGINE_COMPILE_TYPE = "junction_tree"
ENGINE_INFERENCE_SAMPLE_LIMIT = 100

MARKETS: dict[str, dict[str, Any]] = deepcopy(INITIAL_MARKETS)
CONDITIONAL_MARGINALS: dict[str, dict[str, dict[str, float]]] = {}
ORDERS: dict[str, dict[str, Any]] = {}
COMMANDS: dict[str, dict[str, Any]] = {}
EVENTS: dict[str, dict[str, Any]] = {}
TERMINAL_OUTCOMES: dict[str, dict[str, Any]] = {}
IDEMPOTENCY_KEYS: dict[tuple[str, str, str], str] = {}
MARKET_EVENT_SEQUENCES: dict[str, int] = {}
LAST_EVENT_HASHES: dict[str, str] = {}
MARKET_WRITE_LOCKS: dict[str, threading.Lock] = {}
_LOCK_REGISTRY_LOCK = threading.Lock()
ACCOUNT_RISK: dict[str, dict[str, Any]] = {}
MARKET_ENGINE_STATS: dict[str, dict[str, Any]] = {}
_RATE_LIMIT_WINDOWS: dict[str, deque[float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()
ORDER_COUNTER = 0
COMMAND_COUNTER = 0
EVENT_COUNTER = 0
GENESIS_EVENT_HASH = f"sha256:{hashlib.sha256(b'').hexdigest()}"


def get_market_write_lock(market_id: str) -> threading.Lock:
    """Serialize same-market journal appends so seq and prevEventHash cannot fork."""
    with _LOCK_REGISTRY_LOCK:
        lock = MARKET_WRITE_LOCKS.get(market_id)
        if lock is None:
            lock = threading.Lock()
            MARKET_WRITE_LOCKS[market_id] = lock
        return lock


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def reset_state() -> None:
    global ORDER_COUNTER, COMMAND_COUNTER, EVENT_COUNTER
    MARKETS.clear()
    MARKETS.update(deepcopy(INITIAL_MARKETS))
    CONDITIONAL_MARGINALS.clear()
    ORDERS.clear()
    COMMANDS.clear()
    EVENTS.clear()
    TERMINAL_OUTCOMES.clear()
    IDEMPOTENCY_KEYS.clear()
    MARKET_EVENT_SEQUENCES.clear()
    LAST_EVENT_HASHES.clear()
    MARKET_WRITE_LOCKS.clear()
    ACCOUNT_RISK.clear()
    MARKET_ENGINE_STATS.clear()
    reset_rate_limit_state()
    ORDER_COUNTER = 0
    COMMAND_COUNTER = 0
    EVENT_COUNTER = 0


def generate_order_id() -> str:
    global ORDER_COUNTER
    ORDER_COUNTER += 1
    return f"ord_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{ORDER_COUNTER:06d}"


def generate_command_id() -> str:
    global COMMAND_COUNTER
    COMMAND_COUNTER += 1
    return f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{COMMAND_COUNTER:06d}"


def generate_event_id() -> str:
    global EVENT_COUNTER
    EVENT_COUNTER += 1
    return f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{EVENT_COUNTER:06d}"


def canonical_json_hash(data: object) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path[:-1]
    return path


def read_bool_env(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def read_non_negative_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(0, parsed)


AUTH_REQUIRE_AGENT_ID = read_bool_env(AUTH_REQUIRE_AGENT_ID_ENV, False)
RATE_LIMIT_PER_MIN = read_non_negative_int_env(RATE_LIMIT_PER_MIN_ENV, 0)


def reset_rate_limit_state() -> None:
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_WINDOWS.clear()


def request_agent_id(headers: Any) -> str:
    return (headers.get(AGENT_ID_HEADER) or "").strip()


def enforce_agent_id(agent_id: str) -> None:
    if AUTH_REQUIRE_AGENT_ID and not agent_id:
        raise ApiError(
            401,
            "missing_agent_id",
            "Missing Bayes agent id header",
            {"header": AGENT_ID_HEADER},
        )


def enforce_rate_limit(agent_id: str) -> None:
    if RATE_LIMIT_PER_MIN <= 0 or not agent_id:
        return

    now = time.monotonic()

    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_WINDOWS.get(agent_id)
        if bucket is None:
            bucket = deque()
            _RATE_LIMIT_WINDOWS[agent_id] = bucket

        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_PER_MIN:
            retry_after_seconds = max(1, math.ceil(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
            raise ApiError(
                429,
                "rate_limit_exceeded",
                "Rate limit exceeded for Bayes agent id",
                {
                    "agentId": agent_id,
                    "limit": RATE_LIMIT_PER_MIN,
                    "windowSeconds": RATE_LIMIT_WINDOW_SECONDS,
                    "retryAfterSeconds": retry_after_seconds,
                    "policyVersion": RATE_LIMIT_POLICY_VERSION,
                },
            )

        bucket.append(now)


def rate_limit_headers(agent_id: str) -> dict[str, str]:
    if RATE_LIMIT_PER_MIN <= 0 or not agent_id:
        return {}

    now = time.monotonic()
    now_epoch = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_WINDOWS.get(agent_id)
        active_entries = [] if bucket is None else [timestamp for timestamp in bucket if timestamp > cutoff]

    used = len(active_entries)
    remaining = max(0, RATE_LIMIT_PER_MIN - used)
    if active_entries:
        seconds_until_reset = max(0.0, RATE_LIMIT_WINDOW_SECONDS - (now - active_entries[0]))
    else:
        seconds_until_reset = float(RATE_LIMIT_WINDOW_SECONDS)

    return {
        "X-RateLimit-Limit": str(RATE_LIMIT_PER_MIN),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(math.ceil(now_epoch + seconds_until_reset)),
        "X-RateLimit-Policy": RATE_LIMIT_POLICY_VERSION,
    }


def make_meta(**extra: object) -> dict[str, Any]:
    meta: dict[str, Any] = {"timestamp": utc_timestamp()}
    meta.update(extra)
    return meta


def error_payload(code: str, message: str, **details: object) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": make_meta(),
    }


def health_payload() -> dict[str, Any]:
    return {
        "service": "bayes-market",
        "status": "ok",
        "timestamp": utc_timestamp(),
    }


def service_index_payload() -> dict[str, Any]:
    return {
        "service": "bayes-market",
        "status": "ok",
        "routes": {
            "health": ["/health", "/healthz"],
            "markets": [
                "/v1/markets",
                "/v1/markets/{id}",
                "/v1/markets/{id}/events",
                "/v1/markets/{id}/engine-stats",
            ],
            "orders": [
                "POST /v1/markets/{id}/orders/probability-edit",
                "POST /v1/markets/{id}/orders/event-trade",
            ],
            "accounts": ["/v1/accounts/{id}/risk"],
        },
        "meta": make_meta(),
    }


def market_summary(market: dict[str, Any]) -> dict[str, Any]:
    return {field: market[field] for field in MARKET_SUMMARY_FIELDS}


def percentile_ms(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return round(ordered[index], 3)


def inference_stats_payload(samples_ms: list[float]) -> dict[str, Any]:
    if not samples_ms:
        return {
            "count": 0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
        }

    count = len(samples_ms)
    return {
        "count": count,
        "mean_ms": round(sum(samples_ms) / count, 3),
        "p50_ms": percentile_ms(samples_ms, 0.50),
        "p95_ms": percentile_ms(samples_ms, 0.95),
        "p99_ms": percentile_ms(samples_ms, 0.99),
    }


def ensure_market_engine_state(market_id: str) -> dict[str, Any]:
    state = MARKET_ENGINE_STATS.get(market_id)
    if state is None:
        state = {
            "request_count": 0,
            "error_count": 0,
            "inference_samples_ms": [],
            "cache_hits": 0,
            "cache_misses": 0,
            "compile_id": None,
            "compile_type": None,
            "source_state_hash": None,
            "compile_time_ms": 0.0,
            "memory_bytes": 0,
            "last_updated": None,
            "cliques": [],
        }
        MARKET_ENGINE_STATS[market_id] = state
    return state


def parse_context_key_variable_ids(context_key: str) -> list[str]:
    if not context_key:
        return []

    variable_ids: list[str] = []
    for assignment in context_key.split("|"):
        variable_id, separator, _outcome_id = assignment.partition("=")
        if separator and variable_id:
            variable_ids.append(variable_id)
    return variable_ids


def clique_state_count(variable_ids: tuple[str, ...]) -> int:
    state_count = 1
    for variable_id in variable_ids:
        market = find_market_by_variable_id(variable_id)
        outcome_count = len(market["outcomes"]) if market else 0
        state_count *= max(outcome_count, 1)
    return state_count


def build_market_cliques(market_id: str) -> list[dict[str, Any]]:
    market = MARKETS[market_id]
    raw_cliques: set[tuple[str, ...]] = {(str(market["variableId"]),)}
    for context_key in CONDITIONAL_MARGINALS.get(market_id, {}):
        clique_nodes = {str(market["variableId"]), *parse_context_key_variable_ids(context_key)}
        raw_cliques.add(tuple(sorted(clique_nodes)))

    return [
        {
            "id": f"{market_id}-c{index}",
            "nodes": list(variable_ids),
            "size": len(variable_ids),
            "states": clique_state_count(variable_ids),
        }
        for index, variable_ids in enumerate(sorted(raw_cliques), start=1)
    ]


def estimate_market_engine_memory_bytes(cliques: list[dict[str, Any]]) -> int:
    return sum(int(clique["states"]) * 32 + int(clique["size"]) * 64 for clique in cliques)


def refresh_market_compile_snapshot(market_id: str, *, compile_time_ms: float | None = None) -> None:
    state = ensure_market_engine_state(market_id)
    cliques = build_market_cliques(market_id)
    source_state_hash = market_replay_state_hash(market_id)
    digest = source_state_hash.split(":", 1)[-1]
    state["compile_id"] = f"comp-{digest[:12]}"
    state["compile_type"] = ENGINE_COMPILE_TYPE
    state["source_state_hash"] = source_state_hash
    state["compile_time_ms"] = round(float(compile_time_ms or 0.0), 3)
    state["memory_bytes"] = estimate_market_engine_memory_bytes(cliques)
    state["last_updated"] = utc_timestamp()
    state["cliques"] = cliques


def record_market_engine_request(market_id: str, duration_ms: float, *, error: bool) -> None:
    state = ensure_market_engine_state(market_id)
    state["request_count"] += 1
    if error:
        state["error_count"] += 1

    samples = state["inference_samples_ms"]
    samples.append(round(float(duration_ms), 3))
    if len(samples) > ENGINE_INFERENCE_SAMPLE_LIMIT:
        del samples[:-ENGINE_INFERENCE_SAMPLE_LIMIT]


def get_market_engine_stats(market_id: str) -> tuple[dict[str, Any], int]:
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    state = MARKET_ENGINE_STATS.get(market_id)
    samples_ms = list(state["inference_samples_ms"]) if state else []
    total_cache = (int(state["cache_hits"]) + int(state["cache_misses"])) if state else 0
    cliques = list(state["cliques"]) if state and state["compile_id"] else []
    max_clique_size = max((int(clique["size"]) for clique in cliques), default=0)
    diagnostics = {
        "request_count": int(state["request_count"]) if state else 0,
        "error_count": int(state["error_count"]) if state else 0,
        "inference": inference_stats_payload(samples_ms),
        "cache": {
            "hits": int(state["cache_hits"]) if state else 0,
            "misses": int(state["cache_misses"]) if state else 0,
            "hit_rate": round(int(state["cache_hits"]) / total_cache, 4) if total_cache else 0.0,
        },
    }
    if state and state["compile_id"]:
        diagnostics["compile_time_ms"] = round(float(state["compile_time_ms"]), 3)
        diagnostics["memory_bytes"] = int(state["memory_bytes"])
        diagnostics["last_updated"] = str(state["last_updated"])

    return {
        "marketId": market_id,
        "engine": {
            "mode": ENGINE_MODE,
            "backend": ENGINE_BACKEND,
            "version": ENGINE_VERSION,
            "precision": ENGINE_PRECISION,
            "compile_id": state["compile_id"] if state else None,
            "compile_type": state["compile_type"] if state else None,
            "source_state_hash": state["source_state_hash"] if state else None,
        },
        "cliques": {
            "num_cliques": len(cliques),
            "max_clique_size": max_clique_size,
            "junction_tree_width": max(0, max_clique_size - 1),
            "cliques": deepcopy(cliques),
        },
        "diagnostics": diagnostics,
        "meta": make_meta(),
    }, 200


def round_risk_value(value: float) -> float:
    return round(float(value), 6)


def account_capacity_status(limit: float, min_asset: float) -> str:
    if min_asset <= 0:
        return "breached"
    utilization = 0.0 if limit <= 0 else (limit - min_asset) / limit
    if utilization >= 0.8:
        return "critical"
    if utilization >= 0.5:
        return "constrained"
    return "healthy"


def build_capacity_indicators(limit: float, min_asset: float) -> dict[str, Any]:
    consumed = round_risk_value(limit - min_asset)
    available = round_risk_value(min_asset)
    utilization = 0.0 if limit <= 0 else round_risk_value(consumed / limit)
    return {
        "limit": round_risk_value(limit),
        "available": available,
        "consumed": consumed,
        "utilization": utilization,
        "status": account_capacity_status(limit, min_asset),
    }


def ensure_account_risk_state(account_id: str, timestamp: str) -> dict[str, Any]:
    account = ACCOUNT_RISK.get(account_id)
    if account is None:
        account = {
            "accountId": account_id,
            "riskLimit": round_risk_value(ACCOUNT_RISK_LIMIT),
            "minAsset": round_risk_value(ACCOUNT_RISK_LIMIT),
            "updatedAt": timestamp,
            "markets": {},
        }
        ACCOUNT_RISK[account_id] = account
    return account


def preview_account_min_asset(account_id: str, impact_score: float) -> dict[str, Any]:
    account = ACCOUNT_RISK.get(account_id)
    if account is None:
        risk_limit = round_risk_value(ACCOUNT_RISK_LIMIT)
        before_min_asset = risk_limit
    else:
        risk_limit = round_risk_value(float(account["riskLimit"]))
        before_min_asset = round_risk_value(float(account["minAsset"]))

    impact_score = round_risk_value(impact_score)
    after_min_asset = round_risk_value(before_min_asset - impact_score)
    return {
        "accountId": account_id,
        "riskLimit": risk_limit,
        "beforeMinAsset": before_min_asset,
        "impactScore": impact_score,
        "afterMinAsset": after_min_asset,
    }


def sync_account_risk_state(order: dict[str, Any]) -> dict[str, Any]:
    account_id = str(order["accountId"])
    market_id = str(order["marketId"])
    timestamp = str(order["filledAt"])
    impact = round_risk_value(float(order["impactScore"]))

    account = ensure_account_risk_state(account_id, timestamp)
    before_min_asset = round_risk_value(float(account["minAsset"]))
    after_min_asset = round_risk_value(before_min_asset - impact)
    account["minAsset"] = after_min_asset
    account["updatedAt"] = timestamp

    market_risk = account["markets"].get(market_id)
    if market_risk is None:
        market_risk = {
            "marketId": market_id,
            "minAsset": round_risk_value(ACCOUNT_RISK_LIMIT),
            "capacityConsumed": 0.0,
            "utilization": 0.0,
            "commandCount": 0,
            "updatedAt": timestamp,
            "lastOrderId": None,
            "lastCommandId": None,
        }
        account["markets"][market_id] = market_risk

    market_before_min_asset = round_risk_value(float(market_risk["minAsset"]))
    market_after_min_asset = round_risk_value(market_before_min_asset - impact)
    market_risk["minAsset"] = market_after_min_asset
    market_risk["capacityConsumed"] = round_risk_value(ACCOUNT_RISK_LIMIT - market_after_min_asset)
    market_risk["utilization"] = round_risk_value(float(market_risk["capacityConsumed"]) / ACCOUNT_RISK_LIMIT)
    market_risk["commandCount"] = int(market_risk["commandCount"]) + 1
    market_risk["updatedAt"] = timestamp
    market_risk["lastOrderId"] = str(order["id"])
    market_risk["lastCommandId"] = str(order["commandId"])

    return {
        "accountId": account_id,
        "marketId": market_id,
        "beforeMinAsset": before_min_asset,
        "afterMinAsset": after_min_asset,
    }


def get_account_risk(account_id: str) -> tuple[dict[str, Any], int]:
    account = ACCOUNT_RISK.get(account_id)
    if account is None:
        raise ApiError(404, "account_not_found", "Account not found", {"accountId": account_id})

    markets = []
    for market_id in sorted(account["markets"]):
        market_risk = account["markets"][market_id]
        markets.append(
            {
                "marketId": str(market_risk["marketId"]),
                "minAsset": round_risk_value(float(market_risk["minAsset"])),
                "capacityConsumed": round_risk_value(float(market_risk["capacityConsumed"])),
                "utilization": round_risk_value(float(market_risk["utilization"])),
                "commandCount": int(market_risk["commandCount"]),
                "lastOrderId": market_risk["lastOrderId"],
                "lastCommandId": market_risk["lastCommandId"],
                "updatedAt": str(market_risk["updatedAt"]),
            }
        )

    min_asset = round_risk_value(float(account["minAsset"]))
    return {
        "account": {
            "id": account_id,
            "risk": {
                "minAssets": {
                    "overall": min_asset,
                    "markets": markets,
                },
                "capacityIndicators": build_capacity_indicators(float(account["riskLimit"]), min_asset),
                "updatedAt": str(account["updatedAt"]),
            },
        },
        "meta": make_meta(),
    }, 200


def list_markets(query: dict[str, list[str]]) -> tuple[dict[str, Any], int]:
    statuses = query.get("status", [])
    if len(statuses) > 1:
        raise ApiError(
            400,
            "invalid_query",
            "status must be provided at most once",
            {"parameter": "status", "received": statuses},
        )

    status = statuses[0] if statuses else None
    markets = list(MARKETS.values())
    if status is not None:
        if status not in ALLOWED_MARKET_STATUSES:
            raise ApiError(
                400,
                "invalid_query",
                "status must be one of the supported market states",
                {"parameter": "status", "received": status, "allowed": sorted(ALLOWED_MARKET_STATUSES)},
            )
        markets = [market for market in markets if market["status"] == status]

    summaries = [market_summary(market) for market in markets]
    return {
        "markets": summaries,
        "count": len(summaries),
        "meta": make_meta(filters={"status": status}),
    }, 200


def get_market_detail(market_id: str) -> tuple[dict[str, Any], int]:
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    return {
        "market": deepcopy(market),
        "meta": make_meta(),
    }, 200


def parse_integer_query_param(
    query: dict[str, list[str]],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    values = query.get(name, [])
    if len(values) > 1:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be provided at most once",
            {"parameter": name, "received": values},
        )

    if not values:
        return default

    raw_value = values[0]
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be an integer",
            {"parameter": name, "received": raw_value},
        ) from exc

    if value < minimum:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be greater than or equal to {minimum}",
            {"parameter": name, "received": raw_value, "minimum": minimum},
        )

    if maximum is not None and value > maximum:
        raise ApiError(
            400,
            "invalid_query",
            f"{name} must be less than or equal to {maximum}",
            {"parameter": name, "received": raw_value, "maximum": maximum},
        )

    return value


def get_market_events(market_id: str, query: dict[str, list[str]]) -> tuple[dict[str, Any], int]:
    if market_id not in MARKETS:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    from_seq = parse_integer_query_param(query, "fromSeq", default=1, minimum=1)
    limit = parse_integer_query_param(query, "limit", default=100, minimum=1, maximum=100)

    market_events = sorted(
        (
            deepcopy(event)
            for event in EVENTS.values()
            if str(event["marketId"]) == market_id and int(event["seq"]) >= from_seq
        ),
        key=lambda event: int(event["seq"]),
    )
    page_events = market_events[:limit]
    head_seq = MARKET_EVENT_SEQUENCES.get(market_id, 0)
    head_hash = LAST_EVENT_HASHES.get(market_id, GENESIS_EVENT_HASH)
    next_from_seq = None
    if page_events:
        tail_seq = int(page_events[-1]["seq"])
        if tail_seq < head_seq:
            next_from_seq = tail_seq + 1

    return {
        "marketId": market_id,
        "events": page_events,
        "chain": {
            "genesisHash": GENESIS_EVENT_HASH,
            "headSeq": head_seq,
            "headHash": head_hash,
        },
        "pagination": {
            "fromSeq": from_seq,
            "limit": limit,
            "returned": len(page_events),
            "nextFromSeq": next_from_seq,
        },
        "meta": make_meta(),
    }, 200


def kl_divergence(previous: dict[str, float], updated: dict[str, float]) -> float:
    return round(
        sum(
            new * math.log(new / old)
            for outcome_id, new in updated.items()
            if new > 0 and (old := previous.get(outcome_id, 0.0)) > 0
        ),
        6,
    )


def find_market_by_variable_id(variable_id: str) -> dict[str, Any] | None:
    for market in MARKETS.values():
        if market["variableId"] == variable_id:
            return market
    return None


def _market_outcome_ids(market: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(outcome["id"]) for outcome in market["outcomes"])


def _resolve_market_outcome_reference(
    variable_id: str,
) -> tuple[dict[str, Any] | None, frozenset[str]]:
    referenced_market = find_market_by_variable_id(variable_id)
    if referenced_market is None:
        return None, frozenset()
    return referenced_market, frozenset(_market_outcome_ids(referenced_market))


def _preview_probability_target_distribution(
    market: dict[str, Any],
    outcome_id: str,
    probability: float,
    marginals: dict[str, float] | None = None,
) -> dict[str, float]:
    base_marginals = marginals if marginals is not None else market["marginals"]
    if not isinstance(base_marginals, dict):
        raise ValueError("market.marginals must be a dictionary")

    outcome_ids = _market_outcome_ids(market)
    if outcome_id not in outcome_ids:
        raise ValueError("target.outcomeId must match a known market outcome")
    other_ids = [candidate for candidate in outcome_ids if candidate != outcome_id]
    if not other_ids:
        raise ValueError("market must have at least two outcomes")
    try:
        previous_other_total = sum(float(base_marginals[candidate]) for candidate in other_ids)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("market.marginals must contain numeric values for all non-target outcomes") from exc

    remaining = 1.0 - probability
    if previous_other_total <= 0:
        scaled_others = {candidate: round(remaining / len(other_ids), 12) for candidate in other_ids}
    else:
        scaled_others = {
            candidate: round(float(base_marginals[candidate]) / previous_other_total * remaining, 12)
            for candidate in other_ids
        }

    updated = {outcome_id: round(probability, 12), **scaled_others}
    rounding_drift = round(1.0 - sum(updated.values()), 12)
    if rounding_drift != 0:
        updated[other_ids[-1]] = round(updated[other_ids[-1]] + rounding_drift, 12)
    return updated


def _validated_market_marginals(
    market: dict[str, Any],
    marginals: dict[str, Any],
) -> dict[str, float]:
    if not isinstance(marginals, dict):
        raise ValueError("market.marginals must be a dictionary")

    outcome_ids = _market_outcome_ids(market)
    missing_outcome_ids = [outcome_id for outcome_id in outcome_ids if outcome_id not in marginals]
    unexpected_outcome_ids = sorted(str(outcome_id) for outcome_id in marginals if str(outcome_id) not in outcome_ids)
    if missing_outcome_ids or unexpected_outcome_ids:
        raise ValueError("market.marginals must contain exactly one value for each market outcome")

    normalized: dict[str, float] = {}
    for outcome_id in outcome_ids:
        value = marginals[outcome_id]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("market.marginals must contain finite numeric values for all market outcomes")
        normalized[outcome_id] = float(value)

    if any(probability < 0 for probability in normalized.values()):
        raise ValueError("market.marginals must preserve non-negative values for all outcomes")

    if not math.isclose(sum(normalized.values()), 1.0, abs_tol=1e-9):
        raise ValueError("market.marginals must sum to 1.0")

    return normalized


def validate_structure_preserving_edit(
    market: dict[str, Any],
    normalized_payload: dict[str, Any],
    marginals: dict[str, float] | None = None,
) -> None:
    """Validate an already-normalized probability edit without mutating state."""
    target = normalized_payload["target"]
    target_outcome_id = str(target["outcomeId"])
    if target_outcome_id not in _market_outcome_ids(market):
        raise ApiError(
            400,
            "invalid_structure_preserving_edit",
            "target.outcomeId must match a known market outcome",
            {"marketId": market["id"], "outcomeId": target_outcome_id},
        )

    for index, assignment in enumerate(normalized_payload.get("context", [])):
        context_variable_id = str(assignment["variableId"])
        context_outcome_id = str(assignment["outcomeId"])
        referenced_market, allowed_outcome_ids = _resolve_market_outcome_reference(context_variable_id)
        if referenced_market is None:
            raise ApiError(
                400,
                "invalid_structure_preserving_edit",
                "context.variableId must match a known market variable",
                {"field": f"context[{index}].variableId", "received": context_variable_id},
            )
        if context_outcome_id not in allowed_outcome_ids:
            raise ApiError(
                400,
                "invalid_structure_preserving_edit",
                "context.outcomeId must match a known outcome for the referenced variable",
                {
                    "field": f"context[{index}].outcomeId",
                    "variableId": context_variable_id,
                    "received": context_outcome_id,
                },
            )

    try:
        base_marginals = _validated_market_marginals(
            market,
            marginals if marginals is not None else market["marginals"],
        )
        non_target_outcome_ids = [candidate for candidate in _market_outcome_ids(market) if candidate != target_outcome_id]
        non_target_marginals = {candidate: base_marginals[candidate] for candidate in non_target_outcome_ids}
        if float(target["probability"]) < 1.0 and sum(non_target_marginals.values()) <= 0:
            raise ValueError("market.marginals must leave positive mass for non-target outcomes")

        updated_marginals = _preview_probability_target_distribution(
            market,
            target_outcome_id,
            float(target["probability"]),
            marginals=base_marginals,
        )
    except ValueError as exc:
        raise ApiError(
            400,
            "invalid_structure_preserving_edit",
            str(exc),
            {"marketId": market["id"], "outcomeId": target_outcome_id},
        ) from exc

    if any(probability < 0 for probability in updated_marginals.values()):
        raise ApiError(
            400,
            "invalid_structure_preserving_edit",
            "target.probability must preserve a non-negative marginal distribution",
            {
                "field": "target.probability",
                "marketId": market["id"],
                "outcomeId": target_outcome_id,
                "updatedMarginals": updated_marginals,
            },
        )


def normalize_context_assignments(
    variable_id: str,
    context: Any,
) -> list[dict[str, str]]:
    if not isinstance(context, list):
        raise ApiError(400, "invalid_probability_edit", "context must be an array", {"field": "context"})

    normalized: dict[str, str] = {}
    for index, assignment in enumerate(context):
        if not isinstance(assignment, dict):
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context entries must be objects",
                {"field": f"context[{index}]"},
            )

        raw_context_variable_id = assignment.get("variableId")
        if not isinstance(raw_context_variable_id, str) or not raw_context_variable_id.strip():
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context.variableId is required",
                {"field": f"context[{index}].variableId"},
            )
        context_variable_id = raw_context_variable_id.strip()
        if context_variable_id == variable_id:
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context.variableId must not match the edited market variable",
                {"field": f"context[{index}].variableId", "variableId": context_variable_id},
            )

        raw_outcome_id = assignment.get("outcomeId")
        if not isinstance(raw_outcome_id, str) or not raw_outcome_id.strip():
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context.outcomeId is required",
                {"field": f"context[{index}].outcomeId"},
            )
        outcome_id = raw_outcome_id.strip()

        referenced_market, allowed_outcome_ids = _resolve_market_outcome_reference(context_variable_id)
        if referenced_market is None:
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context.variableId must match a known market variable",
                {"field": f"context[{index}].variableId", "received": context_variable_id},
            )
        if outcome_id not in allowed_outcome_ids:
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context.outcomeId must match a known outcome for the referenced variable",
                {
                    "field": f"context[{index}].outcomeId",
                    "variableId": context_variable_id,
                    "received": outcome_id,
                },
            )

        existing_outcome_id = normalized.get(context_variable_id)
        if existing_outcome_id is not None and existing_outcome_id != outcome_id:
            raise ApiError(
                400,
                "invalid_probability_edit",
                "context contains conflicting assignments for the same variable",
                {"field": f"context[{index}].outcomeId", "variableId": context_variable_id},
            )
        normalized[context_variable_id] = outcome_id

    return [
        {"variableId": normalized_variable_id, "outcomeId": normalized[normalized_variable_id]}
        for normalized_variable_id in sorted(normalized)
    ]


def normalize_event_formula(formula: Any) -> list[list[dict[str, Any]]]:
    return formula_schema.normalize_event_formula(
        formula,
        lookup_market_by_variable_id=find_market_by_variable_id,
        error_factory=ApiError,
        max_clauses=MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals=MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    )


def validate_event_trade_formula_market_ids(formula: Any) -> None:
    formula_schema.validate_event_trade_formula_market_ids(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
        error_factory=ApiError,
    )


def translate_event_trade_formula_for_validation(formula: Any) -> Any:
    return formula_schema.translate_event_trade_formula_for_validation(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
    )


def restore_event_trade_formula_market_ids(
    normalized_formula: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    return formula_schema.restore_event_trade_formula_market_ids(
        normalized_formula,
        lookup_market_by_variable_id=find_market_by_variable_id,
    )


def normalize_event_trade_formula(formula: Any) -> list[list[dict[str, Any]]]:
    return formula_schema.normalize_event_trade_formula(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
        lookup_market_by_variable_id=find_market_by_variable_id,
        error_factory=ApiError,
        max_clauses=MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals=MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    )


def normalize_event_trade_size(payload: dict[str, Any]) -> float:
    has_size = "size" in payload
    has_amount = "amount" in payload
    if not has_size and not has_amount:
        raise ApiError(400, "invalid_event_trade", "size is required", {"field": "size"})

    raw_size = payload.get("size") if has_size else payload.get("amount")
    field = "size" if has_size else "amount"
    if isinstance(raw_size, bool) or not isinstance(raw_size, (int, float)):
        raise ApiError(
            400,
            "invalid_event_trade",
            f"{field} must be a positive number",
            {"field": field},
        )

    normalized_size = float(raw_size)
    if normalized_size <= 0:
        raise ApiError(
            400,
            "invalid_event_trade",
            f"{field} must be a positive number",
            {"field": field, "received": normalized_size},
        )
    return normalized_size


def normalize_event_trade_side(payload: dict[str, Any]) -> str:
    raw_side = payload.get("side")
    if not isinstance(raw_side, str) or not raw_side.strip():
        raise ApiError(400, "invalid_event_trade", "side is required", {"field": "side"})

    side = raw_side.strip().lower()
    if side not in ALLOWED_EVENT_TRADE_SIDES:
        raise ApiError(
            400,
            "invalid_event_trade",
            "side must be either 'buy' or 'sell'",
            {"field": "side", "received": side, "allowed": sorted(ALLOWED_EVENT_TRADE_SIDES)},
        )
    return side


def require_atomic_event_trade_formula(formula: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return formula_schema.require_atomic_event_trade_formula(
        formula,
        error_factory=ApiError,
    )


def normalize_event_trade_payload(market_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    market = MARKETS.get(market_id)
    if market is None:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    formula = normalize_event_trade_formula(payload.get("formula"))
    literal = require_atomic_event_trade_formula(formula)
    if literal["variableId"] != market_id:
        raise ApiError(
            400,
            "invalid_event_trade",
            "formula literal must match the target market id",
            {"field": "formula[0][0].variableId", "expected": market_id, "received": literal["variableId"]},
        )

    allowed_outcome_ids = frozenset(_market_outcome_ids(market))
    if literal["outcomeId"] not in allowed_outcome_ids:
        raise ApiError(
            400,
            "invalid_event_trade",
            "formula outcome must match a known outcome for the target market",
            {
                "field": "formula[0][0].outcomeId",
                "marketId": market_id,
                "received": literal["outcomeId"],
                "allowed": sorted(allowed_outcome_ids),
            },
        )

    return {
        "formula": formula,
        "size": normalize_event_trade_size(payload),
        "side": normalize_event_trade_side(payload),
    }


def context_state_key(context: list[dict[str, str]]) -> str:
    canonical_assignments = sorted(
        (
            (str(assignment["variableId"]).strip(), str(assignment["outcomeId"]).strip())
            for assignment in context
        )
    )
    return "|".join(f"{variable_id}={outcome_id}" for variable_id, outcome_id in canonical_assignments)


def resolve_probability_edit_base_marginals(
    market_id: str,
    context: list[dict[str, str]],
) -> dict[str, float]:
    market = MARKETS[market_id]
    if not context:
        return deepcopy(market["marginals"])

    context_key = context_state_key(context)
    market_conditionals = CONDITIONAL_MARGINALS.get(market_id, {})
    return deepcopy(market_conditionals.get(context_key, market["marginals"]))


def idempotency_scope_key(market_id: str, account_id: str, idempotency_key: str) -> tuple[str, str, str]:
    return market_id, account_id, idempotency_key


def market_replay_state_hash(market_id: str) -> str:
    return canonical_json_hash(
        {
            "market": deepcopy(MARKETS[market_id]),
            "conditionalMarginals": deepcopy(CONDITIONAL_MARGINALS.get(market_id, {})),
        }
    )


def apply_probability_target(
    market: dict[str, Any],
    outcome_id: str,
    probability: float,
    marginals: dict[str, float] | None = None,
) -> dict[str, float]:
    outcome_ids = list(_market_outcome_ids(market))
    if outcome_id not in outcome_ids:
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.outcomeId must match a known market outcome",
            {"marketId": market["id"], "outcomeId": outcome_id},
        )

    if not isinstance(probability, (int, float)):
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.probability must be a number",
            {"field": "target.probability"},
        )

    probability = float(probability)
    if not (0.0 < probability < 1.0):
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.probability must be greater than 0 and less than 1",
            {"field": "target.probability", "received": probability},
        )

    if len(outcome_ids) < 2:
        raise ApiError(
            400,
            "invalid_probability_edit",
            "market must have at least two outcomes",
            {"marketId": market["id"]},
        )

    try:
        return _preview_probability_target_distribution(market, outcome_id, probability, marginals=marginals)
    except ValueError as exc:
        raise ApiError(
            400,
            "invalid_probability_edit",
            str(exc),
            {"marketId": market["id"], "outcomeId": outcome_id},
        ) from exc


def normalize_probability_value(probability: Any) -> float:
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.probability must be a number",
            {"field": "target.probability"},
        )
    return float(probability)


def preview_unconditional_probability_edit(
    market_id: str,
    payload: dict[str, Any],
    account_id: str,
) -> dict[str, Any]:
    if payload["context"]:
        raise ValueError("preview_unconditional_probability_edit requires an empty context")

    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    target = payload["target"]
    previous_marginals = deepcopy(market["marginals"])
    updated_marginals = apply_probability_target(
        market,
        str(target["outcomeId"]),
        target["probability"],
        marginals=previous_marginals,
    )
    impact_score = kl_divergence(previous_marginals, updated_marginals)
    return {
        "previousMarginals": previous_marginals,
        "newMarginals": deepcopy(updated_marginals),
        "impactScore": impact_score,
        "assetDelta": preview_account_min_asset(account_id, impact_score),
    }


def create_probability_edit_order(
    command: dict[str, Any],
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_id = str(command["marketId"])
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    payload = command["payload"]
    variable_id = str(payload["variableId"])
    target = payload["target"]
    context = payload["context"]

    if context:
        context_key = context_state_key(context)
        market_conditionals = CONDITIONAL_MARGINALS.setdefault(market_id, {})
        previous_marginals = resolve_probability_edit_base_marginals(market_id, context)
        updated_marginals = apply_probability_target(
            market,
            str(target["outcomeId"]),
            target["probability"],
            marginals=previous_marginals,
        )
        market_conditionals[context_key] = deepcopy(updated_marginals)
    else:
        if preview is None:
            preview = preview_unconditional_probability_edit(
                market_id,
                payload,
                str(command["accountId"]),
            )
        previous_marginals = deepcopy(preview["previousMarginals"])
        updated_marginals = deepcopy(preview["newMarginals"])
        market["marginals"] = deepcopy(updated_marginals)

    timestamp = utc_timestamp()
    order = {
        "id": generate_order_id(),
        "type": str(command["commandType"]),
        "marketId": market_id,
        "accountId": str(command["accountId"]),
        "commandId": str(command["commandId"]),
        "submittedAt": str(command["submittedAt"]),
        "status": "filled",
        "payload": deepcopy(payload),
        "previousMarginals": previous_marginals,
        "newMarginals": deepcopy(updated_marginals),
        "impactScore": (
            round_risk_value(float(preview["impactScore"]))
            if preview is not None
            else kl_divergence(previous_marginals, updated_marginals)
        ),
        "createdAt": timestamp,
        "filledAt": timestamp,
    }
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        order["idempotencyKey"] = idempotency_key
    ORDERS[order["id"]] = deepcopy(order)
    return order


def normalize_probability_edit_payload(market_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    variable_id = payload.get("variableId")
    if variable_id != market["variableId"]:
        raise ApiError(
            400,
            "invalid_probability_edit",
            "variableId must match market variable",
            {"expected": market["variableId"], "received": variable_id},
        )

    target = payload.get("target")
    if not isinstance(target, dict):
        raise ApiError(400, "invalid_probability_edit", "target must be an object", {"field": "target"})
    if target.get("kind") != "marginal":
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.kind must be 'marginal'",
            {"field": "target.kind", "received": target.get("kind")},
        )
    if "outcomeId" not in target:
        raise ApiError(400, "invalid_probability_edit", "target.outcomeId is required", {"field": "target.outcomeId"})
    if "probability" not in target:
        raise ApiError(
            400,
            "invalid_probability_edit",
            "target.probability is required",
            {"field": "target.probability"},
        )

    context = normalize_context_assignments(str(variable_id), payload.get("context", []))
    normalized_probability = normalize_probability_value(target["probability"])
    normalized_payload = {
        "variableId": str(variable_id),
        "target": {
            "kind": "marginal",
            "outcomeId": str(target["outcomeId"]),
            "probability": normalized_probability,
        },
        "context": deepcopy(context),
    }
    base_marginals = resolve_probability_edit_base_marginals(market_id, context)
    validate_structure_preserving_edit(market, normalized_payload, marginals=base_marginals)
    apply_probability_target(
        market,
        str(normalized_payload["target"]["outcomeId"]),
        normalized_payload["target"]["probability"],
        marginals=base_marginals,
    )
    return normalized_payload


def materialize_probability_edit_command(
    market_id: str,
    normalized_payload: dict[str, Any],
    account_id: str,
    command_id: str,
    submitted_at: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    command = {
        "schemaVersion": "bayes-command/v1",
        "commandId": command_id,
        "marketId": market_id,
        "accountId": account_id,
        "commandType": "ProbabilityEdit",
        "submittedAt": submitted_at,
        "payload": normalized_payload,
        "meta": {
            "source": "api",
        },
    }
    if idempotency_key is not None:
        command["idempotencyKey"] = idempotency_key

    COMMANDS[command_id] = deepcopy(command)
    return command


def emit_terminal_event(command: dict[str, Any], event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    market_id = str(command["marketId"])
    with get_market_write_lock(market_id):
        seq = MARKET_EVENT_SEQUENCES.get(market_id, 0) + 1
        prev_event_hash = LAST_EVENT_HASHES.get(market_id, GENESIS_EVENT_HASH)
        event = {
            "schemaVersion": "bayes-event/v1",
            "eventId": generate_event_id(),
            "marketId": market_id,
            "seq": seq,
            "commandId": str(command["commandId"]),
            "eventType": event_type,
            "emittedAt": utc_timestamp(),
            "approxFlag": False,
            "payload": deepcopy(payload),
            "prevEventHash": prev_event_hash,
        }
        event["eventHash"] = canonical_json_hash(event)
        MARKET_EVENT_SEQUENCES[market_id] = seq
        LAST_EVENT_HASHES[market_id] = str(event["eventHash"])
        EVENTS[str(event["eventId"])] = deepcopy(event)
        return event


def build_terminal_result(event: dict[str, Any]) -> dict[str, Any]:
    result = {
        "terminal": True,
        "status": "accepted" if event["eventType"] == "CommandAccepted" else "rejected",
        "eventType": str(event["eventType"]),
        "eventId": str(event["eventId"]),
        "commandId": str(event["commandId"]),
        "emittedAt": str(event["emittedAt"]),
    }
    if event["eventType"] == "CommandRejected":
        result.update(
            {
                "reasonCode": event["payload"]["reasonCode"],
                "reason": event["payload"]["reason"],
                "retryHint": event["payload"].get("retryHint"),
            }
        )
    return result


def record_terminal_outcome(
    command: dict[str, Any],
    event: dict[str, Any],
    status: int,
    response: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> None:
    command_id = str(command["commandId"])
    TERMINAL_OUTCOMES[command_id] = {
        "eventId": str(event["eventId"]),
        "eventType": str(event["eventType"]),
        "status": status,
        "response": deepcopy(response),
    }
    if scope_key is not None:
        IDEMPOTENCY_KEYS[scope_key] = command_id


def replay_terminal_outcome(command_id: str) -> tuple[dict[str, Any], int]:
    outcome = TERMINAL_OUTCOMES[command_id]
    response = deepcopy(outcome["response"])
    response.setdefault("meta", {})
    response["meta"]["replayed"] = True
    return response, int(outcome["status"])


def build_idempotency_conflict_response(
    existing_command_id: str,
    idempotency_key: str,
    market_id: str,
    account_id: str,
    command_type: str,
) -> tuple[dict[str, Any], int]:
    return {
        "error": {
            "code": "idempotency_conflict",
            "message": f"idempotencyKey is already bound to a different {command_type} payload",
            "details": {
                "idempotencyKey": idempotency_key,
                "marketId": market_id,
                "accountId": account_id,
                "existingCommandId": existing_command_id,
            },
        },
        "meta": make_meta(idempotencyKeyEcho=idempotency_key),
    }, 409


def build_terminal_rejection_response(
    command: dict[str, Any],
    code: str,
    message: str,
    details: dict[str, Any],
    retry_hint: str,
    status: int,
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    event = emit_terminal_event(
        command,
        "CommandRejected",
        {
            "reasonCode": code,
            "reason": message,
            "retryHint": retry_hint,
        },
    )
    meta_kwargs: dict[str, Any] = {}
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        meta_kwargs["idempotencyKeyEcho"] = idempotency_key
    response = {
        "error": {
            "code": code,
            "message": message,
            "details": deepcopy(details),
        },
        "result": build_terminal_result(event),
        "meta": make_meta(**meta_kwargs),
    }
    record_terminal_outcome(command, event, status, response, scope_key)
    return response, status


def build_terminal_acceptance_response(
    command: dict[str, Any],
    order: dict[str, Any],
    asset_delta: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    target = order["payload"]["target"]
    delta = {
        "variableId": order["payload"]["variableId"],
        "outcomeId": target["outcomeId"],
        "before": order["previousMarginals"][target["outcomeId"]],
        "after": order["newMarginals"][target["outcomeId"]],
    }
    if order["payload"]["context"]:
        delta["context"] = deepcopy(order["payload"]["context"])

    event = emit_terminal_event(
        command,
        "CommandAccepted",
        {
            "effects": {
                "marginalDelta": [delta],
                "assetDelta": [deepcopy(asset_delta)],
            },
            "pricing": {
                "cost": order["impactScore"],
                "fee": 0.0,
            },
            "replayStateHash": market_replay_state_hash(str(command["marketId"])),
        },
    )
    meta_kwargs: dict[str, Any] = {}
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        meta_kwargs["idempotencyKeyEcho"] = idempotency_key
    response = {
        "order": deepcopy(order),
        "result": build_terminal_result(event),
        "meta": make_meta(**meta_kwargs),
    }
    record_terminal_outcome(command, event, 201, response, scope_key)
    return response, 201


def materialize_event_trade_command(
    market_id: str,
    normalized_payload: dict[str, Any],
    account_id: str,
    command_id: str,
    submitted_at: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    command = {
        "schemaVersion": "bayes-command/v1",
        "commandId": command_id,
        "marketId": market_id,
        "accountId": account_id,
        "commandType": "EventTrade",
        "submittedAt": submitted_at,
        "payload": normalized_payload,
        "meta": {
            "source": "api",
        },
    }
    if idempotency_key is not None:
        command["idempotencyKey"] = idempotency_key

    COMMANDS[command_id] = deepcopy(command)
    return command


def create_event_trade_order(command: dict[str, Any]) -> dict[str, Any]:
    market_id = str(command["marketId"])
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    payload = command["payload"]
    literal = payload["formula"][0][0]
    outcome_id = str(literal["outcomeId"])
    price = round_risk_value(float(market["marginals"][outcome_id]))
    size = round_risk_value(float(payload["size"]))
    timestamp = utc_timestamp()
    order = {
        "id": generate_order_id(),
        "type": str(command["commandType"]),
        "marketId": market_id,
        "accountId": str(command["accountId"]),
        "commandId": str(command["commandId"]),
        "submittedAt": str(command["submittedAt"]),
        "status": "filled",
        "payload": deepcopy(payload),
        "targetMarketId": market_id,
        "targetOutcomeId": outcome_id,
        "side": str(payload["side"]),
        "size": size,
        "price": price,
        "notional": round_risk_value(size * price),
        "createdAt": timestamp,
        "filledAt": timestamp,
    }
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        order["idempotencyKey"] = idempotency_key
    ORDERS[order["id"]] = deepcopy(order)
    return order


def build_event_trade_acceptance_response(
    command: dict[str, Any],
    order: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    literal = order["payload"]["formula"][0][0]
    event = emit_terminal_event(
        command,
        "CommandAccepted",
        {
            "effects": {
                "marginalDelta": [],
                "assetDelta": [],
            },
            "pricing": {
                "cost": order["notional"],
                "fee": 0.0,
                "unitPrice": order["price"],
            },
            "trade": {
                "marketId": str(order["marketId"]),
                "outcomeId": str(literal["outcomeId"]),
                "side": str(order["side"]),
                "size": order["size"],
                "price": order["price"],
                "notional": order["notional"],
            },
            "replayStateHash": market_replay_state_hash(str(command["marketId"])),
        },
    )
    meta_kwargs: dict[str, Any] = {}
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        meta_kwargs["idempotencyKeyEcho"] = idempotency_key
    response = {
        "order": deepcopy(order),
        "result": build_terminal_result(event),
        "meta": make_meta(**meta_kwargs),
    }
    record_terminal_outcome(command, event, 201, response, scope_key)
    return response, 201


def handle_probability_edit(market_id: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    body = payload if payload is not None else {}
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    account_id = body.get("accountId")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ApiError(400, "invalid_probability_edit", "accountId is required", {"field": "accountId"})

    idempotency_key = body.get("idempotencyKey")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApiError(
                400,
                "invalid_probability_edit",
                "idempotencyKey must be a non-empty string when provided",
                {"field": "idempotencyKey"},
            )
        idempotency_key = idempotency_key.strip()

    normalized_payload = normalize_probability_edit_payload(market_id, body)
    account_id = account_id.strip()
    scope_key = idempotency_scope_key(market_id, account_id, idempotency_key) if idempotency_key is not None else None
    if scope_key is not None:
        existing_command_id = IDEMPOTENCY_KEYS.get(scope_key)
        if existing_command_id is not None:
            existing_command = COMMANDS[existing_command_id]
            if existing_command["payload"] != normalized_payload:
                return build_idempotency_conflict_response(
                    existing_command_id,
                    idempotency_key,
                    market_id,
                    account_id,
                    "ProbabilityEdit",
                )
            return replay_terminal_outcome(existing_command_id)

    submitted_at = utc_timestamp()
    command = materialize_probability_edit_command(
        market_id=market_id,
        normalized_payload=normalized_payload,
        account_id=account_id,
        command_id=generate_command_id(),
        submitted_at=submitted_at,
        idempotency_key=idempotency_key,
    )
    market = MARKETS[market_id]
    if market["status"] != "active":
        return build_terminal_rejection_response(
            command,
            code="market_not_active",
            message="ProbabilityEdit is only allowed for active markets",
            details={
                "marketId": market_id,
                "status": market["status"],
                "allowedStatus": "active",
                "commandId": command["commandId"],
            },
            retry_hint="submit against an active market",
            status=409,
            scope_key=scope_key,
        )
    preview: dict[str, Any] | None = None
    if not normalized_payload["context"]:
        preview = preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
        asset_preview = preview["assetDelta"]
        if asset_preview["afterMinAsset"] < 0:
            return build_terminal_rejection_response(
                command,
                code="min_asset_violation",
                message="Edit would produce negative state-contingent assets",
                details={
                    "accountId": account_id,
                    "marketId": market_id,
                    "commandId": command["commandId"],
                    "riskLimit": asset_preview["riskLimit"],
                    "beforeMinAsset": asset_preview["beforeMinAsset"],
                    "impactScore": asset_preview["impactScore"],
                    "afterMinAsset": asset_preview["afterMinAsset"],
                },
                retry_hint="reduce probability target",
                status=409,
                scope_key=scope_key,
            )

    order = create_probability_edit_order(command, preview=preview)
    asset_delta = sync_account_risk_state(order)
    return build_terminal_acceptance_response(command, order, asset_delta, scope_key)


def handle_event_trade(market_id: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    body = payload if payload is not None else {}
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    account_id = body.get("accountId")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ApiError(400, "invalid_event_trade", "accountId is required", {"field": "accountId"})

    idempotency_key = body.get("idempotencyKey")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApiError(
                400,
                "invalid_event_trade",
                "idempotencyKey must be a non-empty string when provided",
                {"field": "idempotencyKey"},
            )
        idempotency_key = idempotency_key.strip()

    normalized_payload = normalize_event_trade_payload(market_id, body)
    account_id = account_id.strip()
    scope_key = idempotency_scope_key(market_id, account_id, idempotency_key) if idempotency_key is not None else None
    if scope_key is not None:
        existing_command_id = IDEMPOTENCY_KEYS.get(scope_key)
        if existing_command_id is not None:
            existing_command = COMMANDS[existing_command_id]
            if existing_command["payload"] != normalized_payload:
                return build_idempotency_conflict_response(
                    existing_command_id,
                    idempotency_key,
                    market_id,
                    account_id,
                    "EventTrade",
                )
            return replay_terminal_outcome(existing_command_id)

    submitted_at = utc_timestamp()
    command = materialize_event_trade_command(
        market_id=market_id,
        normalized_payload=normalized_payload,
        account_id=account_id,
        command_id=generate_command_id(),
        submitted_at=submitted_at,
        idempotency_key=idempotency_key,
    )
    market = MARKETS[market_id]
    if market["status"] != "active":
        return build_terminal_rejection_response(
            command,
            code="market_not_active",
            message="EventTrade is only allowed for active markets",
            details={
                "marketId": market_id,
                "status": market["status"],
                "allowedStatus": "active",
                "commandId": command["commandId"],
            },
            retry_hint="submit against an active market",
            status=409,
            scope_key=scope_key,
        )

    order = create_event_trade_order(command)
    return build_event_trade_acceptance_response(command, order, scope_key)


def route_request(method: str, raw_path: str, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    parsed = urlparse(raw_path)
    path = normalize_path(parsed.path)

    if method == "GET" and path == "/":
        return service_index_payload(), 200

    if method == "GET" and path in {"/health", "/healthz"}:
        return health_payload(), 200

    if path == "/v1/markets":
        if method != "GET":
            raise ApiError(
                405,
                "method_not_allowed",
                f"{method} is not allowed for this resource",
                {"method": method, "path": path},
            )
        return list_markets(parse_qs(parsed.query, keep_blank_values=True))

    parts = [part for part in path.split("/") if part]
    if len(parts) == 4 and parts[:2] == ["v1", "accounts"] and parts[3] == "risk":
        account_id = parts[2]
        if method != "GET":
            raise ApiError(
                405,
                "method_not_allowed",
                f"{method} is not allowed for this resource",
                {"method": method, "path": path},
            )
        return get_account_risk(account_id)

    if len(parts) >= 3 and parts[:2] == ["v1", "markets"]:
        market_id = parts[2]
        if len(parts) == 3:
            if method != "GET":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            return get_market_detail(market_id)

        if len(parts) == 4 and parts[3] == "engine-stats":
            if method != "GET":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            return get_market_engine_stats(market_id)

        if len(parts) == 4 and parts[3] == "events":
            if method != "GET":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            return get_market_events(market_id, parse_qs(parsed.query, keep_blank_values=True))

        if len(parts) == 5 and parts[3:] == ["orders", "probability-edit"]:
            if method != "POST":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            started_at = time.perf_counter()
            try:
                payload, status = handle_probability_edit(market_id, body)
            except ApiError:
                if market_id in MARKETS:
                    record_market_engine_request(
                        market_id,
                        (time.perf_counter() - started_at) * 1000.0,
                        error=True,
                    )
                raise

            if market_id in MARKETS:
                duration_ms = (time.perf_counter() - started_at) * 1000.0
                record_market_engine_request(market_id, duration_ms, error=status >= 400)
                if status == 201:
                    refresh_market_compile_snapshot(market_id, compile_time_ms=duration_ms)
            return payload, status

        if len(parts) == 5 and parts[3:] == ["orders", "event-trade"]:
            if method != "POST":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            started_at = time.perf_counter()
            try:
                payload, status = handle_event_trade(market_id, body)
            except ApiError:
                if market_id in MARKETS:
                    record_market_engine_request(
                        market_id,
                        (time.perf_counter() - started_at) * 1000.0,
                        error=True,
                    )
                raise

            if market_id in MARKETS:
                duration_ms = (time.perf_counter() - started_at) * 1000.0
                record_market_engine_request(market_id, duration_ms, error=status >= 400)
            return payload, status

    raise ApiError(404, "not_found", "Not found", {"path": path})


class BayesHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def send_json(
        self,
        data: dict[str, Any],
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _enforce_write_controls(self, method: str) -> str:
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return ""

        agent_id = request_agent_id(self.headers)
        enforce_agent_id(agent_id)
        enforce_rate_limit(agent_id)
        return agent_id

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "invalid_content_length", "Invalid Content-Length") from exc

        if content_length <= 0:
            return None

        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "invalid_json", "Invalid JSON") from exc

        if not isinstance(body, dict):
            raise ApiError(400, "invalid_body", "payload must be an object")
        return body

    def handle_api(self, method: str) -> None:
        extra_headers: dict[str, str] | None = None
        try:
            body = self._read_json_body() if method in {"POST", "PUT", "PATCH"} else None
            agent_id = self._enforce_write_controls(method)
            payload, status = route_request(method, self.path, body)
            if status < 400:
                extra_headers = rate_limit_headers(agent_id)
        except ApiError as exc:
            payload, status = error_payload(exc.code, exc.message, **exc.details), exc.status
            if exc.code == "rate_limit_exceeded":
                retry_after = str(exc.details.get("retryAfterSeconds", 1))
                extra_headers = {"Retry-After": retry_after}
                extra_headers.update(rate_limit_headers(str(exc.details.get("agentId", ""))))
        self.send_json(payload, status, extra_headers=extra_headers)

    def do_GET(self) -> None:  # noqa: N802
        self.handle_api("GET")

    def do_POST(self) -> None:  # noqa: N802
        self.handle_api("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self.handle_api("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self.handle_api("DELETE")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bayes Market backend server")
    parser.add_argument("--host", default=os.environ.get("BAYES_MARKET_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BAYES_MARKET_PORT", "3205")))
    return parser.parse_args()


def run_server(host: str = "127.0.0.1", port: int = 3205) -> None:
    HTTPServer((host, port), BayesHandler).serve_forever()


def main() -> int:
    args = parse_args()
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
