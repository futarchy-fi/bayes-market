"""HTTP lifecycle proof for the always-on complete-set order book."""

import os

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")

from httpx import ASGITransport, AsyncClient
import pytest

import exchange.core.api as api_module
from exchange.core.api import _authenticate_github_identity, app
from exchange.core.models import reset_counters
from exchange.core.persistence import load_snapshot


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-key"}


async def _request(method, path, *, key=None, body=None):
    headers = {"Authorization": f"Bearer {key}"} if key else ADMIN_HEADERS
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(method, path, headers=headers, json=body)


@pytest.fixture(autouse=True)
def _state_path(tmp_path, monkeypatch):
    original = api_module.STATE_PATH
    monkeypatch.delenv("EXCHANGE_SEEDS_PATH", raising=False)
    api_module.STATE_PATH = str(tmp_path / "state.json")
    reset_counters()
    yield
    api_module.STATE_PATH = original


async def test_order_mint_depth_survives_restart():
    async with api_module.lifespan(app):
        assert app.state.venues_by_kind["book"] is app.state.book
        yes = await _authenticate_github_identity({"id": 101, "login": "yes"})
        no = await _authenticate_github_identity({"id": 102, "login": "no"})

        created = await _request(
            "POST", "/v1/book/markets", body={"question": "Will it ship?"}
        )
        assert created.status_code == 200
        market_id = created.json()["id"]

        candles = await _request(
            "GET", f"/v1/book/markets/{market_id}/candles", key=yes.api_key
        )
        assert candles.status_code == 200
        assert candles.json() == []

        resting = await _request(
            "POST", "/v1/book/orders", key=yes.api_key,
            body={"marketId": market_id, "side": "bid", "outcome": "yes",
                  "price": "0.3000", "size": "2.00"},
        )
        assert resting.status_code == 200
        assert resting.json()["status"] == "open"

        await _request(
            "POST", "/v1/book/orders", key=no.api_key,
            body={"marketId": market_id, "side": "bid", "outcome": "no",
                  "price": "0.4000", "size": "1.00"},
        )
        crossed = await _request(
            "POST", "/v1/book/orders", key=yes.api_key,
            body={"marketId": market_id, "side": "bid", "outcome": "yes",
                  "price": "0.6000", "size": "1.00"},
        )
        assert crossed.status_code == 200
        assert crossed.json()["status"] == "filled"

        depth_response = await _request(
            "GET", f"/v1/book/markets/{market_id}/orderbook", key=yes.api_key
        )
        assert depth_response.status_code == 200
        depth_before = depth_response.json()
        assert depth_before["bids"] == [{"price": "0.3000", "size": "2.00"}]
        assert depth_before["asks"] == []

        trades = await _request(
            "GET", f"/v1/book/markets/{market_id}/trades", key=yes.api_key
        )
        assert trades.json()["trades"][0]["kind"] == "mint"
        candles = await _request(
            "GET", f"/v1/book/markets/{market_id}/candles", key=yes.api_key
        )
        assert set(candles.json()[0]) == {"t", "o", "h", "l", "c", "v"}
        assert candles.json()[0]["o"] == 0.6
        assert candles.json()[0]["v"] == 1.0

    _, _, _, _, venues, _ = load_snapshot(api_module.STATE_PATH)
    assert venues["book"]["trades"][str(market_id)][0]["kind"] == "mint"

    async with api_module.lifespan(app):
        depth_response = await _request(
            "GET", f"/v1/book/markets/{market_id}/orderbook", key=yes.api_key
        )
        assert depth_response.status_code == 200
        assert depth_response.json() == depth_before
        assert app.state.book.get_market(market_id)["setsMinted"] == "1.00"
