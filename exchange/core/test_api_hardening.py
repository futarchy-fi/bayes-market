"""
HTTP hardening tests (Task B6): CORS, request body size cap, OpenAPI
metadata, and rate limiting on the net-venue write routes.

Two test styles are used, matching the two conventions already in this
codebase:
  - CORS/body-cap-with-no-state/OpenAPI tests use the `client` fixture
    pattern from core/test_api.py (fresh app.state per test, no venue
    needed).
  - The oversized-Content-Length-with-real-state test and the net-order
    rate-limit test drive `core.api.lifespan` directly with
    EXCHANGE_SEEDS_PATH set, mirroring core/test_api_net.py, since they
    need a live joint venue behind /v1/net/orders(/preview).

A note on the "accumulated stream over cap, no/small Content-Length" case
from the brief: httpx (like most real HTTP clients) always computes and
sends an accurate Content-Length header for an in-memory bytes/str body,
so that path genuinely can't be driven honestly through an HTTP client in
this test suite. Per the task's own instruction ("do what's honest,
document it"), TestBodySizeLimitStreamGuard drives the ASGI middleware
directly with a fake `receive()` that mimics a chunked request with no
Content-Length at all -- exactly the case the accumulated guard exists for.
"""

import asyncio
import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("FUTARCHY_STATE", "/tmp/futarchy_test_state_hardening.json")
os.environ.setdefault("INITIAL_CREDITS", "1000")

import exchange.core.api as api_module
from exchange.core.api import app, _authenticate_github_identity
from exchange.core.auth import AuthStore
from exchange.core.middleware import (
    rate_limiter,
    BodySizeLimitMiddleware,
    MAX_BODY_BYTES,
)
from exchange.core.models import reset_counters
from exchange.core.risk_engine import RiskEngine
from exchange.core.market_engine import MarketEngine
from exchange.venues.joint.test_venue import TINY_SEEDS


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _write_seeds(tmp_path) -> str:
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps(TINY_SEEDS))
    return str(path)


