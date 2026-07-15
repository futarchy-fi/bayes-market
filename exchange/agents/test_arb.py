"""HTTP-backed policy proofs for the resident arbitrage agent."""

import json
import os
from copy import deepcopy
from decimal import Decimal

import httpx
import pytest

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("FUTARCHY_STATE", "/tmp/futarchy_test_state.json")

import exchange.core.api as api_module
import exchange.agents.arb as arb_module
from exchange.agents.arb import (
    ArbConfig,
    ArbPolicy,
    ExchangeHTTPError,
    HttpExchange,
    run_pass,
)
from exchange.core.api import _authenticate_github_identity, app
from exchange.core.lmsr import prices
from exchange.core.models import reset_counters
from exchange.core.middleware import rate_limiter
from exchange.venues.joint.test_venue import TINY_SEEDS


@pytest.fixture
async def seeded_exchange(tmp_path, monkeypatch):
    seeds = tmp_path / "seeds.json"
    # Production takeoff seeds mark live markets "active" (not "open") —
    # regression for the anchor-status bug that made every tick a NOOP.
    tiny = json.loads(json.dumps(TINY_SEEDS))
    for market in tiny["markets"].values():
        market["status"] = "active"
    seeds.write_text(json.dumps(tiny))
    state_path = tmp_path / "state.json"
    original_state_path = api_module.STATE_PATH
    monkeypatch.setenv("EXCHANGE_SEEDS_PATH", str(seeds))
    api_module.STATE_PATH = str(state_path)
    reset_counters()
    rate_limiter.buckets.clear()

    async with api_module.lifespan(app):
        amm, _ = app.state.me.create_market(
            "A", "arb-test", "a", {}, b=Decimal("20")
        )
        book = app.state.book.create_market("A")
        auth = await _authenticate_github_identity({"id": 9001, "login": "arb"})
        instrument = {
            "instrumentId": "test-a",
            "title": "A",
            "listings": [
                {"venue": "net", "marketId": "g1"},
                {"venue": "amm", "marketId": str(amm.id)},
                {"venue": "book", "marketId": str(book["id"])},
            ],
        }
        yield auth, instrument, amm, book

    api_module.STATE_PATH = original_state_path


def _client(api_key: str) -> HttpExchange:
    return HttpExchange(
        "http://test", api_key, transport=httpx.ASGITransport(app=app)
    )


async def test_distorted_amm_moves_toward_net_anchor_in_bounded_steps(
    seeded_exchange,
):
    auth, instrument, amm, _ = seeded_exchange
    instrument = {**instrument, "listings": instrument["listings"][:2]}
    before = prices(amm.q, amm.b)["yes"]
    anchor = Decimal("0.6")

    async with _client(auth.api_key) as client:
        policy = ArbPolicy(client, ArbConfig(report_only=False))
        executed = []
        for _ in range(3):
            actions = await policy.tick(instrument)
            if not actions:
                break
            executed.extend(actions)

    assert executed
    assert all(action.outcome == "yes" for action in executed)
    assert all(Decimal("0") < action.budget <= Decimal("25") for action in executed)

    after = prices(amm.q, amm.b)["yes"]
    assert before < after < anchor
    assert anchor - after < anchor - before


async def test_book_gets_two_sided_quotes_at_anchor_delta(seeded_exchange):
    auth, instrument, _, book = seeded_exchange
    async with _client(auth.api_key) as client:
        actions = await ArbPolicy(
            client, ArbConfig(report_only=False)
        ).tick(instrument)

    book_actions = [action for action in actions if action.venue == "book"]
    assert [(action.outcome, action.price) for action in book_actions] == [
        ("yes", Decimal("0.5900")),
        ("no", Decimal("0.3900")),
    ]
    orders = list(app.state.book.engine.orders.values())
    assert [(order.side, order.outcome, order.price, order.size) for order in orders] == [
        ("bid", "yes", Decimal("0.5900"), Decimal("10.00")),
        ("bid", "no", Decimal("0.3900"), Decimal("10.00")),
    ]
    assert all(order.market_id == book["id"] for order in orders)


