"""HTTP proofs for self-serve markets and resolver authorization."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("FUTARCHY_STATE", "/tmp/futarchy_test_state.json")
os.environ.setdefault("INITIAL_CREDITS", "1000")

import exchange.core.api as api_module
from exchange.core.api import _authenticate_github_identity, app
from exchange.core.auth import AuthStore
from exchange.core.market_engine import MarketEngine
from exchange.core.middleware import rate_limiter
from exchange.core.models import TrackedRepo, reset_counters
from exchange.core.risk_engine import RiskEngine
from exchange.venues.book.engine import BookEngine
from exchange.venues.book.venue import BookVenue


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-key"}
FIXED_NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _deadline(delta: timedelta = timedelta(days=1)) -> str:
    return (FIXED_NOW + delta).isoformat().replace("+00:00", "Z")


RESOLUTION_CRITERIA = (
    "Resolve YES if the release is publicly available by the deadline; "
    "otherwise resolve NO."
)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    reset_counters()
    risk = RiskEngine()
    app.state.risk = risk
    app.state.me = MarketEngine(risk)
    app.state.auth_store = AuthStore()
    app.state.tracked_repos = {}
    app.state.instruments = {}
    app.state.venues = {}
    app.state.joint = None
    app.state.book = BookVenue(BookEngine(risk))
    app.state.lock = asyncio.Lock()
    rate_limiter.buckets.clear()
    monkeypatch.setattr(api_module, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(api_module, "TREASURY_ACCOUNT_ID", "")
    monkeypatch.setattr(api_module, "_now", lambda: FIXED_NOW)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as value:
        yield value


async def _user(github_id: int, login: str):
    return await _authenticate_github_identity({"id": github_id, "login": login})


async def _create_amm(client, key: str, **overrides):
    payload = {
        "question": "Will self-serve markets work?",
        "deadline": _deadline(),
        "funding": "25",
        "resolution_criteria": RESOLUTION_CRITERIA,
    }
    payload.update(overrides)
    return await client.post("/v1/markets", headers=_headers(key), json=payload)


async def test_amm_creation_uses_exact_creator_funding(client):
    creator = await _user(1, "creator")
    account = app.state.risk.get_account(creator.account_id)
    before = account.available_balance

    response = await _create_amm(client, creator.api_key)

    assert response.status_code == 200
    market_id = response.json()["market_id"]
    market = app.state.me.markets[market_id]
    amm = app.state.risk.get_account(market.amm_account_id)
    assert before - account.available_balance == Decimal("25")
    assert amm.frozen_balance == Decimal("25")
    assert market.category == "user"
    assert market.category_id.startswith(f"user/{creator.account_id}/will-self-serve-markets-work-")

    detail = (await client.get(f"/v1/markets/{market_id}")).json()
    assert detail["creator_account_id"] == creator.account_id
    assert detail["resolver"] == {"type": "creator"}
    assert detail["metadata"]["funding_account_id"] == creator.account_id
    assert detail["metadata"]["creator_github_id"] == 1
    assert detail["metadata"]["creator_login"] == "creator"
    assert detail["metadata"]["resolution_criteria"] == RESOLUTION_CRITERIA


@pytest.mark.parametrize("criteria", ["", "   ", "x" * 4001])
async def test_amm_rejects_invalid_resolution_criteria(client, criteria):
    creator = await _user(100, "criteria")
    response = await _create_amm(
        client, creator.api_key, resolution_criteria=criteria,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_resolution_criteria"


@pytest.mark.parametrize("criteria", ["", "   ", "x" * 4001])
async def test_book_rejects_invalid_resolution_criteria(client, criteria):
    creator = await _user(101, "book-criteria")
    response = await client.post(
        "/v1/book/markets",
        headers=_headers(creator.api_key),
        json={
            "question": "Are these criteria valid?",
            "deadline": _deadline(),
            "resolution_criteria": criteria,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_resolution_criteria"


async def test_insufficient_funding_has_zero_state_change(client):
    creator = await _user(2, "underfunded")
    account = app.state.risk.get_account(creator.account_id)
    account.available_balance = Decimal("5")
    before = (
        set(app.state.risk.accounts),
        set(app.state.me.markets),
        len(app.state.risk.transactions),
        account.available_balance,
    )

    response = await _create_amm(client, creator.api_key, funding="10")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert before == (
        set(app.state.risk.accounts),
        set(app.state.me.markets),
        len(app.state.risk.transactions),
        account.available_balance,
    )


@pytest.mark.parametrize("funding", ["9.999999", "500.000001", "NaN"])
async def test_user_funding_bounds(client, funding):
    creator = await _user(hash(funding), funding)
    response = await _create_amm(client, creator.api_key, funding=funding)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "deadline,code",
    [
        (_deadline(timedelta(seconds=-1)), "invalid_deadline"),
        (_deadline(timedelta(days=400, seconds=1)), "deadline_out_of_bounds"),
        ("not-a-date", "invalid_deadline"),
    ],
)
async def test_user_deadline_bounds(client, deadline, code):
    creator = await _user(hash(deadline), deadline)
    response = await _create_amm(client, creator.api_key, deadline=deadline)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("outcomes", [["yes"], [str(i) for i in range(9)], ["x", "x"]])
async def test_user_outcome_bounds(client, outcomes):
    creator = await _user(len(outcomes) * 100 + len(set(outcomes)), "outcomes")
    response = await _create_amm(client, creator.api_key, outcomes=outcomes)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_outcomes"


async def test_category_ids_are_unique_for_repeated_questions(client):
    creator = await _user(30, "repeat")
    first = await _create_amm(client, creator.api_key)
    second = await _create_amm(client, creator.api_key)
    first_market = app.state.me.markets[first.json()["market_id"]]
    second_market = app.state.me.markets[second.json()["market_id"]]
    assert first_market.category_id != second_market.category_id


async def test_cap_is_shared_between_amm_and_book(client, monkeypatch):
    monkeypatch.setattr(api_module, "USER_MARKET_CAP", 2)
    creator = await _user(40, "capped")
    assert (await _create_amm(client, creator.api_key)).status_code == 200
    assert (
        await client.post(
            "/v1/book/markets", headers=_headers(creator.api_key),
            json={
                "question": "Book question?",
                "deadline": _deadline(),
                "resolution_criteria": RESOLUTION_CRITERIA,
            },
        )
    ).status_code == 200

    rejected = await _create_amm(client, creator.api_key, question="One too many?")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "market_cap_reached"


async def test_creator_resolution_rules_and_exact_winner_balance(client, monkeypatch):
    creator = await _user(50, "resolver")
    trader = await _user(51, "winner")
    created = await _create_amm(client, creator.api_key, deadline=_deadline(timedelta(hours=1)))
    market_id = created.json()["market_id"]

    bought = await client.post(
        f"/v1/markets/{market_id}/buy", headers=_headers(trader.api_key),
        json={"outcome": "yes", "budget": "10"},
    )
    assert bought.status_code == 200
    amount = Decimal(bought.json()["amount"])
    value = Decimal(bought.json()["value"])

    early = await client.post(
        f"/v1/markets/{market_id}/resolve", headers=_headers(creator.api_key),
        json={"outcome": "yes"},
    )
    assert early.status_code == 403
    assert early.json()["error"]["code"] == "before_deadline"

    monkeypatch.setattr(api_module, "_now", lambda: FIXED_NOW + timedelta(hours=2))
    assert market_id not in await api_module._reconcile_expired_markets_once(
        FIXED_NOW + timedelta(hours=2)
    )
    denied = await client.post(
        f"/v1/markets/{market_id}/resolve", headers=_headers(trader.api_key),
        json={"outcome": "yes"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "not_resolver"

    resolved = await client.post(
        f"/v1/markets/{market_id}/resolve", headers=_headers(creator.api_key),
        json={"outcome": "yes"},
    )
    assert resolved.status_code == 200
    winner = app.state.risk.get_account(trader.account_id)
    assert winner.available_balance == Decimal("1000") - value + amount
    assert winner.frozen_balance == 0


async def test_admin_can_resolve_creator_market_before_deadline(client):
    creator = await _user(60, "admin-override")
    created = await _create_amm(client, creator.api_key)
    market_id = created.json()["market_id"]

    response = await client.post(
        f"/v1/markets/{market_id}/resolve", headers=ADMIN_HEADERS,
        json={"outcome": "no"},
    )
    assert response.status_code == 200
    assert app.state.me.markets[market_id].resolution == "no"


async def test_creator_can_void_after_deadline(client, monkeypatch):
    creator = await _user(70, "voider")
    created = await _create_amm(client, creator.api_key)
    market_id = created.json()["market_id"]
    monkeypatch.setattr(api_module, "_now", lambda: FIXED_NOW + timedelta(days=2))

    response = await client.post(
        f"/v1/markets/{market_id}/void", headers=_headers(creator.api_key),
    )
    assert response.status_code == 200
    assert app.state.me.markets[market_id].status == "void"


async def test_book_creator_metadata_and_resolution(client, monkeypatch):
    creator = await _user(80, "book-creator")
    other = await _user(81, "book-other")
    created = await client.post(
        "/v1/book/markets", headers=_headers(creator.api_key),
        json={
            "question": "Will the book settle?",
            "deadline": _deadline(),
            "resolution_criteria": RESOLUTION_CRITERIA,
        },
    )
    assert created.status_code == 200
    market_id = created.json()["id"]
    assert created.json()["creatorAccountId"] == creator.account_id
    assert created.json()["resolver"] == {"type": "creator"}
    assert created.json()["metadata"]["creator_github_id"] == 80
    assert created.json()["metadata"]["creator_login"] == "book-creator"
    assert created.json()["metadata"]["resolution_criteria"] == RESOLUTION_CRITERIA

    early = await client.post(
        f"/v1/book/markets/{market_id}/resolve", headers=_headers(creator.api_key),
        json={"outcome": "yes"},
    )
    assert early.status_code == 403
    assert early.json()["error"]["code"] == "before_deadline"

    monkeypatch.setattr(api_module, "_now", lambda: FIXED_NOW + timedelta(days=2))
    denied = await client.post(
        f"/v1/book/markets/{market_id}/void", headers=_headers(other.api_key),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "not_resolver"
    resolved = await client.post(
        f"/v1/book/markets/{market_id}/resolve", headers=_headers(creator.api_key),
        json={"outcome": "yes"},
    )
    assert resolved.status_code == 200


async def test_legacy_creation_without_resolution_criteria_still_works(client):
    creator = await _user(83, "book-criteria")
    book = await client.post(
        "/v1/book/markets", headers=_headers(creator.api_key),
        json={"question": "Legacy book client?", "deadline": _deadline()},
    )
    amm = await _create_amm(
        client, creator.api_key, resolution_criteria=None,
    )
    assert book.status_code == 200
    assert "resolution_criteria" not in book.json()["metadata"]
    assert amm.status_code == 200
    detail = (await client.get(f"/v1/markets/{amm.json()['market_id']}")).json()
    assert "resolution_criteria" not in detail["metadata"]


async def test_book_creator_can_void_after_deadline(client, monkeypatch):
    creator = await _user(82, "book-voider")
    created = await client.post(
        "/v1/book/markets", headers=_headers(creator.api_key),
        json={
            "question": "Will the book condition be met?",
            "deadline": _deadline(),
            "resolution_criteria": RESOLUTION_CRITERIA,
        },
    )
    market_id = created.json()["id"]
    monkeypatch.setattr(api_module, "_now", lambda: FIXED_NOW + timedelta(days=2))

    response = await client.post(
        f"/v1/book/markets/{market_id}/void",
        headers=_headers(creator.api_key),
    )
    assert response.status_code == 200
    assert response.json()["market"]["status"] == "void"


async def test_admin_created_markets_default_to_admin_resolver(client):
    amm = await client.post(
        "/v1/admin/markets", headers=ADMIN_HEADERS,
        json={"question": "Admin AMM?", "category": "test", "category_id": "admin/amm"},
    )
    amm_detail = (await client.get(f"/v1/markets/{amm.json()['market_id']}")).json()
    assert amm_detail["resolver"] == {"type": "admin"}

    book = await client.post(
        "/v1/book/markets", headers=ADMIN_HEADERS, json={"question": "Admin book?"},
    )
    assert book.status_code == 200
    assert book.json()["resolver"] == {"type": "admin"}


async def test_github_pr_market_keeps_webhook_resolver(client):
    app.state.tracked_repos["owner/repo"] = TrackedRepo.new("owner/repo")
    opened = {
        "action": "opened",
        "pull_request": {
            "number": 9,
            "title": "Resolver metadata",
            "html_url": "https://github.com/owner/repo/pull/9",
        },
        "repository": {"full_name": "owner/repo"},
    }
    response = await client.post(
        "/v1/hooks/github", json=opened, headers={"x-github-event": "pull_request"},
    )
    market_id = response.json()["market_id"]
    detail = (await client.get(f"/v1/markets/{market_id}")).json()
    assert detail["resolver"] == {
        "type": "github_pr", "repo": "owner/repo", "pr_number": 9,
    }
    user = await _user(90, "not-webhook")
    denied = await client.post(
        f"/v1/markets/{market_id}/resolve", headers=_headers(user.api_key),
        json={"outcome": "yes"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "not_resolver"

    closed = {**opened, "action": "closed", "pull_request": {**opened["pull_request"], "merged": True}}
    response = await client.post(
        "/v1/hooks/github", json=closed, headers={"x-github-event": "pull_request"},
    )
    assert response.status_code == 200
    assert app.state.me.markets[market_id].resolution == "yes"
