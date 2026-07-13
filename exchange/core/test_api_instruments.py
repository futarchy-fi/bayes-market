"""HTTP and persistence coverage for the cross-venue instrument registry."""

import json
import os
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")

import exchange.core.api as api_module
from exchange.core.api import _authenticate_github_identity, app, yes_price
from exchange.core.models import reset_counters
from exchange.core.persistence import load_snapshot
from exchange.venues.joint.test_venue import TINY_SEEDS


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-key"}


@asynccontextmanager
async def _running_exchange(tmp_path, monkeypatch):
    seeds_path = tmp_path / "seeds.json"
    seeds_path.write_text(json.dumps(TINY_SEEDS))
    monkeypatch.setenv("EXCHANGE_SEEDS_PATH", str(seeds_path))
    original_state_path = api_module.STATE_PATH
    api_module.STATE_PATH = str(tmp_path / "state.json")
    reset_counters()
    try:
        async with api_module.lifespan(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client
    finally:
        api_module.STATE_PATH = original_state_path


async def _post(client, path, body, *, key=None):
    headers = (
        {"Authorization": f"Bearer {key}"} if key is not None else ADMIN_HEADERS
    )
    return await client.post(path, json=body, headers=headers)


async def _seed_listings(client):
    amm = await _post(
        client,
        "/v1/admin/markets",
        {"question": "Will it ship?", "category": "test", "category_id": "ship"},
    )
    assert amm.status_code == 200

    book = await _post(client, "/v1/book/markets", {"question": "Will it ship?"})
    assert book.status_code == 200

    trader = await _authenticate_github_identity({"id": 801, "login": "maker"})
    for outcome, price in (("yes", "0.4000"), ("no", "0.3000")):
        order = await _post(
            client,
            "/v1/book/orders",
            {
                "marketId": book.json()["id"],
                "side": "bid",
                "outcome": outcome,
                "price": price,
                "size": "1.00",
            },
            key=trader.api_key,
        )
        assert order.status_code == 200

    return [
        {"venue": "net", "marketId": "g1"},
        {"venue": "amm", "marketId": str(amm.json()["market_id"])},
        {"venue": "book", "marketId": str(book.json()["id"])},
    ]


def test_yes_price_extracts_each_venue_shape():
    assert yes_price("net", {"marginals": {"yes": 0.61}}) == pytest.approx(0.61)
    assert yes_price("amm", {"prices": {"yes": "0.49"}}) == pytest.approx(0.49)
    assert yes_price(
        "book", {"bestBid": "0.4000", "bestAsk": "0.7000"}
    ) == pytest.approx(0.55)
    assert yes_price("book", {"bestBid": None, "bestAsk": None}) is None


async def test_create_list_delete_all_live_venues(tmp_path, monkeypatch):
    async with _running_exchange(tmp_path, monkeypatch) as client:
        listings = await _seed_listings(client)
        created = await _post(
            client,
            "/v1/admin/instruments",
            {
                "instrumentId": "ship-date",
                "title": "Will it ship?",
                "listings": listings,
            },
        )
        assert created.status_code == 200
        assert created.json()["listings"] == listings

        response = await client.get("/v1/instruments")
        assert response.status_code == 200
        [instrument] = response.json()
        assert instrument["instrumentId"] == "ship-date"
        assert instrument["title"] == "Will it ship?"
        by_venue = {listing["venue"]: listing for listing in instrument["listings"]}
        assert by_venue["net"]["yesPrice"] == pytest.approx(0.6)
        assert by_venue["amm"]["yesPrice"] == pytest.approx(0.5)
        assert by_venue["book"]["yesPrice"] == pytest.approx(0.55)
        assert {listing["status"] for listing in instrument["listings"]} == {"open"}

        deleted = await client.delete(
            "/v1/admin/instruments/ship-date", headers=ADMIN_HEADERS
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": "ship-date"}
        assert (await client.get("/v1/instruments")).json() == []


async def test_instrument_persistence_roundtrip(tmp_path, monkeypatch):
    async with _running_exchange(tmp_path, monkeypatch) as client:
        listings = await _seed_listings(client)
        response = await _post(
            client,
            "/v1/admin/instruments",
            {
                "instrumentId": "persistent-question",
                "title": "Persistent question",
                "listings": listings,
            },
        )
        assert response.status_code == 200

    *_, instruments = load_snapshot(str(tmp_path / "state.json"))
    restored = instruments["persistent-question"]
    assert restored.title == "Persistent question"
    assert restored.listings == listings

    async with _running_exchange(tmp_path, monkeypatch) as client:
        response = await client.get("/v1/instruments")
        assert response.status_code == 200
        assert response.json()[0]["instrumentId"] == "persistent-question"


@pytest.mark.parametrize(
    ("listing", "name"),
    [
        ({"venue": "missing", "marketId": "g1"}, "missing:g1"),
        ({"venue": "amm", "marketId": "999"}, "amm:999"),
    ],
)
async def test_invalid_listing_rejected(tmp_path, monkeypatch, listing, name):
    async with _running_exchange(tmp_path, monkeypatch) as client:
        response = await _post(
            client,
            "/v1/admin/instruments",
            {
                "instrumentId": "bad-listing",
                "title": "Bad listing",
                "listings": [listing],
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "invalid_listing"
        assert name in response.json()["error"]["message"]
        assert app.state.instruments == {}


async def test_instrument_id_must_be_slug(tmp_path, monkeypatch):
    async with _running_exchange(tmp_path, monkeypatch) as client:
        response = await _post(
            client,
            "/v1/admin/instruments",
            {"instrumentId": "Not A Slug", "title": "Bad", "listings": []},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_instrument_id"
