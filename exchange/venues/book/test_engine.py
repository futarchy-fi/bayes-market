from copy import deepcopy
from decimal import Decimal
import random

import pytest

from exchange.core.models import ZERO, reset_counters
from exchange.core.risk_engine import RiskEngine
from exchange.venues.book.engine import (
    BookEngine,
    InsufficientCredits,
    InvalidTarget,
    MarketClosed,
    NoPosition,
    TradeRejected,
)


D = Decimal


@pytest.fixture(autouse=True)
def clean_ids():
    reset_counters()


@pytest.fixture
def book():
    risk = RiskEngine()
    accounts = [risk.create_account() for _ in range(4)]
    for account in accounts:
        risk.mint(account.id, D("100"))
    engine = BookEngine(risk)
    market = engine.create_market("Will it ship?")
    return risk, engine, market, accounts


def totals(risk):
    return sum((account.total for account in risk.accounts.values()), ZERO)


def assert_locks(risk):
    for account in risk.accounts.values():
        assert account.frozen_balance == sum((lock.amount for lock in account.locks), ZERO)


def seed_sets(engine, market, yes_account, no_account, size=D("10.00")):
    engine.buy(no_account.id, market.id, "no", D("0.4000"), size)
    engine.buy(yes_account.id, market.id, "yes", D("0.6000"), size)


def test_direct_match_uses_maker_price_and_releases_taker_surplus(book):
    risk, engine, market, (seller, buyer, *_rest) = book
    seed_sets(engine, market, seller, _rest[0], D("2.00"))
    before_seller = seller.available_balance
    order = engine.sell(seller.id, market.id, "yes", D("0.3000"), D("2.00"))
    taker = engine.buy(buyer.id, market.id, "yes", D("0.5000"), D("2.00"))

    assert order.status == taker.status == "filled"
    assert buyer.available_balance == D("99.400000")
    assert buyer.frozen_balance == ZERO
    assert seller.available_balance == before_seller + D("0.600000")
    assert engine.position(buyer.id, market.id)["yes"] == D("2.00")
    assert_locks(risk)


def test_mint_cross_maker_split_and_escrow(book):
    risk, engine, market, (yes, no, *_rest) = book
    maker = engine.buy(no.id, market.id, "no", D("0.4500"), D("3.00"))
    taker = engine.buy(yes.id, market.id, "yes", D("0.6000"), D("3.00"))

    assert maker.status == taker.status == "filled"
    assert yes.available_balance == D("98.350000")  # 3 * (1 - .45)
    assert no.available_balance == D("98.650000")
    escrow = risk.get_account(market.escrow_account_id)
    assert escrow.available_balance == ZERO
    assert escrow.frozen_balance == D("3.000000")
    assert engine.position(yes.id, market.id) == {"yes": D("3.00"), "no": ZERO}
    assert engine.position(no.id, market.id) == {"yes": ZERO, "no": D("3.00")}
    assert market.total_sets_minted == D("3.00")
    assert totals(risk) == D("400")


def test_redeem_cross_pays_maker_split_and_burns_set(book):
    risk, engine, market, (yes, no, *_rest) = book
    seed_sets(engine, market, yes, no, D("4.00"))
    yes_before, no_before = yes.available_balance, no.available_balance
    maker = engine.sell(no.id, market.id, "no", D("0.4200"), D("4.00"))
    taker = engine.sell(yes.id, market.id, "yes", D("0.5500"), D("4.00"))

    assert maker.status == taker.status == "filled"
    assert yes.available_balance == yes_before + D("2.320000")
    assert no.available_balance == no_before + D("1.680000")
    assert risk.get_account(market.escrow_account_id).total == ZERO
    assert engine.position(yes.id, market.id)["yes"] == ZERO
    assert engine.position(no.id, market.id)["no"] == ZERO
    assert market.total_sets_minted == ZERO
    assert totals(risk) == D("400")


def test_price_time_priority_and_partial_fill_across_makers(book):
    _risk, engine, market, (m1, m2, taker, no) = book
    seed_sets(engine, market, m1, no, D("5.00"))
    seed_sets(engine, market, m2, no, D("5.00"))
    old = engine.sell(m1.id, market.id, "yes", D("0.4000"), D("2.00"))
    newer = engine.sell(m2.id, market.id, "yes", D("0.4000"), D("2.00"))
    best = engine.sell(m2.id, market.id, "yes", D("0.3500"), D("1.00"))

    engine.buy(taker.id, market.id, "yes", D("0.5000"), D("4.00"))
    assert best.status == old.status == "filled"
    assert newer.status == "partial" and newer.remaining == D("1.00")
    assert taker.available_balance == D("98.450000")


def test_cancel_releases_exact_remaining_bid_lock(book):
    risk, engine, market, (maker, buyer, no, *_rest) = book
    seed_sets(engine, market, maker, no, D("1.00"))
    engine.sell(maker.id, market.id, "yes", D("0.4000"), D("1.00"))
    order = engine.buy(buyer.id, market.id, "yes", D("0.5000"), D("3.00"))
    assert order.remaining == D("2.00")
    assert buyer.frozen_balance == D("1.000000")

    engine.cancel(buyer.id, order.id)
    assert order.status == "cancelled"
    assert buyer.available_balance == D("99.600000")
    assert buyer.frozen_balance == ZERO
    assert_locks(risk)