async def _post(path: str, body: dict | None = None, headers: dict | None = None,
                 content: bytes | None = None, extra_headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        if content is not None:
            hdrs = {**(headers or {}), **(extra_headers or {})}
            return await c.post(path, content=content, headers=hdrs)
        return await c.post(path, json=body, headers=headers or {})


async def _authed_user(github_id: int = 1, login: str = "hardeninguser"):
    auth = await _authenticate_github_identity({"id": github_id, "login": login})
    return auth.api_key, auth.account_id


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Every test in this module manages its own env vars."""
    monkeypatch.delenv("EXCHANGE_SEEDS_PATH", raising=False)
    monkeypatch.delenv("JOINT_LIQUIDITY", raising=False)
    monkeypatch.delenv("JOINT_MAX_WIDTH", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    original_state_path = api_module.STATE_PATH
    yield
    api_module.STATE_PATH = original_state_path
    rate_limiter.rate = 60
    rate_limiter.buckets.clear()


@pytest.fixture
async def client():
    """Fresh app state per test, no net venue — mirrors core/test_api.py."""
    reset_counters()
    app.state.risk = RiskEngine()
    app.state.me = MarketEngine(app.state.risk)
    app.state.auth_store = AuthStore()
    app.state.tracked_repos = {}
    app.state.github_oauth_states = {}
    app.state.lock = asyncio.Lock()
    app.state.joint = None
    app.state.venues = {}
    rate_limiter.buckets.clear()

    try:
        os.remove(os.environ["FUTARCHY_STATE"])
    except FileNotFoundError:
        pass

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

class TestCORS:
    async def test_preflight_default_wildcard(self, client):
        resp = await client.options(
            "/v1/net/markets",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"
        assert "access-control-allow-credentials" not in {
            k.lower() for k in resp.headers.keys()
        }

    async def test_preflight_restricted_origin_echoed(self, client, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://futarchy.ai")
        resp = await client.options(
            "/v1/net/markets",
            headers={
                "Origin": "https://futarchy.ai",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://futarchy.ai"
        assert resp.headers.get("access-control-allow-credentials") == "true"

    async def test_preflight_rejects_non_allowed_origin(self, client, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://futarchy.ai")
        resp = await client.options(
            "/v1/net/markets",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Starlette's CORSMiddleware answers a disallowed-origin preflight
        # with 400 and no Access-Control-Allow-Origin header (it's the
        # browser's job to actually enforce the policy; the header is
        # simply never granted).
        assert resp.status_code == 400
        assert resp.headers.get("access-control-allow-origin") != "https://evil.example"

    async def test_allowed_methods_and_headers(self, client, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://futarchy.ai")
        resp = await client.options(
            "/v1/net/orders",
            headers={
                "Origin": "https://futarchy.ai",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert resp.status_code == 200
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        for method in ("GET", "POST", "PATCH", "DELETE", "OPTIONS"):
            assert method in allow_methods


# ---------------------------------------------------------------------------
# Body size cap
# ---------------------------------------------------------------------------

class TestBodySizeCapContentLength:
    async def test_oversized_content_length_rejected_413_no_state_change(
        self, tmp_path, monkeypatch
    ):
        reset_counters()
        seeds_path = _write_seeds(tmp_path)
        monkeypatch.setenv("EXCHANGE_SEEDS_PATH", seeds_path)
        api_module.STATE_PATH = str(tmp_path / "state.json")

        async with api_module.lifespan(app):
            api_key, account_id = await _authed_user()
            balance_before = app.state.risk.get_account(account_id).available_balance
            orders_before = len(app.state.joint._orders)

            padding = b"x" * (MAX_BODY_BYTES + 4096)
            oversized_body = (
                b'{"variableId": "gcx_a", "outcomeId": "yes", "target": 0.8, '
                b'"pad": "' + padding + b'"}'
            )
            resp = await _post(
                "/v1/net/orders",
                headers=_headers(api_key),
                content=oversized_body,
                extra_headers={"Content-Type": "application/json"},
            )

            assert resp.status_code == 413
            assert resp.json()["error"]["code"] == "request_too_large"

            # No mutation: the handler never ran.
            account = app.state.risk.get_account(account_id)
            assert account.available_balance == balance_before
            assert len(app.state.joint._orders) == orders_before

    async def test_small_body_unaffected(self, tmp_path, monkeypatch):
        reset_counters()
        seeds_path = _write_seeds(tmp_path)
        monkeypatch.setenv("EXCHANGE_SEEDS_PATH", seeds_path)
        api_module.STATE_PATH = str(tmp_path / "state.json")

        async with api_module.lifespan(app):
            api_key, _ = await _authed_user()
            resp = await _post(
                "/v1/net/orders/preview",
                body={"variableId": "gcx_a", "outcomeId": "yes", "target": 0.8},
                headers=_headers(api_key),
            )
            assert resp.status_code == 200


class TestBodySizeCapStreamGuard:
    """Drives the ASGI middleware directly with a fake `receive()` that
    mimics a chunked request with no Content-Length header at all -- the
    one case that can't honestly be exercised through an HTTP client that
    always sets an accurate Content-Length for in-memory bodies."""

    async def test_streamed_body_over_cap_without_content_length(self):
        chunk = b"x" * 20000  # 4 chunks = 80000 bytes > MAX_BODY_BYTES
        chunks = [chunk] * 4
        received_chunk_sizes = []

        async def inner_app(scope, receive, send):
            while True:
                message = await receive()
                received_chunk_sizes.append(len(message.get("body", b"")))
                if not message.get("more_body", False):
                    break
            # Would only run if the guard failed to fire.
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = BodySizeLimitMiddleware(inner_app, max_bytes=MAX_BODY_BYTES)

        scope = {"type": "http", "method": "POST", "path": "/v1/net/orders",
                  "headers": []}  # no content-length at all

        remaining = list(chunks)

        async def receive():
            if remaining:
                body = remaining.pop(0)
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": bool(remaining),
                }
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages = []

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        start = next(m for m in sent_messages if m["type"] == "http.response.start")
        assert start["status"] == 413
        body_msg = next(m for m in sent_messages if m["type"] == "http.response.body")
        payload = json.loads(body_msg["body"])
        assert payload["error"]["code"] == "request_too_large"

        # The guard fired partway through -- the inner app never drained
        # (let alone processed) the full oversized stream.
        assert sum(received_chunk_sizes) < sum(len(c) for c in chunks)

    async def test_stream_under_cap_passes_through(self):
        chunks = [b"x" * 100, b"y" * 100]
        received = []

        async def inner_app(scope, receive, send):
            while True:
                message = await receive()
                received.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = BodySizeLimitMiddleware(inner_app, max_bytes=MAX_BODY_BYTES)
        scope = {"type": "http", "method": "POST", "path": "/x", "headers": []}
        remaining = list(chunks)

        async def receive():
            if remaining:
                body = remaining.pop(0)
                return {"type": "http.request", "body": body, "more_body": bool(remaining)}
            return {"type": "http.request", "body": b"", "more_body": False}

        sent_messages = []

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)
        start = next(m for m in sent_messages if m["type"] == "http.response.start")
        assert start["status"] == 200
        assert b"".join(received) == b"x" * 100 + b"y" * 100


# ---------------------------------------------------------------------------
# OpenAPI metadata
# ---------------------------------------------------------------------------

class TestOpenAPIMetadata:
    async def test_openapi_title_and_net_routes(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert spec["info"]["title"] == "Futarchy Exchange API"
        assert "/v1/net/markets" in spec["paths"]
        assert "/v1/net/orders" in spec["paths"]
        assert "/v1/net/orders/preview" in spec["paths"]

    async def test_docs_served(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting on net writes
# ---------------------------------------------------------------------------

class TestNetOrderRateLimiting:
    async def test_preview_rate_limited_past_low_cap(self, tmp_path, monkeypatch):
        reset_counters()
        seeds_path = _write_seeds(tmp_path)
        monkeypatch.setenv("EXCHANGE_SEEDS_PATH", seeds_path)
        api_module.STATE_PATH = str(tmp_path / "state.json")

        async with api_module.lifespan(app):
            api_key, _ = await _authed_user()
            rate_limiter.rate = 2
            rate_limiter.buckets.clear()

            body = {"variableId": "gcx_a", "outcomeId": "yes", "target": 0.8}
            r1 = await _post("/v1/net/orders/preview", body=body, headers=_headers(api_key))
            r2 = await _post("/v1/net/orders/preview", body=body, headers=_headers(api_key))
            r3 = await _post("/v1/net/orders/preview", body=body, headers=_headers(api_key))

            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r3.status_code == 429
            assert r3.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# CORS on error responses (409, 429, 500)
# ---------------------------------------------------------------------------

class TestCORSErrorResponses:
    async def test_cors_headers_on_409_and_429_responses(self, tmp_path, monkeypatch):
        reset_counters()
        seeds_path = _write_seeds(tmp_path)
        monkeypatch.setenv("EXCHANGE_SEEDS_PATH", seeds_path)
        monkeypatch.setenv("CORS_ORIGINS", "https://futarchy.ai")
        api_module.STATE_PATH = str(tmp_path / "state.json")

        async with api_module.lifespan(app):
            api_key, _ = await _authed_user()
            # Resolve g1 so placing an order on gcx_a triggers 409 market_closed.
            res = await _post(
                "/v1/net/markets/g1/resolve",
                body={"outcome": "yes"},
                headers={"Authorization": "Bearer test-admin-key"},
            )
            assert res.status_code == 200

            body = {"variableId": "gcx_a", "outcomeId": "yes", "target": 0.8}
            r409 = await _post(
                "/v1/net/orders",
                body=body,
                headers={**_headers(api_key), "Origin": "https://futarchy.ai"},
            )
            assert r409.status_code == 409
            assert r409.headers.get("access-control-allow-origin") == "https://futarchy.ai"
            assert r409.headers.get("access-control-allow-credentials") == "true"

            r409_bad = await _post(
                "/v1/net/orders",
                body=body,
                headers={**_headers(api_key), "Origin": "https://evil.example"},
            )
            assert r409_bad.status_code == 409
            assert r409_bad.headers.get("access-control-allow-origin") is None

            # Trigger 429 rate limit with an allowlisted origin.
            rate_limiter.rate = 1
            rate_limiter.buckets.clear()
            ok = await _post(
                "/v1/net/orders/preview",
                body={"variableId": "gcx_b", "outcomeId": "yes", "target": 0.7},
                headers={**_headers(api_key), "Origin": "https://futarchy.ai"},
            )
            assert ok.status_code == 200
            r429 = await _post(
                "/v1/net/orders/preview",
                body={"variableId": "gcx_b", "outcomeId": "yes", "target": 0.7},
                headers={**_headers(api_key), "Origin": "https://futarchy.ai"},
            )
            assert r429.status_code == 429
            assert r429.json()["error"]["code"] == "rate_limited"
            assert r429.headers.get("access-control-allow-origin") == "https://futarchy.ai"
            assert r429.headers.get("access-control-allow-credentials") == "true"
            assert r429.headers.get("retry-after") == "60"

            r429_bad = await _post(
                "/v1/net/orders/preview",
                body={"variableId": "gcx_b", "outcomeId": "yes", "target": 0.7},
                headers={**_headers(api_key), "Origin": "https://evil.example"},
            )
            assert r429_bad.status_code == 429
            assert r429_bad.headers.get("access-control-allow-origin") is None

    async def test_cors_headers_on_500_unhandled_exception(self, monkeypatch):
        from exchange.core.middleware import DynamicCORSMiddleware

        monkeypatch.setenv("CORS_ORIGINS", "https://futarchy.ai")

        async def crashing_app(scope, receive, send):
            raise RuntimeError("boom")

        wrapped = DynamicCORSMiddleware(crashing_app)
        async with AsyncClient(
            transport=ASGITransport(app=wrapped), base_url="http://test"
        ) as c:
            r500 = await c.get("/boom", headers={"Origin": "https://futarchy.ai"})
            assert r500.status_code == 500
            assert r500.json()["error"]["code"] == "internal_error"
            assert r500.headers.get("access-control-allow-origin") == "https://futarchy.ai"
            assert r500.headers.get("access-control-allow-credentials") == "true"

            r500_bad = await c.get("/boom", headers={"Origin": "https://evil.example"})
            assert r500_bad.status_code == 500
            assert r500_bad.headers.get("access-control-allow-origin") is None


# ---------------------------------------------------------------------------
# OAuth state table cap & leaderboard upgrade hardening
# ---------------------------------------------------------------------------

class TestOAuthStateHardening:
    async def test_oauth_state_table_capped_at_2000_evicts_oldest(self, client, monkeypatch):
        from datetime import datetime, timedelta, timezone
        from urllib.parse import parse_qs, urlparse

        monkeypatch.setattr(api_module, "GITHUB_CLIENT_ID", "cid")
        base = datetime.now(timezone.utc) - timedelta(minutes=2)
        app.state.github_oauth_states = {
            f"state-{i}": base + timedelta(milliseconds=i)
            for i in range(api_module.GITHUB_OAUTH_STATE_MAX_ENTRIES)
        }
        assert len(app.state.github_oauth_states) == 2000

        resp = await client.get("/v1/auth/github/login", follow_redirects=False)
        assert resp.status_code == 302
        new_state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]

        assert len(app.state.github_oauth_states) == 2000
        assert "state-0" not in app.state.github_oauth_states
        assert "state-1999" in app.state.github_oauth_states
        assert new_state in app.state.github_oauth_states

    async def test_oauth_state_prunes_expired_before_evicting_active(self, client, monkeypatch):
        from datetime import datetime, timedelta, timezone

        monkeypatch.setattr(api_module, "GITHUB_CLIENT_ID", "cid")
        now = datetime.now(timezone.utc)
        app.state.github_oauth_states = {
            "expired-a": now - timedelta(minutes=15),
            "expired-b": now - timedelta(minutes=11),
            "fresh-a": now - timedelta(minutes=1),
        }

        resp = await client.get("/v1/auth/github/login", follow_redirects=False)
        assert resp.status_code == 302
        assert "expired-a" not in app.state.github_oauth_states
        assert "expired-b" not in app.state.github_oauth_states
        assert "fresh-a" in app.state.github_oauth_states


class TestLeaderboardUpgraded:
    async def test_leaderboard_named_traders_net_stats_and_tie_breaking(
        self, tmp_path, monkeypatch
    ):
        from decimal import Decimal

        reset_counters()
        seeds_path = _write_seeds(tmp_path)
        monkeypatch.setenv("EXCHANGE_SEEDS_PATH", seeds_path)
        api_module.STATE_PATH = str(tmp_path / "state_lb.json")
        admin_headers = {"Authorization": f"Bearer {os.environ['FUTARCHY_ADMIN_KEY']}"}

        async with api_module.lifespan(app):
            # Hidden service account (default is_service_account=True)
            bot_resp = await _post(
                "/v1/admin/service-accounts",
                {"username": "hidden_bot", "initial_credits": "50000"},
                headers=admin_headers,
            )
            assert bot_resp.status_code == 200
            bot_acc_id = bot_resp.json()["account_id"]

            # Two named guest traders with equal starting total (1000)
            alpha_resp = await _post(
                "/v1/admin/service-accounts",
                {
                    "username": "guest_alpha",
                    "display_name": "Guest Alpha",
                    "is_service_account": False,
                    "initial_credits": "1000",
                },
                headers=admin_headers,
            )
            assert alpha_resp.status_code == 200
            alpha_key = alpha_resp.json()["api_key"]
            alpha_acc_id = alpha_resp.json()["account_id"]

            beta_resp = await _post(
                "/v1/admin/service-accounts",
                {
                    "username": "guest_beta",
                    "display_name": "Guest Beta",
                    "is_service_account": False,
                    "initial_credits": "1000",
                },
                headers=admin_headers,
            )
            assert beta_resp.status_code == 200
            beta_key = beta_resp.json()["api_key"]
            beta_acc_id = beta_resp.json()["account_id"]

            # Two GitHub users with equal 1000 credits and zero orders
            _, gh1_acc_id = await _authed_user(github_id=101, login="gh_one")
            _, gh2_acc_id = await _authed_user(github_id=102, login="gh_two")

            # Alpha places 1 small order; Beta places 2 larger orders
            o_alpha = await _post(
                "/v1/net/orders",
                body={"variableId": "gcx_a", "outcomeId": "yes", "target": 0.55},
                headers=_headers(alpha_key),
            )
            assert o_alpha.status_code == 200
            alpha_stake = Decimal(o_alpha.json()["stake"])

            o_beta1 = await _post(
                "/v1/net/orders",
                body={"variableId": "gcx_a", "outcomeId": "yes", "target": 0.78},
                headers=_headers(beta_key),
            )
            assert o_beta1.status_code == 200
            o_beta2 = await _post(
                "/v1/net/orders",
                body={"variableId": "gcx_b", "outcomeId": "yes", "target": 0.80},
                headers=_headers(beta_key),
            )
            assert o_beta2.status_code == 200
            beta_stake = Decimal(o_beta1.json()["stake"]) + Decimal(o_beta2.json()["stake"])
            assert beta_stake > alpha_stake > Decimal("0")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                lb_resp = await c.get("/v1/leaderboard")
            assert lb_resp.status_code == 200
            entries = lb_resp.json()["entries"]

            ids = [e["accountId"] for e in entries]
            assert bot_acc_id not in ids
            assert app.state.joint.treasury_account_id not in ids

            # All 4 visible accounts tie at total=1000, so ranking is:
            # netVolume desc (beta > alpha > gh1 == gh2), then accountId asc (gh1 < gh2)
            assert ids == [beta_acc_id, alpha_acc_id, gh1_acc_id, gh2_acc_id]

            by_id = {e["accountId"]: e for e in entries}
            assert by_id[beta_acc_id]["login"] == "guest_beta"
            assert by_id[beta_acc_id]["displayName"] == "Guest Beta"
            assert by_id[beta_acc_id]["netOrders"] == 2
            assert Decimal(by_id[beta_acc_id]["netVolume"]) == beta_stake

            assert by_id[alpha_acc_id]["login"] == "guest_alpha"
            assert by_id[alpha_acc_id]["displayName"] == "Guest Alpha"
            assert by_id[alpha_acc_id]["netOrders"] == 1
            assert Decimal(by_id[alpha_acc_id]["netVolume"]) == alpha_stake

            assert by_id[gh1_acc_id]["login"] == "gh_one"
            assert by_id[gh1_acc_id]["displayName"] is None
            assert by_id[gh1_acc_id]["netOrders"] == 0
            assert by_id[gh1_acc_id]["netVolume"] == "0"

    def test_legacy_snapshot_without_display_name_defaults_to_none(self):
        from exchange.core.persistence import _load_auth

        store = _load_auth({
            "users": [{
                "github_id": 42,
                "github_login": "octo",
                "account_id": 1,
                "api_key_hash": "a" * 64,
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
            }],
            "local_users": [{
                "username": "legacy_local",
                "account_id": 2,
                "api_key_hash": "b" * 64,
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
            }],
        })
        assert store.users[42].display_name is None
        assert store.local_users["legacy_local"].display_name is None
