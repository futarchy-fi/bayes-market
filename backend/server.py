#!/usr/bin/env python3
"""Minimal Bayes Market backend restoring the documented HTTP surface."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import sys
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import parse_qs, quote, urlparse

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = str(BACKEND_DIR.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.inference import (
    CURRENT_MODEL_COMPILER,
    CURRENT_MODEL_QUERY_BACKEND,
    CompileResult,
    DEFAULT_ENGINE_CONFIG,
    EngineConfig,
    InferenceCompileError,
    InferenceQueryError,
    InferenceUnsupportedQueryError,
)

FORMULA_SCHEMA_MODULE_PATH = Path(__file__).with_name("formula_schema.py")
_FORMULA_SCHEMA_SPEC = importlib.util.spec_from_file_location(
    "bayes_market_formula_schema",
    FORMULA_SCHEMA_MODULE_PATH,
)
if _FORMULA_SCHEMA_SPEC is None or _FORMULA_SCHEMA_SPEC.loader is None:
    raise RuntimeError(f"Unable to load formula schema module from {FORMULA_SCHEMA_MODULE_PATH}")
formula_schema = importlib.util.module_from_spec(_FORMULA_SCHEMA_SPEC)
_FORMULA_SCHEMA_SPEC.loader.exec_module(formula_schema)

LMSR_MODULE_PATH = Path(__file__).with_name("lmsr.py")
_LMSR_SPEC = importlib.util.spec_from_file_location(
    "bayes_market_lmsr",
    LMSR_MODULE_PATH,
)
if _LMSR_SPEC is None or _LMSR_SPEC.loader is None:
    raise RuntimeError(f"Unable to load LMSR module from {LMSR_MODULE_PATH}")
lmsr = importlib.util.module_from_spec(_LMSR_SPEC)
_LMSR_SPEC.loader.exec_module(lmsr)

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
        "resolutionProbabilities": {"yes": 0.0, "no": 1.0},
        "outcomes": [
            {"id": "yes", "name": "Yes"},
            {"id": "no", "name": "No"},
        ],
        "marginals": {"yes": 0.0, "no": 1.0},
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
max_position_size = 100.0
ACCOUNT_LMSR_LEDGER_VERSION = "lmsr-ledger-v1"
ACCOUNT_LMSR_RISK_READ_MODEL = "scalar-min-asset-v1"
MAX_EVENT_FORMULA_CLAUSES = 16
MAX_EVENT_FORMULA_CLAUSE_LITERALS = 8
ALLOWED_EVENT_TRADE_SIDES = frozenset({"buy", "sell"})
AGENT_ID_HEADER = "X-Bayes-Agent-Id"
AUTH_REQUIRE_AGENT_ID_ENV = "BAYES_REQUIRE_AGENT_ID"
RATE_LIMIT_PER_MIN_ENV = "BAYES_RATE_LIMIT_PER_MIN"
RATE_LIMIT_POLICY_VERSION = "bayes-agent-id-v1"
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_COMMENT_BODY_LENGTH = 2000
AGENT_ID_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
MARKET_ADMIN_WRITE_CATEGORY = "market_admin"
TRADE_WRITE_CATEGORY = "trade_write"
ENGINE_CONFIG: EngineConfig = DEFAULT_ENGINE_CONFIG
ENGINE_MODE = ENGINE_CONFIG.mode
ENGINE_BACKEND = ENGINE_CONFIG.backend
ENGINE_VERSION = ENGINE_CONFIG.version
ENGINE_PRECISION = ENGINE_CONFIG.precision
ENGINE_COMPILE_TYPE = ENGINE_CONFIG.compile_type
ENGINE_INFERENCE_SAMPLE_LIMIT = ENGINE_CONFIG.inference_sample_limit
PUBLIC_ORIGIN_ENV = "BAYES_PUBLIC_ORIGIN"
DEFAULT_PUBLIC_ORIGIN = "http://localhost"
SITE_NAME = "Bayes Market"
SITE_DESCRIPTION = "Create, trade, and resolve Bayesian prediction markets."
OPEN_GRAPH_TYPE = "website"
FRONTEND_MARKET_DETAIL_RE = re.compile(r"^/markets/(?P<market_id>[^/]+)$")
TITLE_TAG_RE = re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)
DESCRIPTION_META_TAG_RE = re.compile(r"<meta\b[^>]*\bname=[\"']description[\"'][^>]*>", re.IGNORECASE)
OG_TITLE_META_TAG_RE = re.compile(r"<meta\b[^>]*\bproperty=[\"']og:title[\"'][^>]*>", re.IGNORECASE)
OG_DESCRIPTION_META_TAG_RE = re.compile(r"<meta\b[^>]*\bproperty=[\"']og:description[\"'][^>]*>", re.IGNORECASE)
OG_TYPE_META_TAG_RE = re.compile(r"<meta\b[^>]*\bproperty=[\"']og:type[\"'][^>]*>", re.IGNORECASE)
OG_URL_META_TAG_RE = re.compile(r"<meta\b[^>]*\bproperty=[\"']og:url[\"'][^>]*>", re.IGNORECASE)

MARKETS: dict[str, dict[str, Any]] = deepcopy(INITIAL_MARKETS)
CONDITIONAL_MARGINALS: dict[str, dict[str, dict[str, float]]] = {}
ORDERS: dict[str, dict[str, Any]] = {}
COMMANDS: dict[str, dict[str, Any]] = {}
EVENTS: dict[str, dict[str, Any]] = {}
COMMENTS: dict[str, dict[str, Any]] = {}
TERMINAL_OUTCOMES: dict[str, dict[str, Any]] = {}
COMMENT_POST_OUTCOMES: dict[str, dict[str, Any]] = {}
IDEMPOTENCY_KEYS: dict[tuple[str, str, str], str] = {}
MARKET_EVENT_SEQUENCES: dict[str, int] = {}
MARKET_COMMENT_SEQUENCES: dict[str, int] = {}
LAST_EVENT_HASHES: dict[str, str] = {}
MARKET_WRITE_LOCKS: dict[str, threading.Lock] = {}
_LOCK_REGISTRY_LOCK = threading.Lock()
_EVENTS_LOCK = threading.RLock()
_COMMENTS_LOCK = threading.RLock()
ACCOUNT_RISK: dict[str, dict[str, Any]] = {}
ACCOUNT_EXPOSURE: dict[str, dict[str, Any]] = {}
MARKET_ENGINE_STATS: dict[str, dict[str, Any]] = {}
_RATE_LIMIT_WINDOWS: dict[str, deque[float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()
ORDER_COUNTER = 0
COMMAND_COUNTER = 0
EVENT_COUNTER = 0
COMMENT_COUNTER = 0
GENESIS_EVENT_HASH = f"sha256:{hashlib.sha256(b'').hexdigest()}"
WRITE_ROUTE_POLICIES: dict[str, dict[str, bool]] = {
    MARKET_ADMIN_WRITE_CATEGORY: {"requires_agent_id": True},
    TRADE_WRITE_CATEGORY: {"requires_agent_id": True},
}


class WriteRequestAgentContext(NamedTuple):
    """Describe one protected write request and its normalized agent identity."""

    category: str
    policy: dict[str, bool]
    agent_id: str


def get_market_write_lock(market_id: str) -> threading.Lock:
    """Serialize same-market command lifecycles so state and journal heads stay coherent."""
    with _LOCK_REGISTRY_LOCK:
        lock = MARKET_WRITE_LOCKS.get(market_id)
        if lock is None:
            lock = threading.RLock()
            MARKET_WRITE_LOCKS[market_id] = lock
        return lock


def utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO-8601 Zulu form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ApiError(Exception):
    """Represent an API error with an HTTP status and structured payload."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize an API error for downstream HTTP serialization."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def reset_state() -> None:
    """Reset all in-memory application state back to the initial fixtures."""
    global ORDER_COUNTER, COMMAND_COUNTER, EVENT_COUNTER, COMMENT_COUNTER
    MARKETS.clear()
    MARKETS.update(deepcopy(INITIAL_MARKETS))
    CONDITIONAL_MARGINALS.clear()
    ORDERS.clear()
    COMMANDS.clear()
    with _EVENTS_LOCK:
        EVENTS.clear()
    with _COMMENTS_LOCK:
        COMMENTS.clear()
    TERMINAL_OUTCOMES.clear()
    COMMENT_POST_OUTCOMES.clear()
    IDEMPOTENCY_KEYS.clear()
    MARKET_EVENT_SEQUENCES.clear()
    MARKET_COMMENT_SEQUENCES.clear()
    LAST_EVENT_HASHES.clear()
    MARKET_WRITE_LOCKS.clear()
    ACCOUNT_RISK.clear()
    ACCOUNT_EXPOSURE.clear()
    MARKET_ENGINE_STATS.clear()
    reset_rate_limit_state()
    ORDER_COUNTER = 0
    COMMAND_COUNTER = 0
    EVENT_COUNTER = 0
    COMMENT_COUNTER = 0


def generate_order_id() -> str:
    """Return a unique order identifier for the current process run."""
    global ORDER_COUNTER
    ORDER_COUNTER += 1
    return f"ord_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{ORDER_COUNTER:06d}"


def generate_command_id() -> str:
    """Return a unique command identifier for the current process run."""
    global COMMAND_COUNTER
    COMMAND_COUNTER += 1
    return f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{COMMAND_COUNTER:06d}"


def generate_event_id() -> str:
    """Return a unique event identifier for the current process run."""
    global EVENT_COUNTER
    EVENT_COUNTER += 1
    return f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{EVENT_COUNTER:06d}"


def generate_comment_id() -> str:
    """Return a unique comment identifier for the current process run."""
    global COMMENT_COUNTER
    COMMENT_COUNTER += 1
    return f"cmt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{COMMENT_COUNTER:06d}"


