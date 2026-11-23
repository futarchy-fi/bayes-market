"""
API tests. Uses httpx AsyncClient with FastAPI's TestClient transport.

Covers:
- Auth round-trip (GitHub token exchange via mock)
- Public market data (no auth)
- Full trading lifecycle via HTTP
- Auth boundaries (no key, wrong key, admin key on user endpoints)
- Admin operations
- Rate limiting
- Dashboard route integrity (static files and API path alignment)
"""

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Set admin key before importing app
os.environ["FUTARCHY_ADMIN_KEY"] = "test-admin-key"
os.environ["FUTARCHY_STATE"] = "/tmp/futarchy_test_state.json"
os.environ["INITIAL_CREDITS"] = "1000"

from exchange.core.api import app, _authenticate_github_identity, _candles
from exchange.core.auth import AuthStore
from exchange.core.middleware import rate_limiter, RateLimiter
from exchange.core.models import reset_counters
from exchange.core.risk_engine import RiskEngine
from exchange.core.market_engine import MarketEngine


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-key"}


@pytest.fixture
async def client():
    """Fresh app state for each test."""
    # Reset state
    reset_counters()
    app.state.risk = RiskEngine()
    app.state.me = MarketEngine(app.state.risk)
    app.state.auth_store = AuthStore()
    app.state.tracked_repos = {}
    app.state.github_oauth_states = {}
    app.state.lock = asyncio.Lock()
    app.state.joint = None
    app.state.venues = {}

    # Reset rate limiter
    rate_limiter.buckets.clear()

    # Remove state file if exists
    try:
        os.remove("/tmp/futarchy_test_state.json")
    except FileNotFoundError:
        pass

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _mock_auth(client: AsyncClient, github_id=1,
                     login="testuser") -> str:
    """Helper: create a user and return the API key."""
    auth = await _authenticate_github_identity({
        "id": github_id,
        "login": login,
    })
    return auth.api_key