async def test_report_only_performs_zero_mutations(seeded_exchange):
    auth, instrument, amm, _ = seeded_exchange
    q_before = deepcopy(amm.q)
    balance_before = app.state.risk.get_account(auth.account_id).available_balance

    async with _client(auth.api_key) as client:
        actions = await ArbPolicy(client, ArbConfig()).tick(instrument)

    assert {action.kind for action in actions} == {"would_buy", "would_quote"}
    assert amm.q == q_before
    assert app.state.book.engine.orders == {}
    assert app.state.risk.get_account(auth.account_id).available_balance == balance_before


async def test_balance_floor_refuses_all_actions(seeded_exchange):
    auth, instrument, amm, _ = seeded_exchange
    account = app.state.risk.get_account(auth.account_id)
    app.state.risk.transfer_available(
        account.id, app.state.joint.treasury_account_id,
        account.available_balance - Decimal("40"), reason="test_floor",
    )
    q_before = deepcopy(amm.q)

    async with _client(auth.api_key) as client:
        actions = await ArbPolicy(
            client, ArbConfig(report_only=False, min_balance=Decimal("50"))
        ).tick(instrument)

    assert actions == []
    assert amm.q == q_before
    assert app.state.book.engine.orders == {}


class _FlakyClient:
    """Instruments listing OK; the tick will fail on one instrument."""

    def __init__(self, instruments):
        self._instruments = instruments

    async def instruments(self):
        return self._instruments


class _RaisingPolicy:
    """Stand-in policy whose tick fails for one broken instrument."""

    def __init__(self):
        self.seen = []

    async def tick(self, instrument):
        self.seen.append(instrument["instrumentId"])
        if instrument["instrumentId"] == "a":
            raise ExchangeHTTPError("missing market", 404)
        return []


class _RateLimitedPolicy:
    def __init__(self, retry_after):
        self.retry_after = retry_after
        self.seen = []

    async def tick(self, instrument):
        self.seen.append(instrument["instrumentId"])
        raise ExchangeHTTPError("rate limited", 429, self.retry_after)


@pytest.mark.parametrize("payload", [{"error": {"message": "rate limited"}}, []])
async def test_http_error_preserves_status_and_retry_after(payload):
    transport = httpx.MockTransport(lambda _request: httpx.Response(
        429,
        headers={"Retry-After": "17"},
        json=payload,
    ))
    async with HttpExchange("http://test", "key", transport=transport) as client:
        with pytest.raises(ExchangeHTTPError) as caught:
            await client.instruments()

    assert caught.value.status_code == 429
    assert caught.value.retry_after == "17"


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("17", 17.0), (None, 60.0), ("bad", 60.0), ("0", 60.0),
     ("nan", 60.0), ("inf", 60.0)],
)
async def test_run_pass_stops_on_rate_limit(retry_after, expected):
    client = _FlakyClient([{"instrumentId": "a"}, {"instrumentId": "b"}])
    policy = _RateLimitedPolicy(retry_after)

    assert await run_pass(client, policy, selected=None) == expected
    assert policy.seen == ["a"]


async def test_run_pass_keeps_non_rate_limited_failures_local():
    client = _FlakyClient([{"instrumentId": "a"}, {"instrumentId": "b"}])
    policy = _RaisingPolicy()
    assert await run_pass(client, policy, selected=None) is None
    assert policy.seen == ["a", "b"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [(RuntimeError("network unavailable"), None),
     (ExchangeHTTPError("rate limited", 429, "17"), 17.0)],
)
async def test_run_pass_handles_a_failing_instruments_fetch(error, expected):
    class _DeadClient:
        async def instruments(self):
            raise error

    assert await run_pass(_DeadClient(), _RaisingPolicy(), selected=None) == expected


@pytest.mark.parametrize(
    ("cooldown", "expected"),
    [(45.0, 45.0), (17.0, 30.0), (None, 30.0)],
)
async def test_run_uses_rate_limit_cooldown(monkeypatch, cooldown, expected):
    class _StopLoop(Exception):
        pass

    async def fake_run_pass(*_args):
        return cooldown

    async def fake_sleep(delay):
        assert delay == expected
        raise _StopLoop

    monkeypatch.setattr(arb_module, "run_pass", fake_run_pass)
    monkeypatch.setattr(arb_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        await arb_module.run(arb_module._parser().parse_args(["--interval", "30"]))