def canonical_json_hash(data: object) -> str:
    """Hash JSON-serializable data using the backend's canonical encoding."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def normalize_path(path: str) -> str:
    """Normalize request paths by trimming a trailing slash when safe."""
    if path != "/" and path.endswith("/"):
        return path[:-1]
    return path


def read_bool_env(name: str, default: bool) -> bool:
    """Read a boolean environment variable with a permissive parser."""
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
    """Read a non-negative integer environment variable or fall back."""
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
    """Clear all in-memory agent rate-limit buckets."""
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_WINDOWS.clear()


def request_agent_id_values(headers: Any) -> list[str]:
    """Extract all raw Bayes agent id header values without normalization."""
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all(AGENT_ID_HEADER, [])
        if values:
            return [str(value) for value in values if value is not None]

    value = headers.get(AGENT_ID_HEADER)
    if value is None:
        return []
    return [str(value)]


def request_agent_id(headers: Any) -> str:
    """Extract and normalize one Bayes agent id header value when available."""
    values = request_agent_id_values(headers)
    if len(values) != 1:
        return ""
    return values[0].strip()


def enforce_agent_id(agent_id: str, *, category: str | None = None) -> None:
    """Raise when write controls require an agent id and none is present."""
    if AUTH_REQUIRE_AGENT_ID and not agent_id:
        details: dict[str, Any] = {"header": AGENT_ID_HEADER}
        if category is not None:
            details["category"] = category
        raise ApiError(
            401,
            "missing_agent_id",
            "Missing Bayes agent id header",
            details,
        )


def write_policy_requires_agent_id(policy: dict[str, bool]) -> bool:
    """Return whether the matched write policy currently requires an agent id."""
    return AUTH_REQUIRE_AGENT_ID and bool(policy.get("requires_agent_id"))


def resolve_write_route_category(method: str, raw_path: str) -> str | None:
    """Resolve the frozen T582 write-route category for a request, if any."""
    if method != "POST":
        return None

    parsed = urlparse(raw_path)
    path = normalize_path(parsed.path)
    if path == "/v1/markets":
        return MARKET_ADMIN_WRITE_CATEGORY

    parts = [part for part in path.split("/") if part]
    if len(parts) < 4 or parts[:2] != ["v1", "markets"]:
        return None

    if len(parts) == 4 and parts[3] == "resolve":
        return MARKET_ADMIN_WRITE_CATEGORY
    if len(parts) == 4 and parts[3] == "comments":
        return TRADE_WRITE_CATEGORY
    if len(parts) == 5 and parts[3:] in (["orders", "probability-edit"], ["orders", "event-trade"]):
        return TRADE_WRITE_CATEGORY
    return None


def _raise_invalid_agent_id(category: str, *, reason: str | None = None) -> None:
    """Raise the stable invalid-agent-id error shape for protected write routes."""
    details: dict[str, Any] = {
        "header": AGENT_ID_HEADER,
        "category": category,
    }
    if reason is not None:
        details["reason"] = reason
    raise ApiError(401, "invalid_agent_id", "Invalid Bayes agent id header", details)


def resolve_write_request_agent(method: str, raw_path: str, headers: Any) -> WriteRequestAgentContext | None:
    """Resolve and validate the agent identity for the frozen protected write surface."""
    category = resolve_write_route_category(method, raw_path)
    if category is None:
        return None

    policy = WRITE_ROUTE_POLICIES[category]
    require_agent_id = write_policy_requires_agent_id(policy)
    raw_values = request_agent_id_values(headers)
    if not raw_values:
        enforce_agent_id("", category=category)
        return WriteRequestAgentContext(category=category, policy=policy, agent_id="")

    if len(raw_values) > 1:
        if require_agent_id:
            _raise_invalid_agent_id(category, reason="multiple_values")
        return WriteRequestAgentContext(category=category, policy=policy, agent_id="")

    raw_agent_id = raw_values[0]
    agent_id = raw_agent_id.strip()
    if not agent_id:
        if require_agent_id:
            raise ApiError(
                401,
                "blank_agent_id",
                "Blank Bayes agent id header",
                {"header": AGENT_ID_HEADER, "category": category},
            )
        return WriteRequestAgentContext(category=category, policy=policy, agent_id="")

    if "," in raw_agent_id or not AGENT_ID_TOKEN_RE.fullmatch(agent_id):
        if require_agent_id:
            reason = "multiple_values" if "," in raw_agent_id else "invalid_format"
            _raise_invalid_agent_id(category, reason=reason)
        return WriteRequestAgentContext(category=category, policy=policy, agent_id="")

    return WriteRequestAgentContext(category=category, policy=policy, agent_id=agent_id)


def enforce_rate_limit(agent_id: str) -> None:
    """Apply the configured per-agent sliding-window rate limit."""
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
    """Build response headers describing the current agent rate-limit state."""
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
    """Build a response metadata object with a timestamp and extras."""
    meta: dict[str, Any] = {"timestamp": utc_timestamp()}
    meta.update(extra)
    return meta


def normalize_public_origin(origin: str) -> str:
    """Normalize a configured public origin down to scheme + authority."""
    raw_origin = origin.strip()
    if not raw_origin:
        return ""

    parsed = urlparse(raw_origin)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{scheme}://{parsed.netloc}"


def header_first_value(headers: Any | None, name: str) -> str:
    """Return the first comma-delimited header value when present."""
    if headers is None:
        return ""

    value = headers.get(name)
    if value is None:
        return ""
    return str(value).split(",")[0].strip()


def normalize_origin_host(host: str) -> str:
    """Sanitize a host header value before using it in an absolute URL."""
    candidate = host.strip()
    if not candidate:
        return ""
    if any(character.isspace() for character in candidate):
        return ""
    if any(character in candidate for character in "/?#"):
        return ""
    return candidate


def configured_public_origin() -> str:
    """Return the configured canonical public origin when available."""
    return normalize_public_origin(os.environ.get(PUBLIC_ORIGIN_ENV, ""))


def request_public_origin(headers: Any | None) -> str:
    """Derive a public origin from forwarded headers or the request host."""
    forwarded_host = header_first_value(headers, "X-Forwarded-Host")
    host = normalize_origin_host(forwarded_host or header_first_value(headers, "Host"))
    if not host:
        return ""

    forwarded_proto = header_first_value(headers, "X-Forwarded-Proto").lower()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else "http"
    return f"{scheme}://{host}"


def resolve_public_origin(headers: Any | None = None) -> str:
    """Resolve the canonical public origin for absolute preview URLs."""
    return configured_public_origin() or request_public_origin(headers) or DEFAULT_PUBLIC_ORIGIN


def absolute_public_url(path: str, *, headers: Any | None = None) -> str:
    """Build an absolute public URL for one application path."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{resolve_public_origin(headers)}{normalized_path}"


def build_market_preview(market: dict[str, Any], *, headers: Any | None = None) -> dict[str, str]:
    """Build the normalized share-preview payload for one market."""
    market_id = str(market["id"])
    return {
        "marketId": market_id,
        "title": str(market["title"]),
        "description": str(market["description"]),
        "url": absolute_public_url(f"/markets/{quote(market_id, safe='')}", headers=headers),
        "siteName": SITE_NAME,
        "type": OPEN_GRAPH_TYPE,
    }


def normalize_frontend_page_path(url_path: str) -> str:
    """Normalize a frontend route path for preview URL generation."""
    clean = normalize_path(url_path.split("?")[0].split("#")[0] or "/")
    if clean == "/index.html":
        return "/"
    return clean


def frontend_market_id(url_path: str) -> str | None:
    """Return the market id encoded in a frontend market-detail route."""
    match = FRONTEND_MARKET_DETAIL_RE.match(normalize_frontend_page_path(url_path))
    if match is None:
        return None

    market_id = match.group("market_id")
    if market_id == "new":
        return None
    return market_id


def build_default_preview(url_path: str, *, headers: Any | None = None) -> dict[str, str]:
    """Build the generic SPA preview payload for non-market pages."""
    normalized_path = normalize_frontend_page_path(url_path)
    return {
        "title": SITE_NAME,
        "description": SITE_DESCRIPTION,
        "url": absolute_public_url(normalized_path, headers=headers),
        "siteName": SITE_NAME,
        "type": OPEN_GRAPH_TYPE,
    }


def preview_for_frontend_path(url_path: str, *, headers: Any | None = None) -> dict[str, str]:
    """Choose market-specific or generic preview metadata for one SPA route."""
    market_id = frontend_market_id(url_path)
    if market_id is not None:
        market = MARKETS.get(market_id)
        if market is not None:
            return build_market_preview(market, headers=headers)
    return build_default_preview(url_path, headers=headers)


def replace_or_insert_head_tag(document: str, pattern: re.Pattern[str], replacement: str) -> str:
    """Replace one existing head tag or insert it before the closing head tag."""
    if pattern.search(document):
        return pattern.sub(replacement, document, count=1)

    if "</head>" in document:
        return document.replace("</head>", f"    {replacement}\n  </head>", 1)
    return f"{document}\n{replacement}"


def render_frontend_index_html(document: str, url_path: str, *, headers: Any | None = None) -> bytes:
    """Inject crawler-visible title and Open Graph tags into the SPA shell."""
    preview = preview_for_frontend_path(url_path, headers=headers)
    escaped_title = html.escape(preview["title"], quote=False)
    escaped_description = html.escape(preview["description"], quote=True)
    escaped_url = html.escape(preview["url"], quote=True)
    escaped_type = html.escape(preview["type"], quote=True)

    rendered = replace_or_insert_head_tag(document, TITLE_TAG_RE, f"<title>{escaped_title}</title>")
    rendered = replace_or_insert_head_tag(
        rendered,
        DESCRIPTION_META_TAG_RE,
        f'<meta name="description" content="{escaped_description}" />',
    )
    rendered = replace_or_insert_head_tag(
        rendered,
        OG_TITLE_META_TAG_RE,
        f'<meta property="og:title" content="{escaped_title}" />',
    )
    rendered = replace_or_insert_head_tag(
        rendered,
        OG_DESCRIPTION_META_TAG_RE,
        f'<meta property="og:description" content="{escaped_description}" />',
    )
    rendered = replace_or_insert_head_tag(
        rendered,
        OG_TYPE_META_TAG_RE,
        f'<meta property="og:type" content="{escaped_type}" />',
    )
    rendered = replace_or_insert_head_tag(
        rendered,
        OG_URL_META_TAG_RE,
        f'<meta property="og:url" content="{escaped_url}" />',
    )
    return rendered.encode("utf-8")


def error_payload(code: str, message: str, **details: object) -> dict[str, Any]:
    """Build the standard JSON error envelope used by the API."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": make_meta(),
    }


def health_payload() -> dict[str, Any]:
    """Build the service health response payload."""
    return {
        "service": "bayes-market",
        "status": "ok",
        "timestamp": utc_timestamp(),
    }


def service_index_payload() -> dict[str, Any]:
    """Build the root index payload describing the public HTTP surface."""
    return {
        "service": "bayes-market",
        "status": "ok",
        "routes": {
            "health": ["/health", "/healthz"],
            "markets": [
                "GET /v1/markets",
                "POST /v1/markets",
                "/v1/markets/{id}",
                "/v1/markets/{id}/meta",
                "/v1/markets/{id}/events",
                "GET /v1/markets/{id}/comments",
                "POST /v1/markets/{id}/comments",
                "/v1/markets/{id}/engine-stats",
                "POST /v1/markets/{id}/resolve",
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
    """Project a market record down to the list response fields."""
    return {field: market[field] for field in MARKET_SUMMARY_FIELDS}


def percentile_ms(values: list[float], ratio: float) -> float:
    """Return a rounded percentile value from a list of millisecond samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return round(ordered[index], 3)