def _user_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["markets"] == 0
        assert data["ledger_accounts"] == 0
        assert data["users"] == 0

    async def test_health_separates_ledger_accounts_from_users(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Will it rain?",
                                       "category": "weather",
                                       "category_id": "weather#1"})
        assert resp.status_code == 200

        await _mock_auth(client, github_id=1, login="alice")

        resp = await client.post("/v1/admin/service-accounts",
                                 headers=ADMIN_HEADERS,
                                 json={"username": "local-user"})
        assert resp.status_code == 200

        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["markets"] == 1
        assert data["ledger_accounts"] == 3
        assert data["users"] == 2


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    async def test_github_auth_creates_account(self, client):
        key = await _mock_auth(client, github_id=42, login="octocat")
        assert len(key) > 20

        # Can use the key
        resp = await client.get("/v1/me", headers=_user_headers(key))
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] == "1000"

    async def test_reauth_rotates_key(self, client):
        key1 = await _mock_auth(client, github_id=42, login="octocat")
        key2 = await _mock_auth(client, github_id=42, login="octocat")
        assert key1 != key2

        # Old key is invalid
        resp = await client.get("/v1/me", headers=_user_headers(key1))
        assert resp.status_code == 401

        # New key works
        resp = await client.get("/v1/me", headers=_user_headers(key2))
        assert resp.status_code == 200

    async def test_same_github_id_same_account(self, client):
        key1 = await _mock_auth(client, github_id=42, login="octocat")
        resp1 = await client.get("/v1/me", headers=_user_headers(key1))
        acct1 = resp1.json()["account_id"]

        key2 = await _mock_auth(client, github_id=42, login="octocat2")
        resp2 = await client.get("/v1/me", headers=_user_headers(key2))
        acct2 = resp2.json()["account_id"]

        assert acct1 == acct2

    async def test_different_github_id_different_account(self, client):
        key1 = await _mock_auth(client, github_id=1, login="alice")
        key2 = await _mock_auth(client, github_id=2, login="bob")

        resp1 = await client.get("/v1/me", headers=_user_headers(key1))
        resp2 = await client.get("/v1/me", headers=_user_headers(key2))

        assert resp1.json()["account_id"] != resp2.json()["account_id"]

    async def test_token_exchange_endpoint_removed(self, client):
        resp = await client.post("/v1/auth/github",
                                 json={"github_token": "bad"})
        assert resp.status_code == 404

    async def test_device_flow_start_requires_client_id(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", ""):
            resp = await client.post("/v1/auth/device", json={})
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "device_flow_unavailable"

    async def test_device_flow_start_returns_user_code(self, client):
        mock = AsyncMock(return_value={
            "device_code": "device-123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        })
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.start_device_flow", mock):
            resp = await client.post("/v1/auth/device", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_code"] == "ABCD-EFGH"
        assert data["verification_uri"] == "https://github.com/login/device"

    async def test_device_flow_poll_pending(self, client):
        mock = AsyncMock(side_effect=ValueError("device_flow_pending"))
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.poll_device_flow", mock):
            resp = await client.post("/v1/auth/device/token",
                                     json={"device_code": "device-123"})
        assert resp.status_code == 202
        assert resp.json()["error"]["code"] == "device_flow_pending"

    async def test_device_flow_poll_creates_account(self, client):
        poll_mock = AsyncMock(return_value={"access_token": "gho_token"})
        validate_mock = AsyncMock(return_value={"id": 77, "login": "octocat"})
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.poll_device_flow", poll_mock), \
                patch("exchange.core.api.validate_github_token", validate_mock):
            resp = await client.post("/v1/auth/device/token",
                                     json={"device_code": "device-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_login"] == "octocat"

        me = await client.get("/v1/me", headers=_user_headers(data["api_key"]))
        assert me.status_code == 200
        assert me.json()["available"] == "1000"

    async def test_oauth_web_login_redirects_to_github(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"):
            resp = await client.get("/v1/auth/github/login",
                                    follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        parsed = urlparse(location)
        query = parse_qs(parsed.query)

        assert location.startswith("https://github.com/login/oauth/authorize?")
        assert query["client_id"] == ["client-id"]
        assert query["redirect_uri"] == [
            "https://api.futarchy.ai/v1/auth/callback"
        ]
        assert "scope" not in query
        assert len(query["state"][0]) > 20
        assert query["state"][0] in app.state.github_oauth_states

    async def test_oauth_web_login_accepts_select_account_prompt(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"):
            resp = await client.get("/v1/auth/github/login",
                                    params={"prompt": "select_account"},
                                    follow_redirects=False)
        assert resp.status_code == 302
        parsed = urlparse(resp.headers["location"])
        query = parse_qs(parsed.query)
        assert query["prompt"] == ["select_account"]

    async def test_oauth_web_login_rejects_unknown_prompt(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"):
            resp = await client.get("/v1/auth/github/login",
                                    params={"prompt": "consent"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "github_oauth_invalid_prompt"

    async def test_oauth_callback_rejects_invalid_state(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "client-secret"):
            resp = await client.get("/v1/auth/callback",
                                    params={"code": "oauth-code",
                                            "state": "bad-state"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "github_oauth_invalid_state"

    async def test_oauth_callback_creates_account_and_redirects(self, client):
        exchange_mock = AsyncMock(return_value="gho_token")
        validate_mock = AsyncMock(return_value={"id": 88, "login": "octocat"})

        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "client-secret"), \
                patch("exchange.core.api._exchange_github_oauth_code", exchange_mock), \
                patch("exchange.core.api.validate_github_token", validate_mock):
            login_resp = await client.get("/v1/auth/github/login",
                                          follow_redirects=False)
            assert login_resp.status_code == 302
            state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
            assert login_resp.cookies.get("futarchy_oauth_state") == state

            resp = await client.get("/v1/auth/callback",
                                    params={"code": "oauth-code",
                                            "state": state},
                                    follow_redirects=False)

        assert resp.status_code == 302
        location = resp.headers["location"]
        parsed = urlparse(location)
        fragment = parse_qs(parsed.fragment)

        assert parsed.scheme == "https"
        assert parsed.netloc == "futarchy.ai"
        assert parsed.path == "/exchange/callback"
        assert fragment["account_id"] == ["1"]
        assert fragment["login"] == ["octocat"]
        assert "auth" in fragment
        assert state not in app.state.github_oauth_states
        # Cookie cleared on callback
        set_cookie = resp.headers.get("set-cookie", "").lower()
        assert "futarchy_oauth_state=" in set_cookie
        assert "max-age=0" in set_cookie

        me = await client.get("/v1/me",
                              headers=_user_headers(fragment["auth"][0]))
        assert me.status_code == 200
        assert me.json()["available"] == "1000"

    async def test_oauth_login_sets_cookie_attributes_for_http_and_https(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"):
            http_resp = await client.get("/v1/auth/github/login",
                                         follow_redirects=False)
            https_resp = await client.get(
                "/v1/auth/github/login",
                headers={"X-Forwarded-Proto": "https"},
                follow_redirects=False,
            )

        http_cookie = http_resp.headers.get("set-cookie", "")
        assert "futarchy_oauth_state=" in http_cookie
        assert "HttpOnly" in http_cookie
        assert "SameSite=lax" in http_cookie
        assert "Max-Age=600" in http_cookie
        assert "; Secure" not in http_cookie

        https_cookie = https_resp.headers.get("set-cookie", "")
        assert "futarchy_oauth_state=" in https_cookie
        assert "HttpOnly" in https_cookie
        assert "SameSite=lax" in https_cookie
        assert "Max-Age=600" in https_cookie
        assert "Secure" in https_cookie

    async def test_oauth_callback_rejects_missing_or_mismatched_cookie(self, client):
        app.state.github_oauth_states["valid-state"] = datetime.now(timezone.utc)
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "client-secret"):
            # Missing cookie -> rejected without burning valid server state
            no_cookie = await client.get(
                "/v1/auth/callback",
                params={"code": "oauth-code", "state": "valid-state"},
                follow_redirects=False,
            )
            assert no_cookie.status_code == 400
            assert no_cookie.json()["error"]["code"] == "github_oauth_invalid_state"
            assert "valid-state" in app.state.github_oauth_states

            # Mismatched cookie -> rejected and cookie cleared
            bad_cookie = await client.get(
                "/v1/auth/callback",
                params={"code": "oauth-code", "state": "valid-state"},
                headers={"Cookie": "futarchy_oauth_state=wrong-state"},
                follow_redirects=False,
            )
            assert bad_cookie.status_code == 400
            assert bad_cookie.json()["error"]["code"] == "github_oauth_invalid_state"
            assert "max-age=0" in bad_cookie.headers.get("set-cookie", "").lower()

    async def test_oauth_callback_browser_error_redirects(self, client):
        with patch("exchange.core.api.GITHUB_CLIENT_ID", "client-id"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "client-secret"):
            # User clicked Cancel on GitHub -> ?error=access_denied always redirects
            denied = await client.get(
                "/v1/auth/callback",
                params={"error": "access_denied"},
                follow_redirects=False,
            )
            assert denied.status_code == 302
            parsed = urlparse(denied.headers["location"])
            assert parsed.netloc == "futarchy.ai"
            assert parsed.path == "/exchange/callback"
            assert parse_qs(parsed.fragment)["error"] == ["access_denied"]
            assert "max-age=0" in denied.headers.get("set-cookie", "").lower()

            # Browser hitting callback with invalid state -> friendly redirect
            bad_state = await client.get(
                "/v1/auth/callback",
                params={"code": "oauth-code", "state": "bad-state"},
                headers={"Accept": "text/html,application/xhtml+xml"},
                follow_redirects=False,
            )
            assert bad_state.status_code == 302
            assert parse_qs(urlparse(bad_state.headers["location"]).fragment)["error"] == [
                "github_oauth_invalid_state"
            ]

    async def test_oauth_callback_handles_httpx_errors_and_sends_redirect_uri(self, client):
        import httpx
        from exchange.core.api import _exchange_github_oauth_code
        from exchange.core.auth import validate_github_token

        # Verify RFC 6749 §4.1.3 redirect_uri is included in code exchange POST
        captured = {}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, data=None, headers=None, timeout=None):
                captured["url"] = url
                captured["data"] = data
                return httpx.Response(200, json={"access_token": "gho_abc"})

            async def get(self, url, headers=None, timeout=None):
                raise httpx.ConnectTimeout("timed out")

        with patch("exchange.core.api.GITHUB_CLIENT_ID", "cid"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "csec"), \
                patch("exchange.core.api.GITHUB_OAUTH_REDIRECT_URI", "https://api.futarchy.ai/v1/auth/callback"), \
                patch("exchange.core.api.httpx.AsyncClient", return_value=_FakeClient()):
            token = await _exchange_github_oauth_code("code-123")
            assert token == "gho_abc"
            assert captured["data"]["redirect_uri"] == "https://api.futarchy.ai/v1/auth/callback"

        with patch("exchange.core.auth.httpx.AsyncClient", return_value=_FakeClient()):
            with pytest.raises(ValueError, match="github_http_error:ConnectTimeout"):
                await validate_github_token("gho_abc")

        # Callback converts httpx.HTTPError to 502 JSON or browser error redirect
        app.state.github_oauth_states["s-api"] = datetime.now(timezone.utc)
        app.state.github_oauth_states["s-html"] = datetime.now(timezone.utc)
        failing_exchange = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))

        with patch("exchange.core.api.GITHUB_CLIENT_ID", "cid"), \
                patch("exchange.core.api.GITHUB_CLIENT_SECRET", "csec"), \
                patch("exchange.core.api._exchange_github_oauth_code", failing_exchange):
            api_resp = await client.get(
                "/v1/auth/callback",
                params={"code": "c", "state": "s-api"},
                headers={"Cookie": "futarchy_oauth_state=s-api"},
                follow_redirects=False,
            )
            assert api_resp.status_code == 502
            assert api_resp.json()["error"]["code"] == "github_api_error"

            html_resp = await client.get(
                "/v1/auth/callback",
                params={"code": "c", "state": "s-html"},
                headers={
                    "Cookie": "futarchy_oauth_state=s-html",
                    "Accept": "text/html",
                },
                follow_redirects=False,
            )
            assert html_resp.status_code == 302
            assert parse_qs(urlparse(html_resp.headers["location"]).fragment)["error"] == [
                "github_api_error"
            ]

    async def test_auth_logout_revokes_key_immediately_and_survives_reload(self, client, tmp_path):
        import exchange.core.api as api_module
        from exchange.core.persistence import load_snapshot

        state_path = tmp_path / "logout_state.json"
        original_state_path = api_module.STATE_PATH
        api_module.STATE_PATH = str(state_path)
        try:
            key = await _mock_auth(client, github_id=77, login="logout-user")
            me_before = await client.get("/v1/me", headers=_user_headers(key))
            assert me_before.status_code == 200
            account_id = me_before.json()["account_id"]

            logout = await client.post("/v1/auth/logout", headers=_user_headers(key))
            assert logout.status_code == 200
            assert logout.json() == {"status": "logged_out"}

            # Old key is immediately rejected
            me_after = await client.get("/v1/me", headers=_user_headers(key))
            assert me_after.status_code == 401
            assert me_after.json()["error"]["code"] == "invalid_api_key"

            # Persisted snapshot keeps old key invalid
            _, _, reloaded_auth, _, _, _ = load_snapshot(str(state_path))
            assert reloaded_auth.authenticate(key) is None

            # Re-authenticating same GitHub user preserves account and issues new key
            new_key = await _mock_auth(client, github_id=77, login="logout-user")
            assert new_key != key
            me_reauth = await client.get("/v1/me", headers=_user_headers(new_key))
            assert me_reauth.status_code == 200
            assert me_reauth.json()["account_id"] == account_id
        finally:
            api_module.STATE_PATH = original_state_path

    async def test_admin_named_trader_account_and_display_name_persistence(self, client, tmp_path):
        import exchange.core.api as api_module
        from exchange.core.persistence import load_snapshot

        state_path = tmp_path / "named_trader_state.json"
        original_state_path = api_module.STATE_PATH
        api_module.STATE_PATH = str(state_path)
        try:
            resp = await client.post(
                "/v1/admin/service-accounts",
                headers=ADMIN_HEADERS,
                json={
                    "username": "dwarkesh_guest",
                    "display_name": "Dwarkesh Guest",
                    "is_service_account": False,
                    "initial_credits": "1000",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["username"] == "dwarkesh_guest"
            assert body["display_name"] == "Dwarkesh Guest"
            assert body["is_service_account"] is False
            old_key = body["api_key"]
            account_id = body["account_id"]

            # Duplicate without rotate_if_exists still returns 409
            dup = await client.post(
                "/v1/admin/service-accounts",
                headers=ADMIN_HEADERS,
                json={"username": "dwarkesh_guest", "initial_credits": "1000"},
            )
            assert dup.status_code == 409
            assert dup.json()["error"]["code"] == "username_taken"

            # Duplicate with rotate_if_exists rotates key without double-minting
            rot = await client.post(
                "/v1/admin/service-accounts",
                headers=ADMIN_HEADERS,
                json={
                    "username": "dwarkesh_guest",
                    "display_name": "Dwarkesh Guest Updated",
                    "is_service_account": False,
                    "initial_credits": "1000",
                    "rotate_if_exists": True,
                },
            )
            assert rot.status_code == 200
            new_key = rot.json()["api_key"]
            assert rot.json()["account_id"] == account_id
            assert new_key != old_key
            assert (await client.get("/v1/me", headers=_user_headers(old_key))).status_code == 401
            me = await client.get("/v1/me", headers=_user_headers(new_key))
            assert me.status_code == 200
            assert me.json()["available"] == "1000"

            # Snapshot persistence preserves display_name
            _, _, reloaded_auth, _, _, _ = load_snapshot(str(state_path))
            loaded = reloaded_auth.local_users["dwarkesh_guest"]
            assert loaded.display_name == "Dwarkesh Guest Updated"
            assert loaded.is_service_account is False
        finally:
            api_module.STATE_PATH = original_state_path

    async def test_register_endpoint_removed(self, client):
        resp = await client.post("/v1/auth/register", json={"username": "alice"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth Boundaries
# ---------------------------------------------------------------------------

class TestAuthBoundaries:
    async def test_no_auth_on_protected(self, client):
        resp = await client.get("/v1/me")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth_required"

        resp = await client.get("/v1/me/activity")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth_required"

    async def test_bad_key(self, client):
        resp = await client.get("/v1/me",
                                headers={"Authorization": "Bearer bad-key"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_api_key"

    async def test_admin_key_rejected_on_user_endpoint(self, client):
        resp = await client.get("/v1/me", headers=ADMIN_HEADERS)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_api_key"

    async def test_user_key_rejected_on_admin_endpoint(self, client):
        key = await _mock_auth(client)
        resp = await client.post("/v1/admin/markets",
                                 headers=_user_headers(key),
                                 json={"question": "Test?",
                                       "category": "t", "category_id": "t#1"})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "admin_required"

    async def test_public_endpoints_no_auth(self, client):
        # All these should work without auth
        resp = await client.get("/v1/health")
        assert resp.status_code == 200

        resp = await client.get("/v1/markets")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Account Activity
# ---------------------------------------------------------------------------

class TestAccountActivity:
    async def test_activity_shows_void_refunds_and_resolved_losses(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Void me?", "category": "t",
                                       "category_id": "t#void"})
        assert resp.status_code == 200
        void_mid = resp.json()["market_id"]

        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Lose me?", "category": "t",
                                       "category_id": "t#loss"})
        assert resp.status_code == 200
        loss_mid = resp.json()["market_id"]

        key = await _mock_auth(client, github_id=35, login="trader35")
        headers = _user_headers(key)

        resp = await client.post(f"/v1/markets/{void_mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "50"})
        assert resp.status_code == 200

        resp = await client.post(f"/v1/admin/markets/{void_mid}/void",
                                 headers=ADMIN_HEADERS)
        assert resp.status_code == 200

        resp = await client.post(f"/v1/markets/{loss_mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "30"})
        assert resp.status_code == 200

        resp = await client.post(f"/v1/admin/markets/{loss_mid}/resolve",
                                 headers=ADMIN_HEADERS,
                                 json={"outcome": "no"})
        assert resp.status_code == 200

        resp = await client.get("/v1/me/activity", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        activity = payload["entries"]
        assert payload["has_more"] is False
        assert payload["next_before_tx_id"] is None
        assert len(activity) >= 5

        assert activity[0]["market_id"] == loss_mid
        assert activity[0]["summary"] == "Resolved market loss"
        assert Decimal(activity[0]["total_delta"]) < 0
        assert Decimal(activity[0]["total_after"]) < Decimal("1000")

        void_entry = next(
            entry for entry in activity
            if entry["market_id"] == void_mid and "Void" in entry["summary"]
        )
        assert void_entry["market_status"] == "void"
        assert Decimal(void_entry["available_after"]) == Decimal("1000")
        assert Decimal(void_entry["frozen_after"]) == Decimal("0")

        buy_entry = next(
            entry for entry in activity
            if entry["market_id"] == loss_mid and entry["reason"] == "lock:position:yes"
        )
        assert buy_entry["summary"] == "Bought YES"
        assert buy_entry["outcome"] == "yes"
        assert Decimal(buy_entry["available_delta"]) < 0
        assert Decimal(buy_entry["frozen_delta"]) > 0
        assert Decimal(buy_entry["total_delta"]) == Decimal("0")

    async def test_activity_paginates_with_before_tx_id_cursor(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Paginate?", "category": "t",
                                       "category_id": "t#page"})
        assert resp.status_code == 200
        mid = resp.json()["market_id"]

        key = await _mock_auth(client, github_id=55, login="pager")
        headers = _user_headers(key)

        for _ in range(3):
            resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                     json={"outcome": "yes", "budget": "10"})
            assert resp.status_code == 200

        resp = await client.get("/v1/me/activity", headers=headers,
                                params={"limit": 2})
        assert resp.status_code == 200
        first_page = resp.json()

        assert len(first_page["entries"]) == 2
        assert first_page["has_more"] is True
        assert first_page["next_before_tx_id"] == first_page["entries"][-1]["tx_id"]
        assert first_page["entries"][0]["tx_id"] > first_page["entries"][1]["tx_id"]

        resp = await client.get("/v1/me/activity", headers=headers,
                                params={"limit": 2,
                                        "before_tx_id": first_page["next_before_tx_id"]})
        assert resp.status_code == 200
        second_page = resp.json()

        assert len(second_page["entries"]) == 2
        assert second_page["entries"][0]["tx_id"] < first_page["entries"][-1]["tx_id"]
        assert second_page["entries"][0]["tx_id"] > second_page["entries"][1]["tx_id"]
        assert second_page["has_more"] is False
        assert second_page["next_before_tx_id"] is None

# ---------------------------------------------------------------------------
# Public Market Data
# ---------------------------------------------------------------------------

def test_candles_aggregate_fabricated_trade_sequence():
    tape = [
        ("2026-07-13T10:45:00Z", Decimal("0.60"), Decimal("2")),
        ("2026-07-13T10:05:00Z", Decimal("0.40"), Decimal("1")),
        ("2026-07-13T10:30:00Z", Decimal("0.70"), Decimal("3")),
        ("2026-07-13T11:00:00Z", Decimal("0.50"), Decimal("4")),
    ]

    hourly = [candle.model_dump() for candle in _candles(tape, "hour")]
    daily = [candle.model_dump() for candle in _candles(tape, "day")]

    assert hourly == [
        {"t": 1783936800, "o": 0.4, "h": 0.7, "l": 0.4, "c": 0.6, "v": 6.0},
        {"t": 1783940400, "o": 0.5, "h": 0.5, "l": 0.5, "c": 0.5, "v": 4.0},
    ]
    assert daily == [
        {"t": 1783900800, "o": 0.4, "h": 0.7, "l": 0.4, "c": 0.5, "v": 10.0}
    ]


class TestPublicMarketData:
    async def _create_market(self, client):
        """Admin creates a market, returns market_id."""
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Will it rain?",
                                       "category": "weather",
                                       "category_id": "weather#1"})
        assert resp.status_code == 200
        return resp.json()["market_id"]

    async def test_list_markets_public(self, client):
        mid = await self._create_market(client)
        resp = await client.get("/v1/markets")
        assert resp.status_code == 200
        markets = resp.json()
        assert len(markets) == 1
        assert markets[0]["market_id"] == mid
        assert markets[0]["question"] == "Will it rain?"
        assert "yes" in markets[0]["prices"]
        assert "no" in markets[0]["prices"]

    async def test_market_detail_public(self, client):
        mid = await self._create_market(client)
        resp = await client.get(f"/v1/markets/{mid}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["market_id"] == mid
        assert detail["status"] == "open"
        assert "q" in detail
        assert "volume" in detail
        assert detail["amm_account_id"] > 0

    async def test_market_not_found(self, client):
        resp = await client.get("/v1/markets/999")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "market_not_found"

    async def test_positions_public(self, client):
        mid = await self._create_market(client)
        resp = await client.get(f"/v1/markets/{mid}/positions")
        assert resp.status_code == 200
        assert resp.json() == []  # No traders yet

    async def test_trades_public(self, client):
        mid = await self._create_market(client)
        resp = await client.get(f"/v1/markets/{mid}/trades")
        assert resp.status_code == 200
        assert resp.json() == []  # No trades yet

    async def test_candles_empty_without_trades(self, client):
        mid = await self._create_market(client)
        resp = await client.get(f"/v1/markets/{mid}/candles?interval=day")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_markets_filter_by_category(self, client):
        await self._create_market(client)
        # Create a second market with different category
        await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                          json={"question": "Will PR merge?",
                                "category": "pr_merge",
                                "category_id": "repo#1@2026-02-24"})

        # Filter by category
        resp = await client.get("/v1/markets", params={"category": "pr_merge"})
        assert resp.status_code == 200
        markets = resp.json()
        assert len(markets) == 1
        assert markets[0]["category"] == "pr_merge"

        # Filter by non-existent category
        resp = await client.get("/v1/markets", params={"category": "nope"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_markets_filter_by_category_id_prefix(self, client):
        # Create two markets with same PR but different dates
        await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                          json={"question": "Merge today?",
                                "category": "pr_merge",
                                "category_id": "repo#7@2026-02-24"})
        await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                          json={"question": "Merge tomorrow?",
                                "category": "pr_merge",
                                "category_id": "repo#7@2026-02-25"})
        await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                          json={"question": "Other PR?",
                                "category": "pr_merge",
                                "category_id": "repo#8@2026-02-24"})

        # Prefix match: all markets for PR #7
        resp = await client.get("/v1/markets",
                                params={"category_id": "repo#7"})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # Exact match
        resp = await client.get("/v1/markets",
                                params={"category_id": "repo#7@2026-02-24"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_markets_filter_by_status(self, client):
        mid = await self._create_market(client)

        # All open
        resp = await client.get("/v1/markets", params={"status": "open"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # None resolved yet
        resp = await client.get("/v1/markets", params={"status": "resolved"})
        assert resp.status_code == 200
        assert resp.json() == []

        # Resolve the market
        await client.post(f"/v1/admin/markets/{mid}/resolve",
                          headers=ADMIN_HEADERS,
                          json={"outcome": "yes"})

        # Now resolved
        resp = await client.get("/v1/markets", params={"status": "resolved"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # No open markets
        resp = await client.get("/v1/markets", params={"status": "open"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_markets_combined_filters(self, client):
        await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                          json={"question": "PR?", "category": "pr_merge",
                                "category_id": "repo#1@2026-02-24"})
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Other?",
                                        "category": "pr_merge",
                                        "category_id": "repo#2@2026-02-24"})
        mid2 = resp.json()["market_id"]

        # Resolve one
        await client.post(f"/v1/admin/markets/{mid2}/resolve",
                          headers=ADMIN_HEADERS,
                          json={"outcome": "no"})

        # Combined: pr_merge + open
        resp = await client.get("/v1/markets",
                                params={"category": "pr_merge",
                                        "status": "open"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["category_id"] == "repo#1@2026-02-24"

    async def test_positions_show_after_trade(self, client):
        mid = await self._create_market(client)
        key = await _mock_auth(client)
        headers = _user_headers(key)

        # Buy
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "50"})
        assert resp.status_code == 200

        # Check positions (public, no auth)
        resp = await client.get(f"/v1/markets/{mid}/positions")
        assert resp.status_code == 200
        positions = resp.json()
        assert len(positions) == 1
        assert Decimal(positions[0]["positions"]["yes"]) > 0

    async def test_trades_show_after_trade(self, client):
        mid = await self._create_market(client)
        key = await _mock_auth(client)
        headers = _user_headers(key)

        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "50"})
        assert resp.status_code == 200

        resp = await client.get(f"/v1/markets/{mid}/trades")
        assert resp.status_code == 200
        trades = resp.json()
        assert len(trades) == 1
        assert trades[0]["outcome"] == "yes"
        assert Decimal(trades[0]["value"]) > 0


# ---------------------------------------------------------------------------
# Full Trading Lifecycle
# ---------------------------------------------------------------------------

class TestTradingLifecycle:
    async def test_buy_sell_resolve(self, client):
        # Admin creates market
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Test?", "category": "t",
                                       "category_id": "t#1"})
        assert resp.status_code == 200
        mid = resp.json()["market_id"]

        # User signs up
        key = await _mock_auth(client)
        headers = _user_headers(key)

        # Check balance
        resp = await client.get("/v1/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["available"] == "1000"

        # Buy YES
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "100"})
        assert resp.status_code == 200
        trade = resp.json()
        assert trade["outcome"] == "yes"
        tokens = Decimal(trade["amount"])
        assert tokens > 0

        # Check balance decreased
        resp = await client.get("/v1/me", headers=headers)
        data = resp.json()
        assert Decimal(data["available"]) < Decimal("1000")
        assert Decimal(data["frozen"]) > 0

        # Sell half
        sell_amount = str(tokens / 2)
        resp = await client.post(f"/v1/markets/{mid}/sell", headers=headers,
                                 json={"outcome": "yes",
                                       "amount": sell_amount})
        assert resp.status_code == 200

        # Resolve YES
        resp = await client.post(f"/v1/admin/markets/{mid}/resolve",
                                 headers=ADMIN_HEADERS,
                                 json={"outcome": "yes"})
        assert resp.status_code == 200

        # Check market resolved
        resp = await client.get(f"/v1/markets/{mid}")
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolution"] == "yes"

        # User balance should have no frozen (all settled)
        resp = await client.get("/v1/me", headers=headers)
        data = resp.json()
        assert Decimal(data["frozen"]) == 0

    async def test_void_market(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Void?", "category": "t",
                                       "category_id": "t#2"})
        mid = resp.json()["market_id"]

        key = await _mock_auth(client)
        headers = _user_headers(key)

        # Buy
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "50"})
        assert resp.status_code == 200

        # Void
        resp = await client.post(f"/v1/admin/markets/{mid}/void",
                                 headers=ADMIN_HEADERS)
        assert resp.status_code == 200

        # Market voided
        resp = await client.get(f"/v1/markets/{mid}")
        assert resp.json()["status"] == "void"

    async def test_two_users_trading(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Race?", "category": "t",
                                       "category_id": "t#3"})
        mid = resp.json()["market_id"]

        key1 = await _mock_auth(client, github_id=1, login="alice")
        key2 = await _mock_auth(client, github_id=2, login="bob")

        # Alice buys YES
        resp = await client.post(f"/v1/markets/{mid}/buy",
                                 headers=_user_headers(key1),
                                 json={"outcome": "yes", "budget": "100"})
        assert resp.status_code == 200

        # Bob buys NO
        resp = await client.post(f"/v1/markets/{mid}/buy",
                                 headers=_user_headers(key2),
                                 json={"outcome": "no", "budget": "100"})
        assert resp.status_code == 200

        # Public positions shows both
        resp = await client.get(f"/v1/markets/{mid}/positions")
        assert len(resp.json()) == 2

        # Public trades shows both
        resp = await client.get(f"/v1/markets/{mid}/trades")
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# Trading Errors
# ---------------------------------------------------------------------------

class TestTradingErrors:
    async def _setup(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "?", "category": "t",
                                       "category_id": "t#e"})
        mid = resp.json()["market_id"]
        key = await _mock_auth(client)
        return mid, _user_headers(key)

    async def test_buy_insufficient_balance(self, client):
        mid, headers = await self._setup(client)
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "99999"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "insufficient_balance"

    async def test_buy_invalid_outcome(self, client):
        mid, headers = await self._setup(client)
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "maybe", "budget": "10"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_outcome"

    async def test_buy_market_not_found(self, client):
        key = await _mock_auth(client)
        resp = await client.post("/v1/markets/999/buy",
                                 headers=_user_headers(key),
                                 json={"outcome": "yes", "budget": "10"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "market_not_found"

    async def test_sell_more_than_held(self, client):
        mid, headers = await self._setup(client)
        # Buy some first
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "10"})
        amount = resp.json()["amount"]

        # Try to sell more
        resp = await client.post(f"/v1/markets/{mid}/sell", headers=headers,
                                 json={"outcome": "yes",
                                       "amount": str(Decimal(amount) * 2)})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_amount"

    async def test_buy_on_resolved_market(self, client):
        mid, headers = await self._setup(client)
        # Resolve it
        await client.post(f"/v1/admin/markets/{mid}/resolve",
                          headers=ADMIN_HEADERS,
                          json={"outcome": "yes"})
        # Try to buy
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "10"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "market_closed"

    async def test_buy_negative_budget(self, client):
        mid, headers = await self._setup(client)
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "-10"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_amount"

    async def test_buy_invalid_budget(self, client):
        mid, headers = await self._setup(client)
        resp = await client.post(f"/v1/markets/{mid}/buy", headers=headers,
                                 json={"outcome": "yes", "budget": "abc"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class TestAdmin:
    async def test_mint(self, client):
        key = await _mock_auth(client)
        me_resp = await client.get("/v1/me", headers=_user_headers(key))
        acct_id = me_resp.json()["account_id"]

        resp = await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                                 json={"account_id": acct_id, "amount": "500"})
        assert resp.status_code == 200
        assert resp.json()["available"] == "1500"

    async def test_create_market_custom_b(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Q?", "category": "t",
                                       "category_id": "t#c", "b": "50"})
        assert resp.status_code == 200
        assert resp.json()["b"] == "50"

    async def test_create_market_with_funding(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Fund?", "category": "t",
                                        "category_id": "t#f", "funding": "200"})
        assert resp.status_code == 200
        data = resp.json()
        # b should be funding / ln(2) ≈ 288.54
        b_val = Decimal(data["b"])
        assert b_val > Decimal("288") and b_val < Decimal("289")

    async def test_create_market_funding_and_b_rejected(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "?", "category": "t",
                                        "category_id": "t#x",
                                        "b": "100", "funding": "200"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_request"

    async def test_add_liquidity(self, client):
        # Create market
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Liq?", "category": "t",
                                        "category_id": "t#liq",
                                        "funding": "40"})
        assert resp.status_code == 200
        mid = resp.json()["market_id"]
        amm_id = resp.json()["amm_account_id"]
        b_before = Decimal(resp.json()["b"])

        # Mint extra to AMM
        resp = await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                                  json={"account_id": amm_id, "amount": "160"})
        assert resp.status_code == 200

        # Add liquidity
        resp = await client.post(f"/v1/admin/markets/{mid}/add-liquidity",
                                  headers=ADMIN_HEADERS,
                                  json={"amount": "40"})
        assert resp.status_code == 200
        b_after = Decimal(resp.json()["b"])
        assert b_after > b_before
        assert resp.json()["funding_added"] == "40"

        # Prices should still sum to ~1
        resp = await client.get(f"/v1/markets/{mid}")
        prices = resp.json()["prices"]
        total = sum(Decimal(v) for v in prices.values())
        assert abs(total - 1) < Decimal("0.01")

    async def test_add_liquidity_insufficient_balance(self, client):
        # Create market — AMM has no extra available
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "?", "category": "t",
                                        "category_id": "t#liq2",
                                        "funding": "40"})
        mid = resp.json()["market_id"]

        # Try to add liquidity without minting extra
        resp = await client.post(f"/v1/admin/markets/{mid}/add-liquidity",
                                  headers=ADMIN_HEADERS,
                                  json={"amount": "40"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "insufficient_balance"

    async def test_update_metadata(self, client):
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Meta?", "category": "t",
                                        "category_id": "t#meta"})
        mid = resp.json()["market_id"]

        # Update metadata
        resp = await client.patch(f"/v1/admin/markets/{mid}/metadata",
                                   headers=ADMIN_HEADERS,
                                   json={"metadata": {
                                       "liquidity_steps_remaining": 3,
                                       "next_liquidity_at": "2026-02-24T12:30:00Z",
                                   }})
        assert resp.status_code == 200
        assert resp.json()["metadata"]["liquidity_steps_remaining"] == 3

        # Verify via market detail
        resp = await client.get(f"/v1/markets/{mid}")
        assert resp.json()["metadata"]["liquidity_steps_remaining"] == 3

        # Merge update (existing keys preserved)
        resp = await client.patch(f"/v1/admin/markets/{mid}/metadata",
                                   headers=ADMIN_HEADERS,
                                   json={"metadata": {
                                       "liquidity_steps_remaining": 2,
                                   }})
        assert resp.status_code == 200
        # next_liquidity_at should still be there
        assert resp.json()["metadata"]["next_liquidity_at"] == "2026-02-24T12:30:00Z"
        assert resp.json()["metadata"]["liquidity_steps_remaining"] == 2

    async def test_create_account(self, client):
        resp = await client.post("/v1/admin/accounts", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert "account_id" in resp.json()
        assert resp.json()["account_id"] > 0

    async def test_create_market_with_treasury(self, client):
        """Create market funded from a treasury account instead of minting."""
        # Create treasury and mint to it
        resp = await client.post("/v1/admin/accounts", headers=ADMIN_HEADERS)
        treasury_id = resp.json()["account_id"]
        await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                          json={"account_id": treasury_id, "amount": "8000"})

        # Create market funded from treasury
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Treasury?", "category": "t",
                                        "category_id": "t#treasury",
                                        "funding": "200",
                                        "funding_account_id": treasury_id})
        assert resp.status_code == 200
        mid = resp.json()["market_id"]
        b_val = Decimal(resp.json()["b"])
        assert b_val > Decimal("288") and b_val < Decimal("289")

        # Treasury balance should have decreased
        treasury = app.state.risk.get_account(treasury_id)
        assert treasury.available_balance < Decimal("8000")

        # Market should be functional (buy works)
        key = await _mock_auth(client)
        resp = await client.post(f"/v1/markets/{mid}/buy",
                                  headers=_user_headers(key),
                                  json={"outcome": "yes", "budget": "10"})
        assert resp.status_code == 200

    async def test_add_liquidity_with_treasury(self, client):
        """Add liquidity funded from treasury (no need to mint to AMM)."""
        # Create treasury
        resp = await client.post("/v1/admin/accounts", headers=ADMIN_HEADERS)
        treasury_id = resp.json()["account_id"]
        await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                          json={"account_id": treasury_id, "amount": "8000"})

        # Create market from treasury with initial funding
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Ramp?", "category": "t",
                                        "category_id": "t#ramp",
                                        "funding": "40",
                                        "funding_account_id": treasury_id})
        assert resp.status_code == 200
        mid = resp.json()["market_id"]
        b_before = Decimal(resp.json()["b"])

        treasury_before = app.state.risk.get_account(treasury_id).available_balance

        # Add liquidity from treasury (no mint to AMM needed)
        resp = await client.post(f"/v1/admin/markets/{mid}/add-liquidity",
                                  headers=ADMIN_HEADERS,
                                  json={"amount": "40",
                                        "funding_account_id": treasury_id})
        assert resp.status_code == 200
        b_after = Decimal(resp.json()["b"])
        assert b_after > b_before

        # Treasury should have decreased by 40
        treasury_after = app.state.risk.get_account(treasury_id).available_balance
        assert treasury_before - treasury_after == Decimal("40")

    async def test_treasury_insufficient_balance(self, client):
        """Treasury with insufficient balance returns 400."""
        # Create treasury with small balance
        resp = await client.post("/v1/admin/accounts", headers=ADMIN_HEADERS)
        treasury_id = resp.json()["account_id"]
        await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                          json={"account_id": treasury_id, "amount": "10"})

        # Try to create market needing more than 10 credits
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                  json={"question": "Broke?", "category": "t",
                                        "category_id": "t#broke",
                                        "funding": "200",
                                        "funding_account_id": treasury_id})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "insufficient_balance"

    async def test_no_admin_key_configured(self, client):
        # Temporarily clear admin key
        import exchange.core.middleware
        old = exchange.core.middleware.ADMIN_KEY
        exchange.core.middleware.ADMIN_KEY = ""
        try:
            resp = await client.post("/v1/admin/markets",
                                     headers={"Authorization": "Bearer x"},
                                     json={"question": "?", "category": "t",
                                           "category_id": "t#x"})
            assert resp.status_code == 500
        finally:
            exchange.core.middleware.ADMIN_KEY = old


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    async def test_rate_limit_headers(self, client):
        key = await _mock_auth(client)
        headers = _user_headers(key)

        resp = await client.get("/v1/me", headers=headers)
        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    async def test_rate_limit_enforced(self, client):
        key = await _mock_auth(client)
        headers = _user_headers(key)

        # Set very low rate limit
        rate_limiter.rate = 2
        rate_limiter.buckets.clear()

        # First two should succeed
        resp1 = await client.get("/v1/me", headers=headers)
        assert resp1.status_code == 200
        resp2 = await client.get("/v1/me", headers=headers)
        assert resp2.status_code == 200

        # Third should be rate limited
        resp3 = await client.get("/v1/me", headers=headers)
        assert resp3.status_code == 429
        assert resp3.json()["error"]["code"] == "rate_limited"

        # Restore
        rate_limiter.rate = 60
        rate_limiter.buckets.clear()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    async def test_state_persists_through_save_load(self, client):
        # Create market via admin
        resp = await client.post("/v1/admin/markets", headers=ADMIN_HEADERS,
                                 json={"question": "Persist?", "category": "t",
                                       "category_id": "t#p"})
        mid = resp.json()["market_id"]

        # Create user and trade
        key = await _mock_auth(client)
        resp = await client.post(f"/v1/markets/{mid}/buy",
                                 headers=_user_headers(key),
                                 json={"outcome": "yes", "budget": "50"})
        assert resp.status_code == 200

        # Reload state from disk
        from exchange.core.persistence import load_snapshot
        risk, me, auth_store, tracked_repos, _venues, _ = load_snapshot("/tmp/futarchy_test_state.json")

        # Verify market exists
        assert mid in me.markets
        assert me.markets[mid].question == "Persist?"
        assert len(me.markets[mid].trades) == 1

        # Verify auth store
        assert auth_store is not None
        assert len(auth_store.users) == 1

        # Verify user can still authenticate
        user = auth_store.authenticate(key)
        assert user is not None
        assert user.github_login == "testuser"