def test_rejections_have_zero_state_change(book):
    risk, engine, market, (poor, seller, *_rest) = book
    risk.transfer_available(poor.id, seller.id, D("100"))
    before = (engine.snapshot(), deepcopy(risk.accounts), list(risk.transactions))
    with pytest.raises(InsufficientCredits):
        engine.buy(poor.id, market.id, "yes", D("0.9000"), D("1.00"))
    assert (engine.snapshot(), risk.accounts, risk.transactions) == before

    before = (engine.snapshot(), deepcopy(risk.accounts), list(risk.transactions))
    with pytest.raises(NoPosition):
        engine.sell(seller.id, market.id, "yes", D("0.5000"), D("1.00"))
    assert (engine.snapshot(), risk.accounts, risk.transactions) == before
    with pytest.raises(InvalidTarget):
        engine.buy(seller.id, market.id, "yes", D("1.0000"), D("1.00"))


def test_resolve_refunds_open_orders_and_pays_winners(book):
    risk, engine, market, (yes, no, open_bid, *_rest) = book
    seed_sets(engine, market, yes, no, D("5.00"))
    engine.buy(open_bid.id, market.id, "yes", D("0.2000"), D("3.00"))
    before = totals(risk)

    engine.resolve(market.id, "yes")
    assert yes.available_balance == D("102.000000")
    assert no.available_balance == D("98.000000")
    assert open_bid.available_balance == D("100.000000")
    assert risk.get_account(market.escrow_account_id).total == ZERO
    assert totals(risk) == before
    assert all(order.status not in ("open", "partial") for order in engine.orders.values())
    assert_locks(risk)
    with pytest.raises(MarketClosed):
        engine.buy(yes.id, market.id, "yes", D("0.5000"), D("1.00"))


def test_void_pays_half_per_share(book):
    risk, engine, market, (yes, no, *_rest) = book
    seed_sets(engine, market, yes, no, D("5.00"))
    before = totals(risk)
    engine.void(market.id)

    assert yes.available_balance == D("99.500000")
    assert no.available_balance == D("100.500000")
    assert risk.get_account(market.escrow_account_id).total == ZERO
    assert totals(risk) == before
    assert_locks(risk)


@pytest.mark.parametrize("settlement", ["resolve", "void"])
def test_seeded_random_sequence_conserves_and_keeps_locks_exact(book, settlement):
    risk, engine, market, accounts = book
    rng = random.Random(8675309)
    initial = totals(risk)
    seed_sets(engine, market, accounts[0], accounts[1], D("20.00"))
    assert totals(risk) == initial
    assert_locks(risk)

    open_ids = []
    for _ in range(80):
        account = rng.choice(accounts)
        outcome = rng.choice(("yes", "no"))
        side = rng.choice(("bid", "ask"))
        price = D(rng.randrange(20, 81)) / D("100")
        size = D(rng.randrange(1, 4)).quantize(D("0.01"))
        try:
            order = engine.place_order(account.id, market.id, side, outcome, price, size)
            if order.status in ("open", "partial"):
                open_ids.append(order.id)
        except (InsufficientCredits, NoPosition):
            pass
        if open_ids and rng.random() < 0.25:
            order_id = rng.choice(open_ids)
            order = engine.orders[order_id]
            if order.status in ("open", "partial"):
                engine.cancel(order.account_id, order.id)
        assert totals(risk) == initial
        assert_locks(risk)

    if settlement == "resolve":
        engine.resolve(market.id, rng.choice(("yes", "no")))
    else:
        engine.void(market.id)
    assert totals(risk) == initial
    assert_locks(risk)
    assert all(account.frozen_balance == ZERO for account in risk.accounts.values())


def test_snapshot_roundtrip_mid_book_settles_like_twin(book):
    risk, engine, market, (yes, no, buyer, *_rest) = book
    seed_sets(engine, market, yes, no, D("6.00"))
    engine.sell(yes.id, market.id, "yes", D("0.4300"), D("4.00"))
    engine.buy(buyer.id, market.id, "yes", D("0.5000"), D("2.00"))
    engine.buy(no.id, market.id, "no", D("0.3000"), D("3.00"))

    twin_risk = deepcopy(risk)
    twin = BookEngine.from_snapshot(engine.snapshot(), twin_risk)
    engine.resolve(market.id, "no")
    twin.resolve(market.id, "no")

    assert twin.snapshot() == engine.snapshot()
    assert {
        account_id: (account.available_balance, account.frozen_balance, account.locks)
        for account_id, account in twin_risk.accounts.items()
    } == {
        account_id: (account.available_balance, account.frozen_balance, account.locks)
        for account_id, account in risk.accounts.items()
    }
    assert_locks(twin_risk)


def test_cancel_requires_owner_and_live_order(book):
    _risk, engine, market, (owner, stranger, *_rest) = book
    order = engine.buy(owner.id, market.id, "yes", D("0.5000"), D("1.00"))
    with pytest.raises(TradeRejected):
        engine.cancel(stranger.id, order.id)
    engine.cancel(owner.id, order.id)
    with pytest.raises(TradeRejected):
        engine.cancel(owner.id, order.id)