def inference_stats_payload(samples_ms: list[float]) -> dict[str, Any]:
    """Summarize inference timing samples for diagnostics output."""
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
    """Return the engine diagnostics bucket for a market, creating it if needed."""
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


def raise_inference_adapter_error(market_id: str, operation: str, exc: Exception) -> None:
    """Wrap inference adapter failures in the API's internal-error response."""
    raise ApiError(
        500,
        "internal_error",
        "Internal server error",
        {"marketId": market_id, "operation": operation},
    ) from exc


def compile_market_for_inference(
    market_id: str,
    *,
    compile_time_ms: float = 0.0,
    last_updated: str | None = None,
) -> CompileResult:
    """Compile a market snapshot for inference queries."""
    market = MARKETS.get(market_id)
    if market is None:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    try:
        return CURRENT_MODEL_COMPILER.compile_result(
            market_snapshot=deepcopy(market),
            conditional_marginals=deepcopy(CONDITIONAL_MARGINALS.get(market_id, {})),
            compile_time_ms=round(float(compile_time_ms), 3),
            last_updated=last_updated or utc_timestamp(),
        )
    except InferenceCompileError as exc:
        raise_inference_adapter_error(market_id, "compile_market", exc)


def context_mapping_from_assignments(context: list[dict[str, str]]) -> dict[str, str]:
    """Convert normalized context assignments into an inference lookup map."""
    return {
        str(assignment["variableId"]): str(assignment["outcomeId"])
        for assignment in context
    }


def query_market_marginals_for_inference(
    market_id: str,
    context: list[dict[str, str]],
) -> dict[str, float]:
    """Query inferred market marginals under an optional context."""
    compile_result = compile_market_for_inference(market_id)
    context_mapping = context_mapping_from_assignments(context) if context else None

    try:
        query_result = CURRENT_MODEL_QUERY_BACKEND.query_marginals(
            compile_result,
            context=context_mapping,
        )
    except (InferenceQueryError, InferenceUnsupportedQueryError) as exc:
        raise_inference_adapter_error(market_id, "query_marginals", exc)

    return deepcopy(dict(query_result.marginals))


def query_market_atomic_probability_for_inference(market_id: str, outcome_id: str) -> float:
    """Query the inferred probability of a single market outcome."""
    market = MARKETS.get(market_id)
    if market is None:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    compile_result = compile_market_for_inference(market_id)
    try:
        query_result = CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(
            compile_result,
            variable_id=str(market["variableId"]),
            outcome_id=outcome_id,
        )
    except (InferenceQueryError, InferenceUnsupportedQueryError) as exc:
        raise_inference_adapter_error(market_id, "query_atomic_event", exc)

    return float(query_result.probability)


def parse_context_key_variable_ids(context_key: str) -> list[str]:
    """Extract variable ids from a serialized context-state key."""
    if not context_key:
        return []

    variable_ids: list[str] = []
    for assignment in context_key.split("|"):
        variable_id, separator, _outcome_id = assignment.partition("=")
        if separator and variable_id:
            variable_ids.append(variable_id)
    return variable_ids


def clique_state_count(variable_ids: tuple[str, ...]) -> int:
    """Estimate the discrete state count for a clique of market variables."""
    state_count = 1
    for variable_id in variable_ids:
        market = find_market_by_variable_id(variable_id)
        outcome_count = len(market["outcomes"]) if market else 0
        state_count *= max(outcome_count, 1)
    return state_count


def build_market_cliques(market_id: str) -> list[dict[str, Any]]:
    """Build clique summaries implied by a market and its conditional contexts."""
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


def estimate_market_engine_memory_bytes(cliques: list[dict[str, Any]] | tuple[CliqueSummary, ...]) -> int:
    """Estimate memory use for a compiled market from its clique summaries."""
    total = 0
    for clique in cliques:
        if isinstance(clique, CliqueSummary):
            states = int(clique.states)
            size = int(clique.size)
        else:
            states = int(clique["states"])
            size = int(clique["size"])
        total += states * 32 + size * 64
    return total


def build_market_compile_result(market_id: str, *, compile_time_ms: float | None = None) -> CompileResult:
    """Compile a market and normalize the optional compile-time measurement."""
    return compile_market_for_inference(
        market_id,
        compile_time_ms=float(compile_time_ms or 0.0),
    )


def refresh_market_compile_snapshot(market_id: str, *, compile_time_ms: float | None = None) -> None:
    """Refresh cached compile diagnostics for a market."""
    state = ensure_market_engine_state(market_id)
    compile_result = build_market_compile_result(market_id, compile_time_ms=compile_time_ms)
    state["compile_id"] = compile_result.compile_id
    state["compile_type"] = compile_result.compile_type
    state["source_state_hash"] = compile_result.source_state_hash
    state["compile_time_ms"] = round(float(compile_result.compile_time_ms), 3)
    state["memory_bytes"] = int(compile_result.memory_bytes)
    state["last_updated"] = compile_result.last_updated
    state["cliques"] = [clique.to_dict() for clique in compile_result.cliques]


def record_market_engine_request(market_id: str, duration_ms: float, *, error: bool) -> None:
    """Record one engine-facing request in the market diagnostics state."""
    state = ensure_market_engine_state(market_id)
    state["request_count"] += 1
    if error:
        state["error_count"] += 1

    samples = state["inference_samples_ms"]
    samples.append(round(float(duration_ms), 3))
    limit = ENGINE_CONFIG.inference_sample_limit
    if limit == 0:
        samples.clear()
    elif len(samples) > limit:
        del samples[:-limit]


def get_market_engine_stats(market_id: str) -> tuple[dict[str, Any], int]:
    """Return the engine diagnostics payload for a market."""
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
            "mode": ENGINE_CONFIG.mode,
            "backend": ENGINE_CONFIG.backend,
            "version": ENGINE_CONFIG.version,
            "precision": ENGINE_CONFIG.precision,
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
    """Round risk-model values to the backend's canonical precision."""
    return round(float(value), 6)


def account_capacity_status(limit: float, min_asset: float) -> str:
    """Classify capacity health from a risk limit and current minimum asset."""
    if min_asset <= 0:
        return "breached"
    utilization = 0.0 if limit <= 0 else (limit - min_asset) / limit
    if utilization >= 0.8:
        return "critical"
    if utilization >= 0.5:
        return "constrained"
    return "healthy"


def build_capacity_indicators(limit: float, min_asset: float) -> dict[str, Any]:
    """Build capacity summary metrics for an account or market slice."""
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


