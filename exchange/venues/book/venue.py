"""Venue adapter and read models for the complete-set order book."""

from decimal import Decimal

from exchange.core.models import ZERO
from exchange.core.risk_engine import RiskEngine
from exchange.venues.base import InvalidTarget, UnknownMarket
from exchange.venues.book.engine import (
    ONE,
    PRICE_QUANTUM,
    SIZE_QUANTUM,
    BookEngine,
    BookMarket,
    Fill,
    Order,
    _money,
)


class BookVenue:
    kind = "book"

    def __init__(self, engine: BookEngine):
        self.engine = engine

    @classmethod
    def from_snapshot(cls, data: dict, risk_engine: RiskEngine) -> "BookVenue":
        return cls(BookEngine.from_snapshot(data, risk_engine))

    def market_ids(self) -> list[int]:
        return list(self.engine.markets)

    def get_market(self, market_id: int) -> dict:
        market = self.engine.markets.get(int(market_id))
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        depth = self.orderbook(market.id)
        fills = self.engine.trades.get(market.id, [])
        return {
            "id": market.id,
            "question": market.question,
            "status": market.status,
            "outcomes": list(market.outcomes),
            "bestBid": depth["bids"][0]["price"] if depth["bids"] else None,
            "bestAsk": depth["asks"][0]["price"] if depth["asks"] else None,
            "lastPrice": str(fills[-1].price) if fills else None,
            "setsMinted": str(market.total_sets_minted),
            "deadline": market.deadline,
            "createdAt": market.created_at,
            "resolution": market.resolution,
        }

    def quote(self, account_id: int, payload: dict) -> dict:
        market_id, side, outcome, price, size = self._parse_order(payload)
        market = self.engine._open_market(market_id)
        canonical_side, canonical_price = self._canonical(side, outcome, price)
        makers = [
            order for order in self.engine.orders.values()
            if order.market_id == market.id
            and order.canonical_side != canonical_side
            and order.status in ("open", "partial")
            and (
                (canonical_side == "bid" and canonical_price >= order.canonical_price)
                or (canonical_side == "ask" and order.canonical_price >= canonical_price)
            )
        ]
        makers.sort(
            key=lambda order: (
                order.canonical_price if canonical_side == "bid"
                else -order.canonical_price,
                order.sequence,
            )
        )
        remaining = size
        value = ZERO
        for maker in makers:
            fill = min(remaining, maker.remaining)
            execution_price = (
                maker.canonical_price if outcome == "yes"
                else ONE - maker.canonical_price
            )
            value += execution_price * fill
            remaining -= fill
            if remaining == ZERO:
                break
        fillable = size - remaining
        average = value / fillable if fillable else ZERO
        result = {
            "fillableNow": str(fillable),
            "avgPrice": str(average),
            "restingSize": str(remaining),
        }
        if side == "bid":
            result["cost"] = str(_money(value + price * remaining))
        else:
            result["proceeds"] = str(_money(value, credit=True))
        return result

    def place(self, account_id: int, payload: dict) -> dict:
        market_id, side, outcome, price, size = self._parse_order(payload)
        return self.order_record(self.engine.place_order(
            account_id, market_id, side, outcome, price, size
        ))

    def resolve(self, market_id: int, outcome_id: str) -> dict:
        market_id = int(market_id)
        open_orders = self._open_order_ids(market_id)
        settled = self._position_accounts(market_id)
        market = self.engine.resolve(market_id, outcome_id)
        return self._settlement_report(market, open_orders, settled)

    def void(self, market_id: int) -> dict:
        market_id = int(market_id)
        open_orders = self._open_order_ids(market_id)
        settled = self._position_accounts(market_id)
        market = self.engine.void(market_id)
        return self._settlement_report(market, open_orders, settled)

    def snapshot(self) -> dict:
        return self.engine.snapshot()

    def stats(self) -> dict:
        return {
            "markets": len(self.engine.markets),
            "orders_or_trades": len(self.engine.orders) + sum(
                len(fills) for fills in self.engine.trades.values()
            ),
        }

    def create_market(self, question: str, deadline: str | None = None) -> dict:
        market = self.engine.create_market(question, deadline)
        return self.get_market(market.id)

    def cancel(self, account_id: int, order_id: int) -> dict:
        return self.order_record(self.engine.cancel(account_id, order_id))

    def orders_for(self, account_id: int) -> list[dict]:
        return [
            self.order_record(order)
            for order in self.engine.orders.values()
            if order.account_id == account_id
        ]

    def positions_for(self, account_id: int) -> list[dict]:
        return [
            {
                "marketId": market_id,
                "yes": str(position.get("yes", ZERO)),
                "no": str(position.get("no", ZERO)),
            }
            for market_id, position in self.engine.positions.get(account_id, {}).items()
        ]

    def orderbook(self, market_id: int) -> dict:
        if int(market_id) not in self.engine.markets:
            raise UnknownMarket(f"market {market_id} not found")
        yes = self._depth(int(market_id))
        no = {
            "bids": self._invert(yes["asks"]),
            "asks": self._invert(yes["bids"]),
        }
        return {
            "marketId": int(market_id),
            "bids": yes["bids"],
            "asks": yes["asks"],
            "outcomes": {"yes": yes, "no": no},
        }

    def trades_for(self, market_id: int, limit: int = 100) -> list[dict]:
        if int(market_id) not in self.engine.markets:
            raise UnknownMarket(f"market {market_id} not found")
        return [
            self.fill_record(fill)
            for fill in self.engine.trades.get(int(market_id), [])[-limit:]
        ]

    @staticmethod
    def order_record(order: Order) -> dict:
        return {
            "orderId": order.id,
            "accountId": order.account_id,
            "marketId": order.market_id,
            "side": order.side,
            "outcome": order.outcome,
            "price": str(order.price),
            "size": str(order.size),
            "filled": str(order.filled),
            "remaining": str(order.remaining),
            "status": order.status,
            "createdAt": order.created_at,
        }

    @staticmethod
    def fill_record(fill: Fill) -> dict:
        return {
            "tradeId": fill.id,
            "marketId": fill.market_id,
            "makerOrderId": fill.maker_order_id,
            "takerOrderId": fill.taker_order_id,
            "price": str(fill.price),
            "size": str(fill.size),
            "kind": fill.kind,
            "createdAt": fill.created_at,
        }

    @staticmethod
    def _parse_order(payload: dict) -> tuple[int, str, str, Decimal, Decimal]:
        try:
            market_id = int(payload["marketId"])
            side = payload["side"].lower()
            outcome = payload["outcome"].lower()
            price = Decimal(str(payload["price"]))
            size = Decimal(str(payload["size"]))
        except (KeyError, AttributeError, TypeError, ValueError) as err:
            raise InvalidTarget(str(err)) from err
        if side not in ("bid", "ask") or outcome not in ("yes", "no"):
            raise InvalidTarget("side must be bid/ask and outcome must be yes/no")
        if not price.is_finite() or not size.is_finite():
            raise InvalidTarget("price and size must be finite")
        if not ZERO < price < ONE or size <= ZERO:
            raise InvalidTarget("price must be in (0, 1) and size must be positive")
        if price != price.quantize(PRICE_QUANTUM) or size != size.quantize(SIZE_QUANTUM):
            raise InvalidTarget("prices support 4dp and sizes support 2dp")
        return market_id, side, outcome, price, size

    @staticmethod
    def _canonical(side: str, outcome: str, price: Decimal) -> tuple[str, Decimal]:
        canonical_side = "bid" if (side, outcome) in (("bid", "yes"), ("ask", "no")) else "ask"
        return canonical_side, price if outcome == "yes" else ONE - price

    def _depth(self, market_id: int) -> dict:
        levels: dict[str, dict[Decimal, Decimal]] = {"bid": {}, "ask": {}}
        for order in self.engine.orders.values():
            if order.market_id == market_id and order.status in ("open", "partial"):
                side = levels[order.canonical_side]
                side[order.canonical_price] = side.get(order.canonical_price, ZERO) + order.remaining
        return {
            "bids": [
                {"price": str(price), "size": str(size)}
                for price, size in sorted(levels["bid"].items(), reverse=True)
            ],
            "asks": [
                {"price": str(price), "size": str(size)}
                for price, size in sorted(levels["ask"].items())
            ],
        }

    @staticmethod
    def _invert(levels: list[dict]) -> list[dict]:
        return [
            {"price": str(ONE - Decimal(level["price"])), "size": level["size"]}
            for level in levels
        ]

    def _open_order_ids(self, market_id: int) -> list[int]:
        return [
            order.id for order in self.engine.orders.values()
            if order.market_id == market_id and order.status in ("open", "partial")
        ]

    def _position_accounts(self, market_id: int) -> list[int]:
        return [
            account_id for account_id, markets in self.engine.positions.items()
            if any(markets.get(market_id, {}).values())
        ]

    def _settlement_report(
        self, market: BookMarket, cancelled: list[int], settled: list[int]
    ) -> dict:
        return {
            "market": self.get_market(market.id),
            "cancelledOrders": cancelled,
            "settledAccounts": settled,
        }
