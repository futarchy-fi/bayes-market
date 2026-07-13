"""Binary complete-set central limit order book.

The four public intents share one YES-axis book:

* ``bid yes`` and ``ask no`` are bids (the latter at ``1 - price``);
* ``ask yes`` and ``bid no`` are asks (the latter at ``1 - price``).

An incoming order takes the best canonical price on the opposite side, then
the oldest order at that price.  The intent pair determines settlement:
bid/ask of the same outcome transfers held shares, two bids mint a complete
set, and two asks redeem one.  Thus same-outcome and complete-set liquidity
compete in a single price-time-priority book without special-case precedence.

Credits live exclusively in ``RiskEngine``.  Bid orders have one
``limit_order`` lock each; complete-set collateral is frozen in one lock on
a dedicated escrow account.  Shares and their ask reservations are held here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Mapping

from exchange.core.models import ZERO
from exchange.core.risk_engine import InsufficientBalance, RiskEngine
from exchange.venues.base import (
    InsufficientCredits,
    InvalidTarget,
    MarketClosed,
    TradeRejected,
    UnknownMarket,
    VenueError,
)


PRICE_QUANTUM = Decimal("0.0001")
SIZE_QUANTUM = Decimal("0.01")
MONEY_QUANTUM = Decimal("0.000001")
ONE = Decimal("1")
HALF = Decimal("0.5")


class NoPosition(VenueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise InvalidTarget(f"not a decimal: {value!r}") from exc


def _money(value: Decimal, *, credit: bool = False) -> Decimal:
    """Quantize so debits round up and credits round down (house-safe)."""
    return value.quantize(
        MONEY_QUANTUM, rounding=ROUND_FLOOR if credit else ROUND_CEILING
    )


@dataclass
class BookMarket:
    id: int
    question: str
    escrow_account_id: int
    escrow_lock_id: int | None = None
    outcomes: list[str] = field(default_factory=lambda: ["yes", "no"])
    status: str = "open"
    deadline: str | None = None
    created_at: str = ""
    resolution: str | None = None
    total_sets_minted: Decimal = ZERO


@dataclass
class Order:
    id: int
    account_id: int
    market_id: int
    side: str
    outcome: str
    price: Decimal
    size: Decimal
    remaining: Decimal
    canonical_side: str
    canonical_price: Decimal
    sequence: int
    status: str = "open"
    lock_id: int | None = None
    created_at: str = ""

    @property
    def filled(self) -> Decimal:
        return self.size - self.remaining


@dataclass
class Fill:
    id: int
    market_id: int
    maker_order_id: int
    taker_order_id: int
    price: Decimal
    size: Decimal
    kind: str
    created_at: str


class BookEngine:
    def __init__(self, risk_engine: RiskEngine) -> None:
        self.risk = risk_engine
        self.markets: dict[int, BookMarket] = {}
        self.orders: dict[int, Order] = {}
        self.positions: dict[int, dict[int, dict[str, Decimal]]] = {}
        self.reservations: dict[int, Decimal] = {}
        self.trades: dict[int, list[Fill]] = {}
        self._market_seq = 0
        self._order_seq = 0
        self._trade_seq = 0

    def create_market(self, question: str, deadline: str | None = None) -> BookMarket:
        self._market_seq += 1
        escrow = self.risk.create_account()
        market = BookMarket(
            id=self._market_seq,
            question=question,
            escrow_account_id=escrow.id,
            deadline=deadline,
            created_at=_now(),
        )
        self.markets[market.id] = market
        return market

    def place_order(
        self,
        account_id: int,
        market_id: int,
        side: str,
        outcome: str,
        price: Decimal,
        size: Decimal,
    ) -> Order:
        market = self._open_market(market_id)
        if not isinstance(side, str) or not isinstance(outcome, str):
            raise InvalidTarget("side and outcome must be strings")
        side = {"buy": "bid", "sell": "ask"}.get(side.lower(), side.lower())
        outcome = outcome.lower()
        if side not in ("bid", "ask") or outcome not in market.outcomes:
            raise InvalidTarget("side must be bid/ask and outcome must be yes/no")

        price = _decimal(price)
        size = _decimal(size)
        if not price.is_finite() or not size.is_finite():
            raise InvalidTarget("price and size must be finite")
        if not ZERO < price < ONE or size <= ZERO:
            raise InvalidTarget("price must be in (0, 1) and size must be positive")
        if price != price.quantize(PRICE_QUANTUM) or size != size.quantize(SIZE_QUANTUM):
            raise InvalidTarget("prices support 4dp and sizes support 2dp")

        canonical_side = "bid" if (side, outcome) in (("bid", "yes"), ("ask", "no")) else "ask"
        canonical_price = price if outcome == "yes" else ONE - price

        # Validate custody before allocating an id or touching either state store.
        if side == "bid":
            required = _money(price * size)
            try:
                account = self.risk.get_account(account_id)
            except ValueError as exc:
                raise TradeRejected(str(exc)) from exc
            if account.available_balance < required:
                raise InsufficientCredits(
                    f"account {account_id}: need {required}, have {account.available_balance}"
                )
        else:
            available = self._held(account_id, market_id, outcome) - self._reserved(
                account_id, market_id, outcome
            )
            if available < size:
                raise NoPosition(
                    f"account {account_id}: need {size} {outcome}, have {available}"
                )

        self._order_seq += 1
        order = Order(
            id=self._order_seq,
            account_id=account_id,
            market_id=market_id,
            side=side,
            outcome=outcome,
            price=price,
            size=size,
            remaining=size,
            canonical_side=canonical_side,
            canonical_price=canonical_price,
            sequence=self._order_seq,
            created_at=_now(),
        )
        if side == "bid":
            try:
                lock, _ = self.risk.lock(
                    account_id,
                    market_id,
                    _money(price * size),
                    lock_type="limit_order",
                    trade_id=order.id,
                )
            except InsufficientBalance as exc:  # defensive against a concurrent ledger user
                raise InsufficientCredits(str(exc)) from exc
            order.lock_id = lock.lock_id
        else:
            self.reservations[order.id] = size
        self.orders[order.id] = order
        self._match(order)
        return order

    # Friendly aliases for callers that use buy/sell terminology.
    def buy(self, account_id: int, market_id: int, outcome: str, price: Decimal, size: Decimal) -> Order:
        return self.place_order(account_id, market_id, "bid", outcome, price, size)

    def sell(self, account_id: int, market_id: int, outcome: str, price: Decimal, size: Decimal) -> Order:
        return self.place_order(account_id, market_id, "ask", outcome, price, size)

    def cancel(self, account_id: int, order_id: int) -> Order:
        order = self.orders.get(order_id)
        if order is None or order.account_id != account_id or order.status not in ("open", "partial"):
            raise TradeRejected("only the owner may cancel an open or partial order")
        self._cancel_order(order)
        return order

    def resolve(self, market_id: int, winning_outcome: str) -> BookMarket:
        market = self._open_market(market_id)
        winning_outcome = winning_outcome.lower()
        if winning_outcome not in market.outcomes:
            raise InvalidTarget(f"unknown outcome: {winning_outcome}")
        self._cancel_market_orders(market_id)
        escrow = market.escrow_account_id
        self._release_escrow(market)
        for account_id, by_market in list(self.positions.items()):
            position = by_market.get(market_id)
            if position is None:
                continue
            payout = _money(position[winning_outcome], credit=True)
            if payout:
                self.risk.transfer_available(escrow, account_id, payout, market_id, "book_resolution")
            position["yes"] = position["no"] = ZERO
        market.status = "resolved"
        market.resolution = winning_outcome
        market.total_sets_minted = ZERO
        return market

    def void(self, market_id: int) -> BookMarket:
        market = self._open_market(market_id)
        self._cancel_market_orders(market_id)
        escrow = market.escrow_account_id
        self._release_escrow(market)
        for account_id, by_market in list(self.positions.items()):
            position = by_market.get(market_id)
            if position is None:
                continue
            payout = _money((position["yes"] + position["no"]) * HALF, credit=True)
            if payout:
                self.risk.transfer_available(escrow, account_id, payout, market_id, "book_void")
            position["yes"] = position["no"] = ZERO
        market.status = "void"
        market.total_sets_minted = ZERO
        return market

    def position(self, account_id: int, market_id: int) -> dict[str, Decimal]:
        position = self.positions.get(account_id, {}).get(market_id)
        return dict(position) if position else {"yes": ZERO, "no": ZERO}

    def snapshot(self) -> dict[str, Any]:
        return {
            "marketSeq": self._market_seq,
            "orderSeq": self._order_seq,
            "tradeSeq": self._trade_seq,
            "markets": [self._encode(asdict(m)) for m in self.markets.values()],
            "orders": [self._encode(asdict(o)) for o in self.orders.values()],
            "trades": self._encode({
                market_id: [asdict(fill) for fill in fills]
                for market_id, fills in self.trades.items()
            }),
            "positions": self._encode(self.positions),
            "reservations": self._encode(self.reservations),
        }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any], risk_engine: RiskEngine) -> "BookEngine":
        engine = cls(risk_engine)
        engine._market_seq = int(data.get("marketSeq", 0))
        engine._order_seq = int(data.get("orderSeq", 0))
        engine._trade_seq = int(data.get("tradeSeq", 0))
        for raw in data.get("markets", []):
            item = dict(raw)
            item["id"] = int(item["id"])
            item["escrow_account_id"] = int(item["escrow_account_id"])
            item["escrow_lock_id"] = (
                int(item["escrow_lock_id"])
                if item.get("escrow_lock_id") is not None
                else None
            )
            item["outcomes"] = list(item["outcomes"])
            item["total_sets_minted"] = Decimal(item["total_sets_minted"])
            risk_engine.get_account(item["escrow_account_id"])
            market = BookMarket(**item)
            engine.markets[market.id] = market
        for raw in data.get("orders", []):
            item = dict(raw)
            for key in ("id", "account_id", "market_id", "sequence"):
                item[key] = int(item[key])
            item["lock_id"] = int(item["lock_id"]) if item.get("lock_id") is not None else None
            for key in ("price", "size", "remaining", "canonical_price"):
                item[key] = Decimal(item[key])
            order = Order(**item)
            engine.orders[order.id] = order
        engine.trades = {
            int(market_id): [
                Fill(
                    **{
                        **raw,
                        "id": int(raw["id"]),
                        "market_id": int(raw["market_id"]),
                        "maker_order_id": int(raw["maker_order_id"]),
                        "taker_order_id": int(raw["taker_order_id"]),
                        "price": Decimal(raw["price"]),
                        "size": Decimal(raw["size"]),
                    }
                )
                for raw in fills
            ]
            for market_id, fills in data.get("trades", {}).items()
        }
        engine.positions = {
            int(account_id): {
                int(market_id): {outcome: Decimal(value) for outcome, value in position.items()}
                for market_id, position in by_market.items()
            }
            for account_id, by_market in data.get("positions", {}).items()
        }
        engine.reservations = {
            int(order_id): Decimal(value)
            for order_id, value in data.get("reservations", {}).items()
        }
        return engine

    @classmethod
    def _encode(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): cls._encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._encode(item) for item in value]
        return value

    def _match(self, taker: Order) -> None:
        while taker.remaining:
            makers = [
                order
                for order in self.orders.values()
                if order.market_id == taker.market_id
                and order.canonical_side != taker.canonical_side
                and order.status in ("open", "partial")
                and order.id != taker.id
                and (
                    (taker.canonical_side == "bid" and taker.canonical_price >= order.canonical_price)
                    or (taker.canonical_side == "ask" and order.canonical_price >= taker.canonical_price)
                )
            ]
            if not makers:
                break
            if taker.canonical_side == "bid":
                maker = min(makers, key=lambda order: (order.canonical_price, order.sequence))
            else:
                maker = max(makers, key=lambda order: (order.canonical_price, -order.sequence))
            self._fill(taker, maker, min(taker.remaining, maker.remaining))

    def _fill(self, taker: Order, maker: Order, size: Decimal) -> None:
        intents = {(taker.side, taker.outcome), (maker.side, maker.outcome)}
        if intents == {("bid", "yes"), ("ask", "yes")}:
            kind = "transfer"
            buyer = taker if taker.side == "bid" else maker
            seller = maker if buyer is taker else taker
            price = maker.price
            self._spend_bid(buyer, price, size, seller.account_id)
            self._consume_ask(seller, size)
            self._add_position(buyer.account_id, buyer.market_id, "yes", size)
        elif intents == {("bid", "no"), ("ask", "no")}:
            kind = "transfer"
            buyer = taker if taker.side == "bid" else maker
            seller = maker if buyer is taker else taker
            price = maker.price
            self._spend_bid(buyer, price, size, seller.account_id)
            self._consume_ask(seller, size)
            self._add_position(buyer.account_id, buyer.market_id, "no", size)
        elif taker.side == maker.side == "bid":
            kind = "mint"
            yes = taker if taker.outcome == "yes" else maker
            no = maker if yes is taker else taker
            yes_price = maker.canonical_price
            escrow = self.markets[taker.market_id].escrow_account_id
            self._spend_bid(yes, yes_price, size, escrow)
            self._spend_bid(no, ONE - yes_price, size, escrow)
            self._increase_escrow(self.markets[taker.market_id], size)
            self._add_position(yes.account_id, yes.market_id, "yes", size)
            self._add_position(no.account_id, no.market_id, "no", size)
            self.markets[taker.market_id].total_sets_minted += size
        elif taker.side == maker.side == "ask":
            kind = "redeem"
            yes = taker if taker.outcome == "yes" else maker
            no = maker if yes is taker else taker
            yes_price = maker.canonical_price
            self._consume_ask(yes, size)
            self._consume_ask(no, size)
            market = self.markets[taker.market_id]
            escrow = market.escrow_account_id
            self._decrease_escrow(market, size)
            self.risk.transfer_available(escrow, yes.account_id, _money(yes_price * size, credit=True), taker.market_id, "book_redeem")
            self.risk.transfer_available(escrow, no.account_id, _money((ONE - yes_price) * size, credit=True), taker.market_id, "book_redeem")
            self.markets[taker.market_id].total_sets_minted -= size
        else:  # pragma: no cover - canonical sides make this unreachable
            raise TradeRejected("unsupported intent pair")
        self._trade_seq += 1
        fills = self.trades.setdefault(taker.market_id, [])
        fills.append(Fill(
            id=self._trade_seq,
            market_id=taker.market_id,
            maker_order_id=maker.id,
            taker_order_id=taker.id,
            price=maker.canonical_price,
            size=size,
            kind=kind,
            created_at=_now(),
        ))
        del fills[:-500]
        self._advance(taker, size)
        self._advance(maker, size)

    def _spend_bid(self, order: Order, price: Decimal, size: Decimal, recipient: int) -> None:
        reserved = _money(order.price * size)
        payment = _money(price * size)
        if order.lock_id is None:
            raise TradeRejected("bid has no credit lock")
        self.risk.decrease_lock(order.lock_id, reserved, trade_id=order.id)
        self.risk.transfer_available(order.account_id, recipient, payment, order.market_id, "book_trade")

    def _consume_ask(self, order: Order, size: Decimal) -> None:
        self.reservations[order.id] -= size
        self._add_position(order.account_id, order.market_id, order.outcome, -size)

    def _increase_escrow(self, market: BookMarket, amount: Decimal) -> None:
        amount = _money(amount)
        if market.escrow_lock_id is None:
            lock, _ = self.risk.lock(
                market.escrow_account_id,
                market.id,
                amount,
                lock_type="position",
            )
            market.escrow_lock_id = lock.lock_id
        else:
            self.risk.increase_lock(market.escrow_lock_id, amount)

    def _decrease_escrow(self, market: BookMarket, amount: Decimal) -> None:
        if market.escrow_lock_id is None:
            raise TradeRejected("market escrow has no collateral lock")
        self.risk.decrease_lock(market.escrow_lock_id, _money(amount))
        if market.total_sets_minted == amount:
            market.escrow_lock_id = None

    def _release_escrow(self, market: BookMarket) -> None:
        if market.escrow_lock_id is not None:
            self.risk.release_lock(market.escrow_lock_id)
            market.escrow_lock_id = None

    def _advance(self, order: Order, size: Decimal) -> None:
        order.remaining -= size
        order.status = "filled" if order.remaining == ZERO else "partial"
        if order.status == "filled":
            self.reservations.pop(order.id, None)
            order.lock_id = None

    def _cancel_order(self, order: Order) -> None:
        if order.side == "bid":
            if order.lock_id is not None:
                self.risk.release_lock(order.lock_id, trade_id=order.id)
                order.lock_id = None
        else:
            self.reservations.pop(order.id, None)
        order.status = "cancelled"

    def _cancel_market_orders(self, market_id: int) -> None:
        for order in self.orders.values():
            if order.market_id == market_id and order.status in ("open", "partial"):
                self._cancel_order(order)

    def _open_market(self, market_id: int) -> BookMarket:
        market = self.markets.get(market_id)
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        if market.status != "open":
            raise MarketClosed(f"market {market_id} is {market.status}")
        return market

    def _held(self, account_id: int, market_id: int, outcome: str) -> Decimal:
        return self.positions.get(account_id, {}).get(market_id, {}).get(outcome, ZERO)

    def _reserved(self, account_id: int, market_id: int, outcome: str) -> Decimal:
        return sum(
            (
                amount
                for order_id, amount in self.reservations.items()
                if (order := self.orders.get(order_id)) is not None
                and order.account_id == account_id
                and order.market_id == market_id
                and order.outcome == outcome
            ),
            ZERO,
        )

    def _add_position(self, account_id: int, market_id: int, outcome: str, amount: Decimal) -> None:
        by_market = self.positions.setdefault(account_id, {})
        position = by_market.setdefault(market_id, {"yes": ZERO, "no": ZERO})
        position[outcome] += amount


# Shorter name for venue wiring code.
Engine = BookEngine
OrderBookEngine = BookEngine
