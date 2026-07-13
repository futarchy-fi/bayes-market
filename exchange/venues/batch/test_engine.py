from copy import deepcopy
from decimal import Decimal
import random

import pytest

from exchange.core.risk_engine import RiskEngine
from exchange.venues.base import InsufficientCredits
from exchange.venues.batch.engine import (
    MONEY_QUANTUM, SHARE_QUANTUM, BatchEngine, BatchVenue, _cost, _logit,
)


D = Decimal
TOL = D("2e-11")  # share tick plus Decimal transcendental error


def setup_engine(*, b="10", cap="100", balance="1000", n=1, funded=False):
    risk = RiskEngine()
    funder = risk.create_account()
    risk.mint(funder.id, D("1000"))
    engine = BatchEngine(risk)
    market = engine.create_market(
        "Will it happen?", D(b), D(cap), funder.id if funded else None
    )
    traders = []
    for _ in range(n):
        trader = risk.create_account()
        risk.mint(trader.id, D(balance))
        traders.append(trader)
    return risk, engine, market, traders, funder


def total(risk):
    return sum((account.total for account in risk.accounts.values()), D(0))


def frozen_matches_locks(risk):
    assert all(
        account.frozen_balance == sum((lock.amount for lock in account.locks), D(0))
        for account in risk.accounts.values()
    )


def assert_escrow_identity(risk, engine, market):
    no_shares = sum((
        positions.get(market.id, {}).get("no", D(0))
        for positions in engine.positions.values()
    ), D(0))
    balance = risk.get_account(market.escrow_account_id).available_balance
    assert abs(balance - (no_shares + _cost(market.posted_price, market.b))) <= (
        len(engine.fills.get(market.id, [])) + 1
    ) * MONEY_QUANTUM


@pytest.mark.parametrize("n", [1, 3, 8])
def test_identical_targets_clear_at_target_and_single_is_sequential(n):
    risk, engine, market, traders, _ = setup_engine(n=n)
    for trader in traders:
        engine.submit_order(trader.id, market.id, "yes", D("0.73"), D("100"))
    result = engine.close_round(market.id)
    assert abs(market.posted_price - D("0.73")) <= TOL
    assert abs(D(result["clearingPrice"]) - (
        (_cost(market.posted_price, market.b) - _cost(D("0.5"), market.b)) /
        (market.b * (_logit(market.posted_price) - _logit(D("0.5"))))
    )) <= TOL
    if n == 1:
        assert abs(result["fills"][0].shares - market.b * _logit(D("0.73"))) <= SHARE_QUANTUM


def test_cash_identity_and_escrow_cost_value_each_clear():
    risk, engine, market, traders, _ = setup_engine(n=3)
    previous = market.posted_price
    for trader, outcome, target in zip(traders, ["yes", "yes", "no"], ["0.8", "0.65", "0.7"]):
        engine.submit_order(trader.id, market.id, outcome, D(target), D("100"))
    result = engine.close_round(market.id)
    yes = sum((fill.spend for fill in result["fills"] if fill.outcome == "yes"), D(0))
    no = sum((fill.spend for fill in result["fills"] if fill.outcome == "no"), D(0))
    signed = sum((fill.shares if fill.outcome == "yes" else -fill.shares for fill in result["fills"]), D(0))
    curve = _cost(market.posted_price, market.b) - _cost(previous, market.b)
    paired_no = sum((fill.shares for fill in result["fills"] if fill.outcome == "no"), D(0))
    assert abs(yes + no - (curve + paired_no)) <= 3 * MONEY_QUANTUM
    assert abs(curve - D(result["clearingPrice"]) * signed) < D("1e-25")
    assert_escrow_identity(risk, engine, market)


def test_max_spend_cap_and_replace_adjusts_exact_lock():
    risk, engine, market, (trader,), _ = setup_engine(balance="10")
    first = engine.submit_order(trader.id, market.id, "yes", D("0.99"), D("7"))
    assert trader.frozen_balance == D("7")
    second = engine.submit_order(trader.id, market.id, "yes", D("0.9"), D("3.25"))
    assert first.id != second.id and len(engine.pending) == 1
    assert trader.frozen_balance == D("3.25")
    assert trader.lock_by_id(second.lock_id).amount == D("3.25")
    fill = engine.close_round(market.id)["fills"][0]
    assert fill.spend <= D("3.25")
    assert trader.frozen_balance == D(0)
    frozen_matches_locks(risk)


def test_resubmit_increase_is_atomic_when_balance_is_insufficient():
    risk, engine, market, (trader,), _ = setup_engine(balance="5")
    original = engine.submit_order(trader.id, market.id, "yes", D("0.7"), D("4"))
    before = deepcopy(engine.snapshot()), deepcopy(risk.accounts), list(risk.transactions)
    with pytest.raises(InsufficientCredits):
        engine.submit_order(trader.id, market.id, "yes", D("0.8"), D("6"))
    assert (engine.snapshot(), risk.accounts, risk.transactions) == before
    assert engine.pending[(market.id, trader.id)].id == original.id