def build_account_lmsr_state(
    slices: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the default LMSR ledger state for an account."""
    return {
        "version": ACCOUNT_LMSR_LEDGER_VERSION,
        "riskReadModel": ACCOUNT_LMSR_RISK_READ_MODEL,
        "slices": deepcopy(slices) if slices is not None else {},
    }


def build_account_risk_state(
    account_id: str,
    timestamp: str,
    *,
    risk_limit: float = ACCOUNT_RISK_LIMIT,
    min_asset: float | None = None,
    markets: dict[str, dict[str, Any]] | None = None,
    lmsr_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the default account risk document."""
    normalized_risk_limit = round_risk_value(risk_limit)
    normalized_min_asset = normalized_risk_limit if min_asset is None else round_risk_value(min_asset)
    return {
        "accountId": account_id,
        "riskLimit": normalized_risk_limit,
        "minAsset": normalized_min_asset,
        "updatedAt": timestamp,
        "markets": deepcopy(markets) if markets is not None else {},
        "lmsrState": deepcopy(lmsr_state) if lmsr_state is not None else build_account_lmsr_state(),
    }


def ensure_account_lmsr_state(account: dict[str, Any]) -> dict[str, Any]:
    """Ensure an account carries a normalized LMSR state block."""
    lmsr_state = account.get("lmsrState")
    if not isinstance(lmsr_state, dict):
        lmsr_state = build_account_lmsr_state()
        account["lmsrState"] = lmsr_state
        return lmsr_state

    if not isinstance(lmsr_state.get("version"), str):
        lmsr_state["version"] = ACCOUNT_LMSR_LEDGER_VERSION
    if not isinstance(lmsr_state.get("riskReadModel"), str):
        lmsr_state["riskReadModel"] = ACCOUNT_LMSR_RISK_READ_MODEL
    if not isinstance(lmsr_state.get("slices"), dict):
        lmsr_state["slices"] = {}
    return lmsr_state


def ensure_account_risk_state(account_id: str, timestamp: str) -> dict[str, Any]:
    """Return an account risk record, creating a default one if absent."""
    account = ACCOUNT_RISK.get(account_id)
    if account is None:
        account = build_account_risk_state(account_id, timestamp)
        ACCOUNT_RISK[account_id] = account
    else:
        ensure_account_lmsr_state(account)
    return account


def round_exposure_value(value: Any, *, default: float = 0.0) -> float:
    """Normalize one exposure scalar to the backend's canonical precision."""
    if value is None:
        return round_risk_value(default)
    return round_risk_value(float(value))


def account_exposure_position_key(market_id: str, outcome_id: str) -> str:
    """Build the flat composite storage key for one exposure position row."""
    return f"{market_id}|{outcome_id}"


def build_account_exposure_position(
    market_id: str,
    outcome_id: str,
    timestamp: str,
    *,
    net_size: float = 0.0,
    last_trade_price: float = 0.0,
    last_order_id: str | None = None,
    last_command_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical mutable state for one live exposure position."""
    return {
        "marketId": str(market_id),
        "outcomeId": str(outcome_id),
        "netSize": round_exposure_value(net_size),
        "lastTradePrice": round_exposure_value(last_trade_price),
        "updatedAt": timestamp,
        "lastOrderId": None if last_order_id is None else str(last_order_id),
        "lastCommandId": None if last_command_id is None else str(last_command_id),
    }


def build_account_exposure_state(
    account_id: str,
    timestamp: str,
    *,
    positions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the default live-exposure projection for one account."""
    return {
        "accountId": str(account_id),
        "updatedAt": timestamp,
        "positions": deepcopy(positions) if positions is not None else {},
    }


def ensure_account_exposure_state(account_id: str, timestamp: str) -> dict[str, Any]:
    """Return an exposure account document, creating or normalizing it as needed."""
    account = ACCOUNT_EXPOSURE.get(account_id)
    if account is None:
        account = build_account_exposure_state(account_id, timestamp)
        ACCOUNT_EXPOSURE[account_id] = account
        return account

    account["accountId"] = str(account_id)
    if not isinstance(account.get("updatedAt"), str):
        account["updatedAt"] = timestamp
    positions = account.get("positions")
    if not isinstance(positions, dict):
        account["positions"] = {}
    return account


def ensure_account_exposure_position(
    account: dict[str, Any],
    market_id: str,
    outcome_id: str,
    timestamp: str,
) -> dict[str, Any]:
    """Return one canonical exposure position row for mutation-oriented callers."""
    positions = account.get("positions")
    if not isinstance(positions, dict):
        positions = {}
        account["positions"] = positions

    composite_key = account_exposure_position_key(market_id, outcome_id)
    position = positions.get(composite_key)
    if not isinstance(position, dict):
        position = build_account_exposure_position(market_id, outcome_id, timestamp)
        positions[composite_key] = position
        return position

    position["marketId"] = str(market_id)
    position["outcomeId"] = str(outcome_id)
    position["netSize"] = round_exposure_value(position.get("netSize"))
    position["lastTradePrice"] = round_exposure_value(position.get("lastTradePrice"))
    if not isinstance(position.get("updatedAt"), str):
        position["updatedAt"] = timestamp
    position["lastOrderId"] = None if position.get("lastOrderId") is None else str(position["lastOrderId"])
    position["lastCommandId"] = None if position.get("lastCommandId") is None else str(position["lastCommandId"])
    return position


def build_event_trade_position_net_change(
    position: dict[str, Any] | None,
    order: dict[str, Any],
) -> dict[str, float]:
    """Compute the signed net-size transition for one accepted EventTrade."""
    current_net_size = 0.0 if position is None else round_exposure_value(position.get("netSize"))
    size = round_exposure_value(order.get("size"))
    side = str(order.get("side"))
    if side == "buy":
        signed_delta = size
    elif side == "sell":
        signed_delta = round_risk_value(-size)
    else:
        raise ValueError(f"Unsupported event-trade side: {side}")

    resulting_net_size = round_risk_value(current_net_size + signed_delta)
    if resulting_net_size == -0.0:
        resulting_net_size = 0.0
    return {
        "currentNetSize": current_net_size,
        "signedDelta": signed_delta,
        "resultingNetSize": resulting_net_size,
    }


def sync_account_exposure_state(order: dict[str, Any]) -> dict[str, Any]:
    """Apply one accepted EventTrade order to the live account-exposure projection."""
    account_id = str(order["accountId"])
    market_id = str(order.get("targetMarketId") or order["marketId"])
    outcome_id = str(order.get("targetOutcomeId") or order["payload"]["formula"][0][0]["outcomeId"])
    timestamp = str(order["filledAt"])

    account = ensure_account_exposure_state(account_id, timestamp)
    position = ensure_account_exposure_position(account, market_id, outcome_id, timestamp)
    net_change = build_event_trade_position_net_change(position, order)
    composite_key = account_exposure_position_key(market_id, outcome_id)
    positions = account["positions"]

    if net_change["resultingNetSize"] == 0.0:
        positions.pop(composite_key, None)
        if positions:
            account["updatedAt"] = timestamp
        else:
            ACCOUNT_EXPOSURE.pop(account_id, None)
    else:
        position["netSize"] = net_change["resultingNetSize"]
        position["lastTradePrice"] = round_exposure_value(order.get("price"))
        position["updatedAt"] = timestamp
        position["lastOrderId"] = str(order["id"])
        position["lastCommandId"] = str(order["commandId"])
        account["updatedAt"] = timestamp

    return {
        "accountId": account_id,
        "marketId": market_id,
        "outcomeId": outcome_id,
        **net_change,
    }


def preview_account_min_asset(account_id: str, impact_score: float) -> dict[str, Any]:
    """Preview the account-wide min-asset effect of a proposed impact score."""
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


def account_lmsr_slice_key(
    market_id: str,
    context: list[dict[str, str]],
) -> str:
    """Build the ledger key for one market/context LMSR slice."""
    return f"{market_id}|{context_state_key(context)}"


def _round_score_by_outcome(score_by_outcome: dict[str, float]) -> dict[str, float]:
    return {
        str(outcome_id): round_risk_value(score)
        for outcome_id, score in score_by_outcome.items()
    }


def _accumulate_score_by_outcome(
    score_by_outcome: dict[str, Any],
    score_delta: dict[str, float],
) -> dict[str, float]:
    accumulated: dict[str, float] = {}
    for outcome_id, score in score_by_outcome.items():
        normalized_outcome_id = str(outcome_id)
        accumulated[normalized_outcome_id] = round_risk_value(float(score))

    for outcome_id, delta in score_delta.items():
        normalized_outcome_id = str(outcome_id)
        accumulated[normalized_outcome_id] = round_risk_value(
            float(accumulated.get(normalized_outcome_id, 0.0)) + float(delta)
        )
    return accumulated


def sync_probability_edit_lmsr_state(account: dict[str, Any], order: dict[str, Any]) -> None:
    """Apply a probability-edit order to the account's LMSR ledger state."""
    market_id = str(order["marketId"])
    market = MARKETS.get(market_id)
    if market is None:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    payload = order["payload"]
    context = deepcopy(payload["context"])
    context_key = context_state_key(context)
    slice_key = account_lmsr_slice_key(market_id, context)
    timestamp = str(order["filledAt"])
    score_delta = _round_score_by_outcome(
        lmsr.lmsr_score_delta(
            order["previousMarginals"],
            order["newMarginals"],
            float(market["liquidity"]),
        )
    )

    lmsr_state = ensure_account_lmsr_state(account)
    slices = lmsr_state["slices"]
    slice_state = slices.get(slice_key)
    if not isinstance(slice_state, dict):
        slice_state = {
            "marketId": market_id,
            "variableId": str(payload["variableId"]),
            "context": context,
            "contextKey": context_key,
            "liquidity": round_risk_value(float(market["liquidity"])),
            "scoreByOutcome": deepcopy(score_delta),
            "commandCount": 1,
            "updatedAt": timestamp,
            "lastOrderId": str(order["id"]),
            "lastCommandId": str(order["commandId"]),
        }
        slices[slice_key] = slice_state
        return

    slice_state["marketId"] = market_id
    slice_state["variableId"] = str(payload["variableId"])
    slice_state["context"] = context
    slice_state["contextKey"] = context_key
    slice_state["liquidity"] = round_risk_value(float(market["liquidity"]))
    existing_scores = slice_state.get("scoreByOutcome", {})
    if not isinstance(existing_scores, dict):
        existing_scores = {}
    slice_state["scoreByOutcome"] = _accumulate_score_by_outcome(existing_scores, score_delta)
    slice_state["commandCount"] = int(slice_state.get("commandCount", 0)) + 1
    slice_state["updatedAt"] = timestamp
    slice_state["lastOrderId"] = str(order["id"])
    slice_state["lastCommandId"] = str(order["commandId"])


def sync_account_risk_state(order: dict[str, Any]) -> dict[str, Any]:
    """Apply an accepted order to the stored account risk state."""
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

    if str(order["type"]) == "ProbabilityEdit":
        sync_probability_edit_lmsr_state(account, order)

    return {
        "accountId": account_id,
        "marketId": market_id,
        "beforeMinAsset": before_min_asset,
        "afterMinAsset": after_min_asset,
    }


def serialize_account_exposure_position(position: dict[str, Any]) -> dict[str, Any] | None:
    """Project one canonical exposure row into the public response shape."""
    net_size = round_exposure_value(position.get("netSize"))
    if net_size == 0.0:
        return None

    return {
        "marketId": str(position["marketId"]),
        "outcomeId": str(position["outcomeId"]),
        "netSize": net_size,
        "absSize": round_risk_value(abs(net_size)),
        "lastTradePrice": round_exposure_value(position.get("lastTradePrice")),
        "updatedAt": str(position["updatedAt"]),
        "lastOrderId": position.get("lastOrderId"),
        "lastCommandId": position.get("lastCommandId"),
    }


def serialize_account_exposure_positions(account: dict[str, Any]) -> list[dict[str, Any]]:
    """Project all live exposure rows in deterministic lexical order."""
    positions = account.get("positions")
    if not isinstance(positions, dict):
        return []

    serialized_positions: list[dict[str, Any]] = []
    for position in positions.values():
        if not isinstance(position, dict):
            continue
        serialized_position = serialize_account_exposure_position(position)
        if serialized_position is not None:
            serialized_positions.append(serialized_position)

    serialized_positions.sort(key=lambda position: (position["marketId"], position["outcomeId"]))
    return serialized_positions


def serialize_account_exposure(account: dict[str, Any]) -> dict[str, Any]:
    """Project one stored exposure account into the public account.exposure shape."""
    return {
        "maxPositionSize": round_risk_value(max_position_size),
        "updatedAt": str(account["updatedAt"]),
        "positions": serialize_account_exposure_positions(account),
    }


def get_account_exposure(account_id: str) -> tuple[dict[str, Any], int]:
    """Return the read model for one account's current live EventTrade exposure."""
    account = ACCOUNT_EXPOSURE.get(account_id)
    if account is None:
        raise ApiError(404, "account_not_found", "Account not found", {"accountId": account_id})

    exposure = serialize_account_exposure(account)
    if not exposure["positions"]:
        raise ApiError(404, "account_not_found", "Account not found", {"accountId": account_id})

    return {
        "account": {
            "id": account_id,
            "exposure": exposure,
        },
        "meta": make_meta(),
    }, 200


def get_account_risk(account_id: str) -> tuple[dict[str, Any], int]:
    """Return the read model for one account's current risk state."""
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
    """Return the market collection, optionally filtered by status."""
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


def create_market(body: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Create a new market from a POST payload."""
    if not body:
        raise ApiError(400, "invalid_payload", "Request body is required")

    title = body.get("title")
    description = body.get("description", "")
    outcomes = body.get("outcomes")
    expires_at = body.get("expires_at")
    liquidity = body.get("liquidity", 10000.0)

    if not title or not isinstance(title, str):
        raise ApiError(400, "invalid_payload", "title is required and must be a string")
    if not outcomes or not isinstance(outcomes, list) or len(outcomes) < 2:
        raise ApiError(400, "invalid_payload", "outcomes must be a list with at least 2 entries")
    for o in outcomes:
        if not isinstance(o, dict) or "id" not in o or "name" not in o:
            raise ApiError(400, "invalid_payload", "each outcome must have id and name")
    if not expires_at or not isinstance(expires_at, str):
        raise ApiError(400, "invalid_payload", "expires_at is required (ISO 8601 string)")

    # Check for duplicate outcome IDs
    outcome_ids = [o["id"] for o in outcomes]
    if len(outcome_ids) != len(set(outcome_ids)):
        raise ApiError(400, "invalid_payload", "outcome IDs must be unique")

    # Generate variable ID from title
    variable_id = title.lower().replace(" ", "_")[:40]
    existing_market = next(
        (market for market in MARKETS.values() if str(market.get("variableId")) == variable_id),
        None,
    )
    if existing_market is not None:
        raise ApiError(
            409,
            "market_already_exists",
            "A market with this title already exists",
            {
                "title": title,
                "variableId": variable_id,
                "existingMarketId": str(existing_market["id"]),
            },
        )

    # Generate market ID
    market_num = len(MARKETS) + 1
    market_id = f"m{market_num}"
    while market_id in MARKETS:
        market_num += 1
        market_id = f"m{market_num}"

    # Uniform prior
    uniform_p = round(1.0 / len(outcomes), 6)
    marginals = {}
    for i, o in enumerate(outcomes):
        if i < len(outcomes) - 1:
            marginals[o["id"]] = uniform_p
        else:
            marginals[o["id"]] = round(1.0 - uniform_p * (len(outcomes) - 1), 6)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    market: dict[str, Any] = {
        "id": market_id,
        "title": title,
        "description": description,
        "variableId": variable_id,
        "status": "active",
        "outcomes": [{"id": o["id"], "name": o["name"]} for o in outcomes],
        "marginals": marginals,
        "liquidity": float(liquidity),
        "volume": 0.0,
        "created_at": now,
        "expires_at": expires_at,
    }

    MARKETS[market_id] = market
    ensure_market_engine_state(market_id)

    return {
        "market": deepcopy(market),
        "meta": make_meta(),
    }, 201


def parse_market_context_query(
    query: dict[str, list[str]],
    *,
    target_variable_id: str,
) -> list[dict[str, str]]:
    """Parse repeated context query params into normalized condition assignments."""
    raw_context_values = query.get("context", [])
    if not raw_context_values:
        return []

    context_assignments: list[dict[str, str]] = []
    for index, raw_context in enumerate(raw_context_values):
        variable_id, separator, outcome_id = raw_context.partition("=")
        if not separator or not variable_id.strip() or not outcome_id.strip():
            raise ApiError(
                400,
                "invalid_query",
                "context entries must use variableId=outcomeId",
                {
                    "parameter": "context",
                    "index": index,
                    "received": raw_context,
                },
            )
        context_assignments.append(
            {
                "variableId": variable_id,
                "outcomeId": outcome_id,
            }
        )

    try:
        return normalize_context_assignments(target_variable_id, context_assignments)
    except ApiError as exc:
        if exc.code != "invalid_probability_edit":
            raise
        details = {"parameter": "context", **exc.details}
        raise ApiError(400, "invalid_query", exc.message, details) from exc


def get_market_detail(
    market_id: str,
    query: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Return the full market payload for one market id."""
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    market_payload = deepcopy(market)
    context = parse_market_context_query(query or {}, target_variable_id=str(market["variableId"]))
    if context:
        market_payload["marginals"] = query_market_marginals_for_inference(market_id, context)

    return {
        "market": market_payload,
        "meta": make_meta(),
    }, 200


def get_market_preview_response(
    market_id: str,
    *,
    headers: Any | None = None,
) -> tuple[dict[str, Any], int]:
    """Return the normalized share-preview payload for one market id."""
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    return {
        "preview": build_market_preview(market, headers=headers),
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
    """Parse and validate an integer query parameter with bounds."""
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
    """Return the paginated event journal for a market."""
    if market_id not in MARKETS:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    from_seq = parse_integer_query_param(query, "fromSeq", default=1, minimum=1)
    limit = parse_integer_query_param(query, "limit", default=100, minimum=1, maximum=100)

    with get_market_write_lock(market_id):
        with _EVENTS_LOCK:
            event_records = list(EVENTS.values())
        market_events = sorted(
            (
                deepcopy(event)
                for event in event_records
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


def get_market_comments(market_id: str, query: dict[str, list[str]]) -> tuple[dict[str, Any], int]:
    """Return the paginated discussion thread for a market."""
    if market_id not in MARKETS:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    from_seq = parse_integer_query_param(query, "fromSeq", default=1, minimum=1)
    limit = parse_integer_query_param(query, "limit", default=100, minimum=1, maximum=100)

    with get_market_write_lock(market_id):
        with _COMMENTS_LOCK:
            comment_records = list(COMMENTS.values())
        market_comments = sorted(
            (
                deepcopy(comment)
                for comment in comment_records
                if str(comment["marketId"]) == market_id and int(comment["seq"]) >= from_seq
            ),
            key=lambda comment: int(comment["seq"]),
        )
        page_comments = market_comments[:limit]
        head_seq = MARKET_COMMENT_SEQUENCES.get(market_id, 0)

    next_from_seq = None
    if page_comments:
        tail_seq = int(page_comments[-1]["seq"])
        if tail_seq < head_seq:
            next_from_seq = tail_seq + 1

    return {
        "marketId": market_id,
        "comments": page_comments,
        "pagination": {
            "fromSeq": from_seq,
            "limit": limit,
            "returned": len(page_comments),
            "nextFromSeq": next_from_seq,
        },
        "meta": make_meta(),
    }, 200


def kl_divergence(previous: dict[str, float], updated: dict[str, float]) -> float:
    """Compute the KL divergence from one marginal distribution to another."""
    return round(
        sum(
            new * math.log(new / old)
            for outcome_id, new in updated.items()
            if new > 0 and (old := previous.get(outcome_id, 0.0)) > 0
        ),
        6,
    )


def find_market_by_variable_id(variable_id: str) -> dict[str, Any] | None:
    """Look up a market by its canonical variable id."""
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
    outcome_ids = _market_outcome_ids(market)
    try:
        updated = lmsr.rescale_probability_edit(base_marginals, outcome_id, probability)
    except ValueError as exc:
        raise ValueError(str(exc).replace("previous", "market.marginals")) from exc

    ordered_outcome_ids = [outcome_id, *[candidate for candidate in outcome_ids if candidate != outcome_id]]
    rounded = {candidate: round(updated[candidate], 12) for candidate in ordered_outcome_ids}
    rounding_drift = round(1.0 - sum(rounded.values()), 12)
    if rounding_drift != 0:
        rounded_outcomes = [candidate for candidate in outcome_ids if candidate != outcome_id]
        if not rounded_outcomes:
            raise ValueError("market must have at least two outcomes")
        rounded[rounded_outcomes[-1]] = round(rounded[rounded_outcomes[-1]] + rounding_drift, 12)
    return rounded


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
    """Normalize and validate probability-edit context assignments."""
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
    """Normalize an event formula against variable-id references."""
    return formula_schema.normalize_event_formula(
        formula,
        lookup_market_by_variable_id=find_market_by_variable_id,
        error_factory=ApiError,
        max_clauses=MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals=MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    )


def validate_event_trade_formula_market_ids(formula: Any) -> None:
    """Validate that market-id references in an event formula all exist."""
    formula_schema.validate_event_trade_formula_market_ids(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
        error_factory=ApiError,
    )


def translate_event_trade_formula_for_validation(formula: Any) -> Any:
    """Translate an event formula into the validation-friendly representation."""
    return formula_schema.translate_event_trade_formula_for_validation(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
    )


def restore_event_trade_formula_market_ids(
    normalized_formula: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    """Restore market ids into a normalized event formula representation."""
    return formula_schema.restore_event_trade_formula_market_ids(
        normalized_formula,
        lookup_market_by_variable_id=find_market_by_variable_id,
    )


def normalize_event_trade_formula(formula: Any) -> list[list[dict[str, Any]]]:
    """Normalize an event-trade formula against market and variable references."""
    return formula_schema.normalize_event_trade_formula(
        formula,
        lookup_market_by_id=lambda market_id: MARKETS.get(market_id),
        lookup_market_by_variable_id=find_market_by_variable_id,
        error_factory=ApiError,
        max_clauses=MAX_EVENT_FORMULA_CLAUSES,
        max_clause_literals=MAX_EVENT_FORMULA_CLAUSE_LITERALS,
    )


def normalize_event_trade_size(payload: dict[str, Any]) -> float:
    """Normalize and validate the size field for an event trade request."""
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
    """Normalize and validate the side field for an event trade request."""
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
    """Require that an event-trade formula collapses to a single literal."""
    return formula_schema.require_atomic_event_trade_formula(
        formula,
        error_factory=ApiError,
    )


def normalize_event_trade_payload(market_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate an event-trade request body."""
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
    """Serialize context assignments into the canonical state-key format."""
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
    """Resolve the base marginals for a probability edit via the inference engine."""
    return query_market_marginals_for_inference(market_id, context)


def fallback_probability_edit_base_marginals(
    market_id: str,
    context: list[dict[str, str]],
) -> dict[str, float]:
    """Resolve the base marginals for a probability edit from stored state only."""
    market = MARKETS[market_id]
    if not context:
        return deepcopy(market["marginals"])

    context_key = context_state_key(context)
    market_conditionals = CONDITIONAL_MARGINALS.get(market_id, {})
    return deepcopy(market_conditionals.get(context_key, market["marginals"]))


def idempotency_scope_key(market_id: str, account_id: str, idempotency_key: str) -> tuple[str, str, str]:
    """Build the idempotency namespace key for one request scope."""
    return market_id, account_id, idempotency_key


def market_replay_state_hash(market_id: str) -> str:
    """Hash the replay-relevant state for a market."""
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
    """Apply a probability target to a market and return the new marginals."""
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
    """Normalize and validate a probability-edit target value."""
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
    """Preview the market and risk impact of an unconditional probability edit."""
    if payload["context"]:
        raise ValueError("preview_unconditional_probability_edit requires an empty context")

    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    target = payload["target"]
    previous_marginals = resolve_probability_edit_base_marginals(market_id, [])
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
    """Materialize and persist an accepted probability-edit order."""
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
        impact_score = kl_divergence(previous_marginals, updated_marginals)
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
        impact_score = round_risk_value(float(preview["impactScore"]))

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
        "impactScore": impact_score,
        "createdAt": timestamp,
        "filledAt": timestamp,
    }
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        order["idempotencyKey"] = idempotency_key
    ORDERS[order["id"]] = deepcopy(order)
    return order


def build_market_resolution_marginals(market: dict[str, Any], outcome_id: str) -> dict[str, float]:
    """Build a point-mass marginal distribution for a resolved market."""
    outcome_ids = _market_outcome_ids(market)
    if outcome_id not in outcome_ids:
        raise ApiError(
            400,
            "invalid_market_resolution",
            "outcomeId must match a known market outcome",
            {
                "field": "outcomeId",
                "marketId": str(market["id"]),
                "received": outcome_id,
                "allowed": sorted(outcome_ids),
            },
        )

    return {candidate: 1.0 if candidate == outcome_id else 0.0 for candidate in outcome_ids}


_MARKET_RESOLUTION_FIELD_UNSET = object()


def normalize_market_resolution_probabilities(
    market: dict[str, Any],
    raw_final_probabilities: Any,
) -> dict[str, float]:
    """Normalize and validate an explicit market-resolution probability map."""
    if not isinstance(raw_final_probabilities, dict):
        raise ApiError(
            400,
            "invalid_market_resolution",
            "finalProbabilities must be an object",
            {"field": "finalProbabilities"},
        )

    market_id = str(market["id"])
    outcome_ids = _market_outcome_ids(market)
    missing_outcome_ids = [outcome_id for outcome_id in outcome_ids if outcome_id not in raw_final_probabilities]
    unexpected_outcome_ids = sorted(str(outcome_id) for outcome_id in raw_final_probabilities if str(outcome_id) not in outcome_ids)
    if missing_outcome_ids or unexpected_outcome_ids:
        details: dict[str, Any] = {
            "field": "finalProbabilities",
            "marketId": market_id,
        }
        if missing_outcome_ids:
            details["missing"] = missing_outcome_ids
        if unexpected_outcome_ids:
            details["unexpected"] = unexpected_outcome_ids
        raise ApiError(
            400,
            "invalid_market_resolution",
            "finalProbabilities must contain exactly one value for each market outcome",
            details,
        )

    normalized: dict[str, float] = {}
    for outcome_id in outcome_ids:
        value = raw_final_probabilities[outcome_id]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ApiError(
                400,
                "invalid_market_resolution",
                "finalProbabilities must contain finite numeric values for all market outcomes",
                {
                    "field": f"finalProbabilities.{outcome_id}",
                    "marketId": market_id,
                    "outcomeId": outcome_id,
                },
            )

        normalized[outcome_id] = float(value)
        if normalized[outcome_id] < 0:
            raise ApiError(
                400,
                "invalid_market_resolution",
                "finalProbabilities must preserve non-negative values for all outcomes",
                {
                    "field": f"finalProbabilities.{outcome_id}",
                    "marketId": market_id,
                    "outcomeId": outcome_id,
                },
            )

    total_probability = sum(normalized.values())
    if not math.isclose(total_probability, 1.0, abs_tol=1e-9):
        raise ApiError(
            400,
            "invalid_market_resolution",
            "finalProbabilities must sum to 1.0",
            {
                "field": "finalProbabilities",
                "marketId": market_id,
                "sum": total_probability,
            },
        )

    return normalized


def resolve_market_resolution_outcome_id(
    market: dict[str, Any],
    final_probabilities: dict[str, float],
) -> str:
    """Resolve a validated final-probabilities map to the current point-mass settlement outcome."""
    point_mass_outcomes = [
        outcome_id
        for outcome_id, probability in final_probabilities.items()
        if math.isclose(probability, 1.0, abs_tol=1e-9)
    ]
    if len(point_mass_outcomes) != 1:
        raise ApiError(
            400,
            "invalid_market_resolution",
            "finalProbabilities must encode a point-mass distribution",
            {
                "field": "finalProbabilities",
                "marketId": str(market["id"]),
            },
        )

    outcome_id = point_mass_outcomes[0]
    expected_distribution = build_market_resolution_marginals(market, outcome_id)
    if any(
        not math.isclose(probability, expected_distribution[candidate], abs_tol=1e-9)
        for candidate, probability in final_probabilities.items()
    ):
        raise ApiError(
            400,
            "invalid_market_resolution",
            "finalProbabilities must encode a point-mass distribution",
            {
                "field": "finalProbabilities",
                "marketId": str(market["id"]),
            },
        )
    return outcome_id


def canonicalize_market_resolution_inputs(
    market: dict[str, Any],
    raw_outcome_id: Any = _MARKET_RESOLUTION_FIELD_UNSET,
    raw_final_probabilities: Any = _MARKET_RESOLUTION_FIELD_UNSET,
) -> tuple[str, dict[str, float]]:
    """Validate and canonicalize market-resolution inputs to one winning outcome."""
    market_id = str(market["id"])
    outcome_id: str | None = None

    if raw_outcome_id is not _MARKET_RESOLUTION_FIELD_UNSET:
        if not isinstance(raw_outcome_id, str) or not raw_outcome_id.strip():
            raise ApiError(400, "invalid_market_resolution", "outcomeId is required", {"field": "outcomeId"})
        outcome_id = raw_outcome_id.strip()
        build_market_resolution_marginals(market, outcome_id)

    if raw_final_probabilities is not _MARKET_RESOLUTION_FIELD_UNSET:
        normalized_final_probabilities = normalize_market_resolution_probabilities(market, raw_final_probabilities)
        resolved_outcome_id = resolve_market_resolution_outcome_id(market, normalized_final_probabilities)
        if outcome_id is not None and outcome_id != resolved_outcome_id:
            raise ApiError(
                400,
                "invalid_market_resolution",
                "outcomeId must match finalProbabilities when both are provided",
                {
                    "field": "outcomeId",
                    "marketId": market_id,
                    "received": outcome_id,
                    "expected": resolved_outcome_id,
                },
            )
        outcome_id = resolved_outcome_id

    if outcome_id is None:
        raise ApiError(400, "invalid_market_resolution", "outcomeId is required", {"field": "outcomeId"})

    return outcome_id, build_market_resolution_marginals(market, outcome_id)


def normalize_market_resolution_payload(market_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a market-resolution request body."""
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    raw_outcome_id = payload["outcomeId"] if "outcomeId" in payload else _MARKET_RESOLUTION_FIELD_UNSET
    raw_final_probabilities = (
        payload["finalProbabilities"] if "finalProbabilities" in payload else _MARKET_RESOLUTION_FIELD_UNSET
    )
    outcome_id, final_probabilities = canonicalize_market_resolution_inputs(
        market,
        raw_outcome_id=raw_outcome_id,
        raw_final_probabilities=raw_final_probabilities,
    )

    return {
        "kind": "ResolveMarket",
        "outcomeId": outcome_id,
        "finalProbabilities": final_probabilities,
    }


def normalize_probability_edit_payload(market_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a probability-edit request body."""
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
    try:
        base_marginals = resolve_probability_edit_base_marginals(market_id, context)
    except ApiError as exc:
        if exc.status != 500 or exc.code != "internal_error":
            raise
        base_marginals = fallback_probability_edit_base_marginals(market_id, context)
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
    """Build and persist a probability-edit command envelope."""
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


def materialize_market_resolution_command(
    market_id: str,
    normalized_payload: dict[str, Any],
    account_id: str,
    command_id: str,
    submitted_at: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build and persist an AdminOp command envelope for market resolution."""
    command = {
        "schemaVersion": "bayes-command/v1",
        "commandId": command_id,
        "marketId": market_id,
        "accountId": account_id,
        "commandType": "AdminOp",
        "submittedAt": submitted_at,
        "payload": deepcopy(normalized_payload),
        "meta": {
            "source": "api",
        },
    }
    if idempotency_key is not None:
        command["idempotencyKey"] = idempotency_key

    COMMANDS[command_id] = deepcopy(command)
    return command


def materialize_comment_post_command(
    market_id: str,
    normalized_payload: dict[str, Any],
    account_id: str,
    command_id: str,
    submitted_at: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build and persist a comment-post command envelope for idempotent replay."""
    command = {
        "schemaVersion": "bayes-command/v1",
        "commandId": command_id,
        "marketId": market_id,
        "accountId": account_id,
        "commandType": "CommentPost",
        "submittedAt": submitted_at,
        "payload": deepcopy(normalized_payload),
        "meta": {
            "source": "api",
        },
    }
    if idempotency_key is not None:
        command["idempotencyKey"] = idempotency_key

    COMMANDS[command_id] = deepcopy(command)
    return command


def emit_terminal_event(command: dict[str, Any], event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a terminal event to the per-market event journal."""
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
        with _EVENTS_LOCK:
            EVENTS[str(event["eventId"])] = deepcopy(event)
        return event


def build_terminal_result(event: dict[str, Any]) -> dict[str, Any]:
    """Build the terminal result block returned to API callers."""
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


def command_response_meta_kwargs(command: dict[str, Any]) -> dict[str, Any]:
    """Build response meta fields shared by idempotent command responses."""
    meta_kwargs: dict[str, Any] = {}
    idempotency_key = command.get("idempotencyKey")
    if isinstance(idempotency_key, str):
        meta_kwargs["idempotencyKeyEcho"] = idempotency_key
    return meta_kwargs


def record_terminal_outcome(
    command: dict[str, Any],
    event: dict[str, Any],
    status: int,
    response: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> None:
    """Persist the final response for a command, including idempotency binding."""
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
    """Replay a previously persisted terminal command outcome."""
    outcome = TERMINAL_OUTCOMES[command_id]
    response = deepcopy(outcome["response"])
    response.setdefault("meta", {})
    response["meta"]["replayed"] = True
    return response, int(outcome["status"])


def record_comment_post_outcome(
    command: dict[str, Any],
    status: int,
    response: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> None:
    """Persist the final response for a comment post, including idempotency binding."""
    command_id = str(command["commandId"])
    COMMENT_POST_OUTCOMES[command_id] = {
        "status": status,
        "response": deepcopy(response),
    }
    if scope_key is not None:
        IDEMPOTENCY_KEYS[scope_key] = command_id


def replay_comment_post_outcome(command_id: str) -> tuple[dict[str, Any], int]:
    """Replay a previously persisted comment-post outcome."""
    outcome = COMMENT_POST_OUTCOMES[command_id]
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
    """Build the response for an idempotency-key payload mismatch."""
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


def build_terminal_response(
    command: dict[str, Any],
    *,
    event_type: str,
    event_payload: dict[str, Any],
    status: int,
    response_fields: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Emit, record, and return a terminal command response."""
    event = emit_terminal_event(command, event_type, event_payload)
    response = deepcopy(response_fields)
    response["result"] = build_terminal_result(event)
    response["meta"] = make_meta(**command_response_meta_kwargs(command))
    record_terminal_outcome(command, event, status, response, scope_key)
    return response, status


def build_terminal_rejection_response(
    command: dict[str, Any],
    code: str,
    message: str,
    details: dict[str, Any],
    retry_hint: str,
    status: int,
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Emit and persist a terminal rejection response for a command."""
    return build_terminal_response(
        command,
        event_type="CommandRejected",
        event_payload={
            "reasonCode": code,
            "reason": message,
            "retryHint": retry_hint,
        },
        status=status,
        response_fields={
            "error": {
                "code": code,
                "message": message,
                "details": deepcopy(details),
            },
        },
        scope_key=scope_key,
    )


def build_terminal_acceptance_response(
    command: dict[str, Any],
    order: dict[str, Any],
    asset_delta: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Emit and persist a terminal acceptance response for a probability edit."""
    target = order["payload"]["target"]
    delta = {
        "variableId": order["payload"]["variableId"],
        "outcomeId": target["outcomeId"],
        "before": order["previousMarginals"][target["outcomeId"]],
        "after": order["newMarginals"][target["outcomeId"]],
    }
    if order["payload"]["context"]:
        delta["context"] = deepcopy(order["payload"]["context"])

    return build_terminal_response(
        command,
        event_type="CommandAccepted",
        event_payload={
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
        status=201,
        response_fields={
            "order": deepcopy(order),
        },
        scope_key=scope_key,
    )


def settle_market_account_risk(market_id: str, timestamp: str) -> list[dict[str, Any]]:
    """Release current market exposure from account risk and LMSR read models."""
    asset_deltas: list[dict[str, Any]] = []

    for account_id in sorted(ACCOUNT_RISK):
        account = ACCOUNT_RISK[account_id]
        markets = account.get("markets")
        if not isinstance(markets, dict):
            continue

        removed_market = markets.pop(market_id, None)
        lmsr_state = ensure_account_lmsr_state(account)
        slices = lmsr_state["slices"]
        slice_keys_to_remove = [
            slice_key
            for slice_key, slice_state in list(slices.items())
            if isinstance(slice_state, dict) and str(slice_state.get("marketId")) == market_id
        ]
        for slice_key in slice_keys_to_remove:
            del slices[slice_key]

        if removed_market is None and not slice_keys_to_remove:
            continue

        before_min_asset = round_risk_value(float(account["minAsset"]))
        risk_limit = round_risk_value(float(account["riskLimit"]))
        remaining_consumed = round_risk_value(
            sum(float(market_state["capacityConsumed"]) for market_state in markets.values())
        )
        after_min_asset = round_risk_value(risk_limit - remaining_consumed)
        account["minAsset"] = after_min_asset
        account["updatedAt"] = timestamp

        if removed_market is not None:
            asset_deltas.append(
                {
                    "accountId": account_id,
                    "marketId": market_id,
                    "beforeMinAsset": before_min_asset,
                    "afterMinAsset": after_min_asset,
                }
            )

    return asset_deltas


def transition_market_to_resolved(
    market_id: str,
    outcome_id: str,
    final_probabilities: dict[str, float],
    *,
    resolved_at: str,
) -> dict[str, Any]:
    """Apply the replay-relevant market mutation for an accepted resolution."""
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    status = str(market["status"])
    if status == "resolved":
        raise ApiError(
            409,
            "market_already_resolved",
            "Market is already resolved",
            {
                "marketId": market_id,
                "status": status,
                "currentResolution": market.get("resolution"),
            },
        )
    if status not in {"active", "closed"}:
        raise ApiError(
            409,
            "market_not_resolvable",
            "Market can only be resolved from active or closed status",
            {
                "marketId": market_id,
                "status": status,
                "allowedStatuses": ["active", "closed"],
            },
        )

    outcome_id, canonical_final_probabilities = canonicalize_market_resolution_inputs(
        market,
        raw_outcome_id=outcome_id,
        raw_final_probabilities=final_probabilities,
    )
    previous_marginals = deepcopy(market["marginals"])
    new_marginals = deepcopy(canonical_final_probabilities)
    market["status"] = "resolved"
    market["resolution"] = outcome_id
    market["resolutionProbabilities"] = deepcopy(new_marginals)
    market["marginals"] = deepcopy(new_marginals)
    CONDITIONAL_MARGINALS.pop(market_id, None)

    return {
        "market": deepcopy(market),
        "previousMarginals": previous_marginals,
        "newMarginals": deepcopy(new_marginals),
        "resolvedAt": resolved_at,
    }


def resolve_market_command(command: dict[str, Any]) -> dict[str, Any]:
    """Apply a market-resolution AdminOp and return the accepted event inputs."""
    resolved_at = utc_timestamp()
    resolution = transition_market_to_resolved(
        str(command["marketId"]),
        str(command["payload"]["outcomeId"]),
        deepcopy(command["payload"]["finalProbabilities"]),
        resolved_at=resolved_at,
    )
    resolution["assetDelta"] = settle_market_account_risk(str(command["marketId"]), resolved_at)
    return resolution


def build_market_resolution_acceptance_response(
    command: dict[str, Any],
    resolution: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Emit and persist a terminal acceptance response for a market resolution."""
    market = MARKETS[str(command["marketId"])]
    marginal_delta = [
        {
            "variableId": str(market["variableId"]),
            "outcomeId": outcome_id,
            "before": resolution["previousMarginals"][outcome_id],
            "after": resolution["newMarginals"][outcome_id],
        }
        for outcome_id in _market_outcome_ids(market)
        if resolution["previousMarginals"][outcome_id] != resolution["newMarginals"][outcome_id]
    ]

    return build_terminal_response(
        command,
        event_type="CommandAccepted",
        event_payload={
            "resolution": {
                "outcomeId": str(command["payload"]["outcomeId"]),
                "finalProbabilities": deepcopy(command["payload"]["finalProbabilities"]),
                "resolvedAt": str(resolution["resolvedAt"]),
            },
            "effects": {
                "marginalDelta": marginal_delta,
                "assetDelta": deepcopy(resolution["assetDelta"]),
            },
            "pricing": {
                "cost": 0.0,
                "fee": 0.0,
            },
            "replayStateHash": market_replay_state_hash(str(command["marketId"])),
        },
        status=201,
        response_fields={
            "market": deepcopy(resolution["market"]),
        },
        scope_key=scope_key,
    )


def materialize_event_trade_command(
    market_id: str,
    normalized_payload: dict[str, Any],
    account_id: str,
    command_id: str,
    submitted_at: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build and persist an event-trade command envelope."""
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
    """Materialize and persist an accepted event-trade order."""
    market_id = str(command["marketId"])
    market = MARKETS.get(market_id)
    if not market:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    payload = command["payload"]
    literal = payload["formula"][0][0]
    outcome_id = str(literal["outcomeId"])
    price = round_risk_value(query_market_atomic_probability_for_inference(market_id, outcome_id))
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
    """Emit and persist a terminal acceptance response for an event trade."""
    literal = order["payload"]["formula"][0][0]
    return build_terminal_response(
        command,
        event_type="CommandAccepted",
        event_payload={
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
        status=201,
        response_fields={
            "order": deepcopy(order),
        },
        scope_key=scope_key,
    )


def normalize_comment_post_payload(market_id: str, body: dict[str, Any]) -> dict[str, str]:
    """Normalize one comment-post payload."""
    if market_id not in MARKETS:
        raise ApiError(404, "market_not_found", "Market not found", {"market_id": market_id})

    comment_body = body.get("body")
    if not isinstance(comment_body, str):
        raise ApiError(400, "invalid_comment", "body is required", {"field": "body"})

    normalized_body = comment_body.strip()
    if not normalized_body:
        raise ApiError(400, "invalid_comment", "body is required", {"field": "body"})
    if len(normalized_body) > MAX_COMMENT_BODY_LENGTH:
        raise ApiError(
            400,
            "invalid_comment",
            f"body must be at most {MAX_COMMENT_BODY_LENGTH} characters",
            {"field": "body", "maximum": MAX_COMMENT_BODY_LENGTH},
        )

    return {"body": normalized_body}


def create_market_comment(command: dict[str, Any]) -> dict[str, Any]:
    """Materialize and persist a market comment."""
    market_id = str(command["marketId"])
    seq = MARKET_COMMENT_SEQUENCES.get(market_id, 0) + 1
    comment = {
        "commentId": generate_comment_id(),
        "marketId": market_id,
        "seq": seq,
        "accountId": str(command["accountId"]),
        "body": str(command["payload"]["body"]),
        "createdAt": str(command["submittedAt"]),
    }
    MARKET_COMMENT_SEQUENCES[market_id] = seq
    with _COMMENTS_LOCK:
        COMMENTS[str(comment["commentId"])] = deepcopy(comment)
    return comment


def build_comment_post_acceptance_response(
    command: dict[str, Any],
    comment: dict[str, Any],
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Persist and return an accepted comment-post response."""
    response = {
        "comment": deepcopy(comment),
        "meta": make_meta(**command_response_meta_kwargs(command)),
    }
    record_comment_post_outcome(command, 201, response, scope_key)
    return response, 201


def build_comment_post_rejection_response(
    command: dict[str, Any],
    *,
    code: str,
    message: str,
    details: dict[str, Any],
    status: int,
    scope_key: tuple[str, str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Persist and return a rejected comment-post response."""
    response = {
        "error": {
            "code": code,
            "message": message,
            "details": deepcopy(details),
        },
        "meta": make_meta(**command_response_meta_kwargs(command)),
    }
    record_comment_post_outcome(command, status, response, scope_key)
    return response, status


def handle_comment_post(market_id: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Handle the full comment-post request lifecycle for one market."""
    body = payload if payload is not None else {}
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    account_id = body.get("accountId")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ApiError(400, "invalid_comment", "accountId is required", {"field": "accountId"})

    idempotency_key = body.get("idempotencyKey")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApiError(
                400,
                "invalid_comment",
                "idempotencyKey must be a non-empty string when provided",
                {"field": "idempotencyKey"},
            )
        idempotency_key = idempotency_key.strip()

    account_id = account_id.strip()
    scope_key = idempotency_scope_key(market_id, account_id, idempotency_key) if idempotency_key is not None else None

    with get_market_write_lock(market_id):
        normalized_payload = normalize_comment_post_payload(market_id, body)
        if scope_key is not None:
            existing_command_id = IDEMPOTENCY_KEYS.get(scope_key)
            if existing_command_id is not None:
                existing_command = COMMANDS[existing_command_id]
                if existing_command["commandType"] != "CommentPost" or existing_command["payload"] != normalized_payload:
                    return build_idempotency_conflict_response(
                        existing_command_id,
                        idempotency_key,
                        market_id,
                        account_id,
                        "CommentPost",
                    )
                return replay_comment_post_outcome(existing_command_id)

        submitted_at = utc_timestamp()
        command = materialize_comment_post_command(
            market_id=market_id,
            normalized_payload=normalized_payload,
            account_id=account_id,
            command_id=generate_command_id(),
            submitted_at=submitted_at,
            idempotency_key=idempotency_key,
        )
        market = MARKETS[market_id]
        if market["status"] != "active":
            return build_comment_post_rejection_response(
                command,
                code="market_not_active",
                message="Comments are only allowed for active markets",
                details={
                    "marketId": market_id,
                    "status": market["status"],
                    "allowedStatus": "active",
                    "commandId": command["commandId"],
                },
                status=409,
                scope_key=scope_key,
            )

        comment = create_market_comment(command)
        return build_comment_post_acceptance_response(command, comment, scope_key)


def handle_probability_edit(market_id: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Handle the full ProbabilityEdit request lifecycle for one market."""
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

    account_id = account_id.strip()
    scope_key = idempotency_scope_key(market_id, account_id, idempotency_key) if idempotency_key is not None else None
    with get_market_write_lock(market_id):
        normalized_payload = normalize_probability_edit_payload(market_id, body)
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
    """Handle the full EventTrade request lifecycle for one market."""
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

    account_id = account_id.strip()
    scope_key = idempotency_scope_key(market_id, account_id, idempotency_key) if idempotency_key is not None else None
    with get_market_write_lock(market_id):
        normalized_payload = normalize_event_trade_payload(market_id, body)
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
        sync_account_exposure_state(order)
        return build_event_trade_acceptance_response(command, order, scope_key)


def handle_market_resolution(market_id: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Handle the full AdminOp-backed market-resolution lifecycle for one market."""
    body = payload if payload is not None else {}
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_body", "payload must be an object")

    account_id = body.get("accountId")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ApiError(400, "invalid_market_resolution", "accountId is required", {"field": "accountId"})

    idempotency_key = body.get("idempotencyKey")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApiError(
                400,
                "invalid_market_resolution",
                "idempotencyKey must be a non-empty string when provided",
                {"field": "idempotencyKey"},
            )
        idempotency_key = idempotency_key.strip()

    normalized_payload = normalize_market_resolution_payload(market_id, body)
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
                    "AdminOp",
                )
            return replay_terminal_outcome(existing_command_id)

    submitted_at = utc_timestamp()
    command = materialize_market_resolution_command(
        market_id=market_id,
        normalized_payload=normalized_payload,
        account_id=account_id,
        command_id=generate_command_id(),
        submitted_at=submitted_at,
        idempotency_key=idempotency_key,
    )
    market = MARKETS[market_id]
    if market["status"] == "resolved":
        return build_terminal_rejection_response(
            command,
            code="market_already_resolved",
            message="Market is already resolved",
            details={
                "marketId": market_id,
                "status": market["status"],
                "currentResolution": market.get("resolution"),
                "commandId": command["commandId"],
            },
            retry_hint="reuse the original idempotency key to replay the prior outcome",
            status=409,
            scope_key=scope_key,
        )
    if market["status"] not in {"active", "closed"}:
        return build_terminal_rejection_response(
            command,
            code="market_not_resolvable",
            message="Market can only be resolved from active or closed status",
            details={
                "marketId": market_id,
                "status": market["status"],
                "allowedStatuses": ["active", "closed"],
                "commandId": command["commandId"],
            },
            retry_hint="resolve an active or closed market",
            status=409,
            scope_key=scope_key,
        )

    resolution = resolve_market_command(command)
    return build_market_resolution_acceptance_response(command, resolution, scope_key)


def route_request(
    method: str,
    raw_path: str,
    body: dict[str, Any] | None = None,
    headers: Any | None = None,
) -> tuple[dict[str, Any], int]:
    """Route one HTTP request into the backend's in-memory handlers."""
    parsed = urlparse(raw_path)
    path = normalize_path(parsed.path)

    if method == "GET" and path == "/":
        return service_index_payload(), 200

    if method == "GET" and path in {"/health", "/healthz"}:
        return health_payload(), 200

    if path == "/v1/markets":
        if method == "GET":
            return list_markets(parse_qs(parsed.query, keep_blank_values=True))
        if method == "POST":
            return create_market(body)
        raise ApiError(
            405,
            "method_not_allowed",
            f"{method} is not allowed for this resource",
            {"method": method, "path": path},
        )

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
            return get_market_detail(market_id, parse_qs(parsed.query, keep_blank_values=True))

        if len(parts) == 4 and parts[3] == "meta":
            if method != "GET":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            return get_market_preview_response(market_id, headers=headers)

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

        if len(parts) == 4 and parts[3] == "comments":
            if method == "GET":
                return get_market_comments(market_id, parse_qs(parsed.query, keep_blank_values=True))
            if method == "POST":
                return handle_comment_post(market_id, body)
            raise ApiError(
                405,
                "method_not_allowed",
                f"{method} is not allowed for this resource",
                {"method": method, "path": path},
            )

        if len(parts) == 4 and parts[3] == "resolve":
            if method != "POST":
                raise ApiError(
                    405,
                    "method_not_allowed",
                    f"{method} is not allowed for this resource",
                    {"method": method, "path": path},
                )
            started_at = time.perf_counter()
            try:
                payload, status = handle_market_resolution(market_id, body)
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


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

MIME_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
}


def should_fallback_to_frontend_index(url_path: str) -> bool:
    """Return whether a request path should load the SPA shell."""
    clean = url_path.split("?")[0].split("#")[0] or "/"
    if clean in {"/", "/index.html"}:
        return True
    if clean == "/assets" or clean.startswith("/assets/"):
        return False
    return PurePosixPath(clean).suffix == ""


class BayesHandler(BaseHTTPRequestHandler):
    """HTTP handler that exposes the Bayes Market API over JSON."""

    def log_message(self, fmt: str, *args: object) -> None:
        """Suppress the default BaseHTTPRequestHandler access log output."""
        return

    def send_json(
        self,
        data: dict[str, Any],
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Write a JSON response body with the standard headers."""
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
        write_request = resolve_write_request_agent(method, self.path, self.headers)
        if write_request is None:
            return ""

        enforce_rate_limit(write_request.agent_id)
        return write_request.agent_id

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
        """Execute one API request and translate ApiError into JSON responses."""
        extra_headers: dict[str, str] | None = None
        try:
            body = self._read_json_body() if method in {"POST", "PUT", "PATCH"} else None
            agent_id = self._enforce_write_controls(method)
            payload, status = route_request(method, self.path, body, headers=self.headers)
            if status < 400:
                extra_headers = rate_limit_headers(agent_id)
        except ApiError as exc:
            payload, status = error_payload(exc.code, exc.message, **exc.details), exc.status
            if exc.code == "rate_limit_exceeded":
                retry_after = str(exc.details.get("retryAfterSeconds", 1))
                extra_headers = {"Retry-After": retry_after}
                extra_headers.update(rate_limit_headers(str(exc.details.get("agentId", ""))))
        self.send_json(payload, status, extra_headers=extra_headers)

    def _serve_static(self, url_path: str) -> bool:
        """Try to serve a static file from frontend/dist/. Return True if served."""
        if not FRONTEND_DIST.is_dir():
            return False

        requested_path = normalize_frontend_page_path(url_path)
        clean = requested_path
        if clean == "/":
            clean = "/index.html"

        dist_root = FRONTEND_DIST.resolve()
        candidate = (dist_root / clean.lstrip("/")).resolve()
        try:
            candidate.relative_to(dist_root)
        except ValueError:
            return False

        if not candidate.is_file():
            if not should_fallback_to_frontend_index(clean):
                return False
            candidate = dist_root / "index.html"
            if not candidate.is_file():
                return False

        if candidate == dist_root / "index.html":
            content = render_frontend_index_html(
                candidate.read_text(encoding="utf-8"),
                requested_path,
                headers=self.headers,
            )
        else:
            content = candidate.read_bytes()
        ext = candidate.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        if candidate == dist_root / "index.html":
            self.send_header("Cache-Control", "no-store")
        elif clean.startswith("/assets/") or ext in {".js", ".css", ".woff2", ".woff", ".ttf", ".png", ".svg", ".ico"}:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(content)
        return True

    def do_GET(self) -> None:  # noqa: N802
        """Serve API routes first, fall back to static frontend files."""
        path = normalize_path(urlparse(self.path).path)
        if path.startswith("/v1/") or path in {"/health", "/healthz"}:
            self.handle_api("GET")
            return
        if path == "/" and "application/json" in (self.headers.get("Accept") or ""):
            self.handle_api("GET")
            return
        if not self._serve_static(self.path):
            self.handle_api("GET")

    def do_POST(self) -> None:  # noqa: N802
        """Serve an HTTP POST request."""
        self.handle_api("POST")

    def do_PUT(self) -> None:  # noqa: N802
        """Serve an HTTP PUT request."""
        self.handle_api("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        """Serve an HTTP DELETE request."""
        self.handle_api("DELETE")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the standalone backend server."""
    parser = argparse.ArgumentParser(description="Bayes Market backend server")
    parser.add_argument("--host", default=os.environ.get("BAYES_MARKET_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BAYES_MARKET_PORT", "3205")))
    return parser.parse_args()


def run_server(host: str = "127.0.0.1", port: int = 3205) -> None:
    """Start the HTTP server and block forever."""
    HTTPServer((host, port), BayesHandler).serve_forever()


def main() -> int:
    """Run the backend from the command line and return an exit code."""
    args = parse_args()
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