# ---------------------------------------------------------------------------
# Error Format
# ---------------------------------------------------------------------------

class TestErrorFormat:
    async def test_error_format(self, client):
        resp = await client.get("/v1/me")
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert "details" in data["error"]


# ---------------------------------------------------------------------------
# Dashboard & Static Files
# ---------------------------------------------------------------------------

class TestDashboard:
    async def test_dashboard_route_serves_html(self, client):
        """Dashboard route must return 200 with HTML content."""
        resp = await client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Futarchy" in resp.text
        assert "Sign in with GitHub" in resp.text

    async def test_landing_page_routes_humans_and_agents(self, client):
        """Landing routes humans to futarchy.ai and agents to /docs + CLI."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "futarchy.ai" in resp.text
        assert "/docs" in resp.text
        assert "install.sh" in resp.text

    async def test_dashboard_api_paths_match_registered_routes(self, client):
        """Every fetch() path in dashboard.html must correspond to a real API route.

        This prevents the dashboard from silently breaking when API routes
        are renamed or prefixed (the exact bug from PR #8 → v1 migration).
        """
        static_dir = Path(__file__).resolve().parent.parent / "static"
        dashboard_html = (static_dir / "dashboard.html").read_text()

        # Extract all paths from fetch('/v1' + path) calls.
        # The dashboard uses: api('/markets' + params), api('/markets/' + id), etc.
        # The api() function prepends '/v1', so effective paths are /v1/markets, etc.
        # We extract the path fragments passed to api() and prepend /v1.
        api_calls = re.findall(r"(?:api|requestJson)\(['\"]([^'\"]+)['\"]", dashboard_html)
        # Also catch template-literal patterns like api('/markets/' + id)
        api_calls += re.findall(r"(?:api|requestJson)\(['\"/]([^'\"+ )]+)", dashboard_html)

        # Normalize: strip leading slash, dedupe
        raw_paths = set()
        for p in api_calls:
            p = p.lstrip("/")
            raw_paths.add(p)

        # Build the set of registered route path templates (strip /v1 prefix for comparison)
        registered = set()
        for route in app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/v1/"):
                # Normalize path params: /markets/{market_id} → /markets/
                normalized = re.sub(r"\{[^}]+\}", "", path[4:]).rstrip("/")
                registered.add(normalized)

        # Each dashboard API path (after stripping dynamic suffixes) must match
        missing = []
        for raw in raw_paths:
            # Strip trailing dynamic parts: '/markets/' + id → 'markets'
            base = raw.split("?")[0].rstrip("/")
            # Remove trailing path segments that look dynamic (numbers)
            base = re.sub(r"/\d+.*", "", base)
            if base and base not in registered:
                missing.append(f"/v1/{raw}")

        assert not missing, (
            f"Dashboard fetches API paths that don't exist as routes: {missing}. "
            f"Registered /v1 routes: {sorted('/v1/' + r for r in registered)}"
        )


# ---------------------------------------------------------------------------
# Tracked Repos Admin
# ---------------------------------------------------------------------------

class TestTrackedRepos:
    async def test_add_list_delete_repo(self, client):
        # List — empty initially
        resp = await client.get("/v1/admin/repos", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

        # Add a repo
        resp = await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                                  json={"repo": "snapshot-labs/sx-monorepo",
                                        "webhook_secret": "test-secret"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo"] == "snapshot-labs/sx-monorepo"
        assert data["enabled"] is True
        assert data["has_webhook_secret"] is True

        # List shows it
        resp = await client.get("/v1/admin/repos", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Delete
        resp = await client.delete(
            "/v1/admin/repos/snapshot-labs/sx-monorepo",
            headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "snapshot-labs/sx-monorepo"

        # List — empty again
        resp = await client.get("/v1/admin/repos", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_add_repo_invalid_format(self, client):
        resp = await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                                  json={"repo": "no-slash"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_repo"

    async def test_delete_nonexistent_repo(self, client):
        resp = await client.delete(
            "/v1/admin/repos/not/tracked",
            headers=ADMIN_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "repo_not_found"

    async def test_add_repo_requires_admin(self, client):
        resp = await client.post("/v1/admin/repos",
                                  json={"repo": "owner/name"})
        assert resp.status_code == 401

    async def test_add_repo_upsert(self, client):
        """Adding the same repo twice updates it."""
        await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                          json={"repo": "owner/name",
                                "webhook_secret": "s1"})
        resp = await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                                  json={"repo": "owner/name",
                                        "webhook_secret": "s2"})
        assert resp.status_code == 200

        repos = (await client.get("/v1/admin/repos",
                                   headers=ADMIN_HEADERS)).json()
        assert len(repos) == 1


# ---------------------------------------------------------------------------
# GitHub Webhook
# ---------------------------------------------------------------------------

def _make_webhook_payload(action, pr_number=42, pr_title="Test PR",
                          repo="snapshot-labs/sx-monorepo",
                          merged=False):
    """Build a GitHub pull_request webhook payload."""
    return {
        "action": action,
        "pull_request": {
            "number": pr_number,
            "title": pr_title,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "merged": merged,
        },
        "repository": {
            "full_name": repo,
        },
    }


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature like GitHub does."""
    import hashlib, hmac as _hmac, json
    sig = _hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class TestWebhook:
    REPO = "snapshot-labs/sx-monorepo"
    SECRET = "webhook-test-secret"

    async def _setup_repo(self, client, secret=None):
        """Add tracked repo and optionally a treasury."""
        # Ensure tracked_repos is initialized
        if not hasattr(app.state, "tracked_repos"):
            app.state.tracked_repos = {}

        await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                          json={"repo": self.REPO,
                                "webhook_secret": secret or self.SECRET})

        # Create a treasury with funds
        resp = await client.post("/v1/admin/accounts", headers=ADMIN_HEADERS)
        treasury_id = resp.json()["account_id"]
        await client.post("/v1/admin/mint", headers=ADMIN_HEADERS,
                          json={"account_id": treasury_id, "amount": "10000"})

        # Set the treasury env var
        import exchange.core.api
        exchange.core.api.TREASURY_ACCOUNT_ID = str(treasury_id)
        return treasury_id

    async def _post_webhook(self, client, payload, secret=None):
        """Post a webhook event with proper signature."""
        import json as _json
        body = _json.dumps(payload).encode()
        headers = {"x-github-event": "pull_request"}
        if secret:
            headers["x-hub-signature-256"] = _sign_payload(body, secret)
        return await client.post("/v1/hooks/github", content=body,
                                  headers={**headers,
                                           "content-type": "application/json"})

    async def test_pr_opened_creates_market(self, client):
        await self._setup_repo(client)
        payload = _make_webhook_payload("opened", pr_number=10,
                                         pr_title="Add feature")
        resp = await self._post_webhook(client, payload, self.SECRET)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "opened"
        assert data["market_id"] is not None
        assert data["skipped"] is False

        # Verify market was actually created
        markets = (await client.get("/v1/markets",
                                     params={"category": "pr_merge"})).json()
        assert len(markets) == 1
        assert "#10@" in markets[0]["category_id"]
        assert markets[0]["question"].startswith("Will PR #10")

    async def test_pr_opened_idempotent(self, client):
        """Duplicate open events don't create duplicate markets."""
        await self._setup_repo(client)
        payload = _make_webhook_payload("opened", pr_number=10)

        resp1 = await self._post_webhook(client, payload, self.SECRET)
        assert resp1.status_code == 200
        mid1 = resp1.json()["market_id"]

        resp2 = await self._post_webhook(client, payload, self.SECRET)
        assert resp2.status_code == 200
        assert resp2.json()["skipped"] is True
        assert resp2.json()["market_id"] == mid1

        # Only one market exists
        markets = (await client.get("/v1/markets",
                                     params={"category": "pr_merge"})).json()
        assert len(markets) == 1

    async def test_pr_closed_merged_resolves_yes(self, client):
        await self._setup_repo(client)

        # First create market
        open_payload = _make_webhook_payload("opened", pr_number=20)
        resp = await self._post_webhook(client, open_payload, self.SECRET)
        mid = resp.json()["market_id"]

        # Then close/merge
        close_payload = _make_webhook_payload("closed", pr_number=20,
                                               merged=True)
        resp = await self._post_webhook(client, close_payload, self.SECRET)
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "yes"

        # Verify market is resolved
        detail = (await client.get(f"/v1/markets/{mid}")).json()
        assert detail["status"] == "resolved"
        assert detail["resolution"] == "yes"

    async def test_pr_closed_not_merged_resolves_no(self, client):
        await self._setup_repo(client)

        open_payload = _make_webhook_payload("opened", pr_number=30)
        resp = await self._post_webhook(client, open_payload, self.SECRET)
        mid = resp.json()["market_id"]

        close_payload = _make_webhook_payload("closed", pr_number=30,
                                               merged=False)
        resp = await self._post_webhook(client, close_payload, self.SECRET)
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "no"

        detail = (await client.get(f"/v1/markets/{mid}")).json()
        assert detail["status"] == "resolved"
        assert detail["resolution"] == "no"

    async def test_pr_close_does_not_settle_prefix_collision(self, client):
        await self._setup_repo(client)

        first = await self._post_webhook(
            client, _make_webhook_payload("opened", pr_number=1), self.SECRET,
        )
        tenth = await self._post_webhook(
            client, _make_webhook_payload("opened", pr_number=10), self.SECRET,
        )
        await self._post_webhook(
            client,
            _make_webhook_payload("closed", pr_number=1, merged=True),
            self.SECRET,
        )

        first_detail = (
            await client.get(f"/v1/markets/{first.json()['market_id']}")
        ).json()
        tenth_detail = (
            await client.get(f"/v1/markets/{tenth.json()['market_id']}")
        ).json()
        assert first_detail["resolution"] == "yes"
        assert tenth_detail["status"] == "open"

    async def test_untracked_repo_rejected(self, client):
        # Don't add any repo — post directly
        if not hasattr(app.state, "tracked_repos"):
            app.state.tracked_repos = {}
        payload = _make_webhook_payload("opened", repo="unknown/repo")
        resp = await self._post_webhook(client, payload)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "repo_not_tracked"

    async def test_disabled_repo_skipped(self, client):
        if not hasattr(app.state, "tracked_repos"):
            app.state.tracked_repos = {}
        await client.post("/v1/admin/repos", headers=ADMIN_HEADERS,
                          json={"repo": self.REPO,
                                "webhook_secret": self.SECRET,
                                "enabled": False})
        payload = _make_webhook_payload("opened")
        resp = await self._post_webhook(client, payload, self.SECRET)
        assert resp.status_code == 200
        assert resp.json()["skipped"] is True

    async def test_invalid_signature_rejected(self, client):
        await self._setup_repo(client)
        payload = _make_webhook_payload("opened")
        # Sign with wrong secret
        resp = await self._post_webhook(client, payload, "wrong-secret")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "signature_invalid"

    async def test_missing_signature_rejected(self, client):
        await self._setup_repo(client)
        payload = _make_webhook_payload("opened")
        # No signature header
        import json as _json
        body = _json.dumps(payload).encode()
        resp = await client.post("/v1/hooks/github", content=body,
                                  headers={"x-github-event": "pull_request",
                                           "content-type": "application/json"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "signature_missing"

    async def test_non_pr_event_ignored(self, client):
        if not hasattr(app.state, "tracked_repos"):
            app.state.tracked_repos = {}
        resp = await client.post("/v1/hooks/github",
                                  json={"action": "created"},
                                  headers={"x-github-event": "push"})
        assert resp.status_code == 200
        assert resp.json()["skipped"] is True

    async def test_unhandled_action_ignored(self, client):
        await self._setup_repo(client)
        payload = _make_webhook_payload("reopened")
        resp = await self._post_webhook(client, payload, self.SECRET)
        assert resp.status_code == 200
        assert resp.json()["skipped"] is True

    async def test_market_metadata_correct(self, client):
        """Verify the market metadata matches pr-market.yml conventions."""
        await self._setup_repo(client)
        payload = _make_webhook_payload("opened", pr_number=55,
                                         pr_title="Big feature")
        resp = await self._post_webhook(client, payload, self.SECRET)
        mid = resp.json()["market_id"]

        detail = (await client.get(f"/v1/markets/{mid}")).json()
        meta = detail["metadata"]
        assert meta["pr_number"] == 55
        assert meta["repo"] == self.REPO
        assert "pr_url" in meta
        assert "liquidity_step" in meta
        assert "liquidity_steps_remaining" in meta
        assert "next_liquidity_at" in meta
        assert detail["deadline"] is not None


class TestExpiredMarketReconciliation:
    async def test_startup_voids_expired_markets_loaded_from_snapshot(
        self, tmp_path
    ):
        import exchange.core.api as api_module
        from exchange.core.persistence import load_snapshot, save_snapshot

        reset_counters()
        risk = RiskEngine()
        me = MarketEngine(risk)
        auth_store = AuthStore()

        market, _ = me.create_market(
            question="Will it ship?",
            category="pr_merge",
            category_id="repo#1@2026-03-01",
            metadata={},
            deadline="2026-03-01T00:00:00Z",
        )

        state_path = tmp_path / "futarchy_state.json"
        save_snapshot(
            risk,
            me,
            str(state_path),
            auth_store=auth_store,
            tracked_repos={},
            instruments={},
        )

        original_state_path = api_module.STATE_PATH
        api_module.STATE_PATH = str(state_path)
        try:
            async with api_module.lifespan(app):
                assert app.state.me.markets[market.id].status == "void"

            _, loaded_me, _, _, _, _ = load_snapshot(str(state_path))
            assert loaded_me.markets[market.id].status == "void"
            assert loaded_me.markets[market.id].resolved_at is not None
        finally:
            api_module.STATE_PATH = original_state_path

    async def test_background_reconciler_voids_markets_after_deadline(
        self, client, monkeypatch
    ):
        import exchange.core.api as api_module

        monkeypatch.setattr(
            api_module,
            "MARKET_EXPIRY_CHECK_INTERVAL_SECONDS",
            0.01,
        )

        deadline = (
            datetime.now(timezone.utc) + timedelta(milliseconds=20)
        ).isoformat().replace("+00:00", "Z")

        resp = await client.post(
            "/v1/admin/markets",
            headers=ADMIN_HEADERS,
            json={
                "question": "Will it expire?",
                "category": "pr_merge",
                "category_id": "repo#2@2026-03-01",
                "deadline": deadline,
            },
        )
        mid = resp.json()["market_id"]

        stop_event = asyncio.Event()
        task = asyncio.create_task(
            api_module._expired_market_reconciler(stop_event)
        )
        try:
            await asyncio.sleep(0.1)
        finally:
            stop_event.set()
            await task

        detail = (await client.get(f"/v1/markets/{mid}")).json()
        assert detail["status"] == "void"
        assert detail["resolved_at"] is not None
