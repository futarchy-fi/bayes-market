"""HTTP, timer, disclosure, and restart coverage for the batch venue."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")

import exchange.core.api as api_module
import exchange.core.middleware as middleware_module
from exchange.core.api import _authenticate_github_identity, app
from exchange.core.models import reset_counters
from exchange.core.persistence import load_snapshot
from exchange.venues.batch.engine import ClearingError


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-key"}


async def _request(method, path, *, key=None, body=None, public=False):
    headers = {} if public else (
        {"Authorization": f"Bearer {key}"} if key else ADMIN_HEADERS
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path, headers=headers, json=body)


@pytest.fixture(autouse=True)
def _state_path(tmp_path, monkeypatch):
    original = api_module.STATE_PATH
    monkeypatch.delenv("EXCHANGE_SEEDS_PATH", raising=False)
    monkeypatch.setattr(api_module, "BATCH_ROUND_CHECK_SECONDS", 30)
    monkeypatch.setattr(middleware_module, "ADMIN_KEY", "test-admin-key")
    api_module.STATE_PATH = str(tmp_path / "state.json")
    reset_counters()
    yield
    api_module.STATE_PATH = original


async def test_sealed_orders_clear_and_only_owner_can_see_them():
    async with api_module.lifespan(app):
        assert app.state.venues_by_kind["batch"] is app.state.batch
        assert app.state.batch_round_task is not None
        health = await _request("GET", "/v1/health", public=True)
        assert health.json()["venues"]["batch"] == {
            "markets": 0,
            "orders_or_trades": 0,
        }

        alice = await _authenticate_github_identity({"id": 201, "login": "alice"})
        bob = await _authenticate_github_identity({"id": 202, "login": "bob"})
        created = await _request(
            "POST", "/v1/batch/markets", body={"question": "Will it ship?", "b": "10"}
        )
        assert created.status_code == 200
        market_id = created.json()["id"]

        listed = await _request("GET", "/v1/batch/markets", public=True)
        assert listed.status_code == 200
        assert listed.json() == {"markets": [created.json()], "count": 1}

        unauthenticated = await _request(
            "POST", "/v1/batch/orders", public=True,
            body={
                "marketId": market_id, "outcome": "yes",
                "target": "0.8", "maxSpend": "5",
            },
        )
        assert unauthenticated.status_code == 401
        forbidden = await _request(
            "POST", "/v1/batch/markets", key=alice.api_key,
            body={"question": "Not an admin"},
        )
        assert forbidden.status_code == 403

        alice_order = await _request(
            "POST", "/v1/batch/orders", key=alice.api_key,
            body={
                "marketId": market_id, "outcome": "yes",
                "target": "0.8", "maxSpend": "5",
            },
        )
        bob_order = await _request(
            "POST", "/v1/batch/orders", key=bob.api_key,
            body={
                "marketId": market_id, "outcome": "no",
                "target": "0.7", "maxSpend": "4",
            },
        )
        assert alice_order.status_code == bob_order.status_code == 200
        assert alice_order.json()["balance"]["frozen"] == "5"
        assert bob_order.json()["balance"]["frozen"] == "4"

        alice_mine = await _request("GET", "/v1/batch/orders/mine", key=alice.api_key)
        bob_mine = await _request("GET", "/v1/batch/orders/mine", key=bob.api_key)
        assert {order["orderId"] for order in alice_mine.json()["orders"]} == {
            alice_order.json()["orderId"]
        }
        assert {order["orderId"] for order in bob_mine.json()["orders"]} == {
            bob_order.json()["orderId"]
        }

        public = await _request(
            "GET", f"/v1/batch/markets/{market_id}", public=True
        )
        assert set(public.json()) == {
            "id", "question", "status", "postedPrice", "round", "roundHistory", "b"
        }
        assert "order" not in str(public.json()).lower()
        assert public.json()["roundHistory"] == []

        closed = await _request(
            "POST", f"/v1/batch/markets/{market_id}/close-round"
        )
        assert closed.status_code == 200
        assert set(closed.json()) == {"round", "clearingPrice", "participants"}
        assert closed.json()["participants"] == 2
        public = (await _request(
            "GET", f"/v1/batch/markets/{market_id}", public=True
        )).json()
        assert public["round"] == 2
        assert public["roundHistory"] == [closed.json()]
        assert (await _request(
            "GET", "/v1/batch/orders/mine", key=alice.api_key
        )).json() == {"orders": []}

        resolved = await _request(
            "POST", f"/v1/batch/markets/{market_id}/resolve", body={"outcome": "yes"}
        )
        assert resolved.status_code == 200
        assert resolved.json()["market"]["status"] == "resolved"


async def test_create_funding_void_and_validation():
    async with api_module.lifespan(app):
        funded = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Funded?", "funding": "20", "roundSeconds": 60},
        )
        assert funded.status_code == 200
        assert Decimal(funded.json()["b"]) == Decimal("20") / Decimal(2).ln()

        both = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Bad", "b": "10", "funding": "20"},
        )
        assert both.status_code == 400
        assert both.json()["error"]["code"] == "invalid_target"

        bad_round = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Bad timer", "roundSeconds": 0},
        )
        assert bad_round.status_code == 400
        assert bad_round.json()["error"]["code"] == "invalid_target"

        missing = await _request("GET", "/v1/batch/markets/999", public=True)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "unknown_market"

        voided = await _request(
            "POST", f"/v1/batch/markets/{funded.json()['id']}/void"
        )
        assert voided.status_code == 200
        assert voided.json()["market"]["status"] == "void"


async def test_mid_round_pending_order_survives_restart():
    async with api_module.lifespan(app):
        trader = await _authenticate_github_identity({"id": 301, "login": "restart"})
        market = await _request(
            "POST", "/v1/batch/markets", body={"question": "Restart?"}
        )
        order = await _request(
            "POST", "/v1/batch/orders", key=trader.api_key,
            body={
                "marketId": market.json()["id"], "outcome": "yes",
                "target": "0.72", "maxSpend": "7",
            },
        )
        before = order.json()

    _, _, _, _, venues, _ = load_snapshot(api_module.STATE_PATH)
    assert venues["batch"]["pending"][0]["id"] == before["orderId"]

    async with api_module.lifespan(app):
        restored = await _request(
            "GET", "/v1/batch/orders/mine", key=trader.api_key
        )
        assert restored.status_code == 200
        assert restored.json()["orders"] == [
            {key: value for key, value in before.items() if key != "balance"}
        ]
        account = app.state.risk.get_account(trader.account_id)
        assert account.frozen_balance == Decimal("7")
        assert account.locks[0].lock_type == "batch_order"
        closed = await _request(
            "POST", f"/v1/batch/markets/{market.json()['id']}/close-round"
        )
        assert closed.json()["participants"] == 1
        assert account.frozen_balance == 0
        assert (await _request(
            "GET", "/v1/batch/orders/mine", key=trader.api_key
        )).json() == {"orders": []}


async def test_due_round_reconciliation_and_nonpositive_interval_disable(monkeypatch):
    monkeypatch.setattr(api_module, "BATCH_ROUND_CHECK_SECONDS", 0)
    async with api_module.lifespan(app):
        assert app.state.batch_round_task is None
        market = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Timed?", "roundSeconds": 10},
        )
        market_id = market.json()["id"]
        started = datetime.fromisoformat(
            app.state.batch.engine.markets[market_id].round_started_at
        )
        assert await api_module._close_due_batch_rounds_once(
            started + timedelta(seconds=9)
        ) == []
        assert await api_module._close_due_batch_rounds_once(
            started + timedelta(seconds=10)
        ) == [market_id]
        assert app.state.batch.get_market(market_id)["round"] == 2


async def test_overdue_persisted_round_closes_before_lifespan_yields(monkeypatch):
    monkeypatch.setattr(api_module, "BATCH_ROUND_CHECK_SECONDS", 30)
    async with api_module.lifespan(app):
        market = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Overdue?", "roundSeconds": 60},
        )
        batch_market = app.state.batch.engine.markets[market.json()["id"]]
        batch_market.round_started_at = (
            datetime.now(timezone.utc) - timedelta(seconds=61)
        ).isoformat()
        api_module._save()

    async with api_module.lifespan(app):
        restored = app.state.batch.get_market(market.json()["id"])
        assert restored["round"] == 2
        assert len(restored["roundHistory"]) == 1


async def test_background_task_closes_and_persists_due_round(monkeypatch):
    monkeypatch.setattr(api_module, "BATCH_ROUND_CHECK_SECONDS", 0.01)
    async with api_module.lifespan(app):
        trader = await _authenticate_github_identity({"id": 401, "login": "timer"})
        market = await _request(
            "POST", "/v1/batch/markets",
            body={"question": "Background?", "roundSeconds": 3600},
        )
        market_id = market.json()["id"]
        await _request(
            "POST", "/v1/batch/orders", key=trader.api_key,
            body={
                "marketId": market_id, "outcome": "yes",
                "target": "0.6", "maxSpend": "2",
            },
        )
        app.state.batch.engine.markets[market_id].round_started_at = (
            datetime.now(timezone.utc) - timedelta(seconds=3601)
        ).isoformat()

        async def wait_until_closed():
            while app.state.batch.engine.markets[market_id].round == 1:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_until_closed(), timeout=1)
        public = app.state.batch.get_market(market_id)
        assert public["round"] == 2
        assert public["roundHistory"][0]["participants"] == 1
        assert app.state.batch.orders_for(trader.account_id) == []

    _, _, _, _, venues, _ = load_snapshot(api_module.STATE_PATH)
    assert venues["batch"]["markets"][0]["round"] == 2
    assert len(venues["batch"]["markets"][0]["round_history"]) == 1


async def test_batch_clearing_error_is_structured(monkeypatch):
    async with api_module.lifespan(app):
        market = await _request(
            "POST", "/v1/batch/markets", body={"question": "Clear?"}
        )

        def fail(_market_id):
            raise ClearingError("could not clear")

        monkeypatch.setattr(app.state.batch, "close_round", fail)
        response = await _request(
            "POST", f"/v1/batch/markets/{market.json()['id']}/close-round"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "clearing_error"