def test_per_participant_net_cap():
    _, engine, market, traders, _ = setup_engine(cap="1.5", n=2)
    for trader in traders:
        engine.submit_order(trader.id, market.id, "yes", D("0.99"), D("100"))
    fills = engine.close_round(market.id)["fills"]
    assert all(fill.shares <= D("1.5") for fill in fills)


def test_symmetric_offset_crosses_at_mid_without_curve_move():
    risk, engine, market, traders, _ = setup_engine(n=2)
    engine.submit_order(traders[0].id, market.id, "yes", D("0.8"), D("100"))
    engine.submit_order(traders[1].id, market.id, "no", D("0.8"), D("100"))
    result = engine.close_round(market.id)
    assert market.posted_price == D("0.5")
    assert D(result["clearingPrice"]) == D("0.5")
    assert result["fills"][0].shares == result["fills"][1].shares
    assert_escrow_identity(risk, engine, market)


def test_resolve_pays_winners_exactly_and_sweeps_funder():
    risk, engine, market, traders, funder = setup_engine(n=2, funded=True)
    funder_after_funding = funder.available_balance
    engine.submit_order(traders[0].id, market.id, "yes", D("0.75"), D("100"))
    engine.submit_order(traders[1].id, market.id, "no", D("0.65"), D("100"))
    engine.close_round(market.id)
    yes_shares = engine.position(traders[0].id, market.id)["yes"]
    before = traders[0].available_balance
    locked = engine.submit_order(traders[0].id, market.id, "yes", D("0.8"), D("2"))
    assert locked.lock_id
    engine.resolve(market.id, "yes")
    assert traders[0].available_balance == before + yes_shares
    assert risk.get_account(market.escrow_account_id).available_balance == D(0)
    assert funder.available_balance >= funder_after_funding
    frozen_matches_locks(risk)


def test_void_refunds_exact_cumulative_cost_basis():
    risk, engine, market, (trader,), funder = setup_engine(funded=True)
    before = trader.total
    for target in ["0.7", "0.8", "0.6"]:
        engine.submit_order(trader.id, market.id, "yes", D(target), D("100"))
        engine.close_round(market.id)
    engine.submit_order(trader.id, market.id, "yes", D("0.9"), D("7"))
    engine.void(market.id)
    assert trader.total == before
    assert risk.get_account(market.escrow_account_id).total == D(0)
    frozen_matches_locks(risk)


def test_seeded_randomized_multi_round_conservation():
    rng = random.Random(9173)
    risk, engine, market, traders, _ = setup_engine(n=6)
    initial = total(risk)
    for _ in range(20):
        posted = market.posted_price
        for trader in rng.sample(traders, rng.randint(1, len(traders))):
            outcome = rng.choice(["yes", "no"])
            current = posted if outcome == "yes" else D(1) - posted
            target = current + (D("0.95") - current) * D(str(rng.random()))
            engine.submit_order(trader.id, market.id, outcome, target, D(str(rng.uniform(.01, 15))))
            frozen_matches_locks(risk)
        engine.close_round(market.id)
        assert total(risk) == initial
        frozen_matches_locks(risk)
        assert_escrow_identity(risk, engine, market)
    engine.resolve(market.id, rng.choice(["yes", "no"]))
    assert total(risk) == initial
    frozen_matches_locks(risk)


def test_snapshot_roundtrip_mid_round_settles_identically():
    risk, engine, market, traders, _ = setup_engine(n=3)
    for trader, outcome, target, spend in zip(
        traders, ["yes", "no", "yes"], ["0.8", "0.7", "0.65"], ["4", "2", "8"]
    ):
        engine.submit_order(trader.id, market.id, outcome, D(target), D(spend))
    twin_risk = deepcopy(risk)
    twin = BatchEngine.from_snapshot(deepcopy(engine.snapshot()), twin_risk)
    left, right = engine.close_round(market.id), twin.close_round(market.id)
    assert left["clearingPrice"] == right["clearingPrice"]
    assert [(f.shares, f.price, f.spend) for f in left["fills"]] == [
        (f.shares, f.price, f.spend) for f in right["fills"]
    ]
    assert engine.snapshot() == twin.snapshot()
    assert {
        account_id: (account.available_balance, account.frozen_balance)
        for account_id, account in risk.accounts.items()
    } == {
        account_id: (account.available_balance, account.frozen_balance)
        for account_id, account in twin_risk.accounts.items()
    }
    frozen_matches_locks(risk)
    frozen_matches_locks(twin_risk)


def test_public_market_and_history_never_disclose_orders():
    risk, engine, market, (trader,), _ = setup_engine()
    venue = BatchVenue(engine)
    venue.place(trader.id, {
        "marketId": market.id, "outcome": "yes", "target": "0.73", "maxSpend": "5"
    })
    public = venue.get_market(market.id)
    assert "pending" not in str(public).lower() and "account" not in str(public).lower()
    assert venue.orders_for(trader.id)[0]["target"] == "0.73"
    venue.close_round(market.id)
    history = venue.get_market(market.id)["roundHistory"]
    assert set(history[0]) == {"round", "clearingPrice", "participants"}
