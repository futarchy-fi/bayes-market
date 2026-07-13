"""Sealed-round binary LMSR with competitive (1/N) order sizing.

Orders are private until they disappear at the end of their round; the only
public round output is clearing price and participant count.  Sizes use a
1e-12 share tick.  After at most three max-spend repricings, every size is
rounded toward zero to that tick and, only if Decimal rounding still puts an
order over budget, reduced one more tick before the final clearing price is
computed.

The binary cost function is ``C(q_yes, q_no) = q_no - b*ln(1-p)``.  Therefore
the escrow invariant is ``balance = total_no_shares + C(posted_price)``; at
creation this is ``b*ln(2)``.  This is the two-security form of "initial
subsidy + C-value" and includes complete sets created by offsetting flow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Any, Mapping

from exchange.core.models import ZERO
from exchange.core.risk_engine import InsufficientBalance, RiskEngine
from exchange.venues.base import (
    InsufficientCredits,
    InvalidOutcome,
    InvalidTarget,
    MarketClosed,
    TradeRejected,
    UnknownMarket,
    VenueError,
)


ONE = Decimal("1")
HALF = Decimal("0.5")
SHARE_QUANTUM = Decimal("0.000000000001")
MONEY_QUANTUM = Decimal("0.000000000001")


class ClearingError(VenueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise InvalidTarget(f"{name} is not a decimal") from exc
    if not result.is_finite():
        raise InvalidTarget(f"{name} must be finite")
    return result


def _logit(p: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return (p / (ONE - p)).ln()


def _logistic(value: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return ONE / (ONE + (-value).exp())


def _cost(p: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return -b * (ONE - p).ln()


def _toward_zero(value: Decimal) -> Decimal:
    sign = ONE if value >= ZERO else -ONE
    return sign * (abs(value) / SHARE_QUANTUM).to_integral_value(
        rounding=ROUND_FLOOR
    ) * SHARE_QUANTUM


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_FLOOR)


@dataclass
class BatchMarket:
    id: int
    question: str
    escrow_account_id: int
    b: Decimal
    net_cap: Decimal
    funding_account_id: int | None = None
    posted_price: Decimal = HALF
    round: int = 1
    round_history: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=lambda: ["yes", "no"])
    status: str = "open"
    resolution: str | None = None
    deadline: str | None = None
    created_at: str = ""


@dataclass
class SealedOrder:
    id: int
    account_id: int
    market_id: int
    round: int
    outcome: str
    target: Decimal
    max_spend: Decimal
    lock_id: int
    created_at: str


@dataclass
class BatchFill:
    id: int
    order_id: int
    account_id: int
    market_id: int
    round: int
    outcome: str
    target: Decimal
    shares: Decimal
    price: Decimal
    spend: Decimal
    created_at: str


class BatchEngine:
    def __init__(self, risk_engine: RiskEngine) -> None:
        self.risk = risk_engine
        self.markets: dict[int, BatchMarket] = {}
        self.pending: dict[tuple[int, int], SealedOrder] = {}
        self.fills: dict[int, list[BatchFill]] = {}
        self.positions: dict[int, dict[int, dict[str, Decimal]]] = {}
        self.cost_basis: dict[int, dict[int, Decimal]] = {}
        self._market_seq = self._order_seq = self._fill_seq = 0

    def create_market(
        self,
        question: str,
        b: Decimal = Decimal("100"),
        net_cap: Decimal = Decimal("100"),
        funding_account_id: int | None = None,
        deadline: str | None = None,
    ) -> BatchMarket:
        b, net_cap = _decimal(b, "b"), _decimal(net_cap, "net cap")
        if b <= ZERO or net_cap <= ZERO:
            raise InvalidTarget("b and net cap must be positive")
        self._market_seq += 1
        escrow = self.risk.create_account()
        subsidy = b * Decimal(2).ln()
        if funding_account_id is None:
            self.risk.mint(escrow.id, subsidy)
        else:
            try:
                self.risk.transfer_available(
                    funding_account_id, escrow.id, subsidy,
                    self._market_seq, "batch_market_funding",
                )
            except (InsufficientBalance, ValueError) as exc:
                raise InsufficientCredits(str(exc)) from exc
        market = BatchMarket(
            id=self._market_seq,
            question=question,
            escrow_account_id=escrow.id,
            b=b,
            net_cap=net_cap,
            funding_account_id=funding_account_id,
            deadline=deadline,
            created_at=_now(),
        )
        self.markets[market.id] = market
        return market

    def submit_order(
        self, account_id: int, market_id: int, outcome: str,
        target: Decimal, max_spend: Decimal,
    ) -> SealedOrder:
        market = self._open_market(market_id)
        if not isinstance(outcome, str):
            raise InvalidOutcome("outcome must be yes or no")
        outcome = outcome.lower()
        if outcome not in market.outcomes:
            raise InvalidOutcome(f"unknown outcome: {outcome}")
        target = _decimal(target, "target")
        max_spend = _decimal(max_spend, "maxSpend")
        if not ZERO < target < ONE:
            raise InvalidTarget("target must be in (0, 1)")
        if max_spend <= ZERO:
            raise InvalidTarget("maxSpend must be positive")
        try:
            self.risk.get_account(account_id)
        except ValueError as exc:
            raise TradeRejected(str(exc)) from exc

        old = self.pending.get((market.id, account_id))
        try:
            if old is None:
                lock, _ = self.risk.lock(
                    account_id, market.id, max_spend,
                    lock_type="batch_order", trade_id=self._order_seq + 1,
                )
                lock_id = lock.lock_id
            else:
                lock_id = old.lock_id
                delta = max_spend - old.max_spend
                if delta > ZERO:
                    self.risk.increase_lock(lock_id, delta, trade_id=old.id)
                elif delta < ZERO:
                    self.risk.decrease_lock(lock_id, -delta, trade_id=old.id)
        except InsufficientBalance as exc:
            raise InsufficientCredits(str(exc)) from exc

        self._order_seq += 1
        order = SealedOrder(
            self._order_seq, account_id, market.id, market.round, outcome,
            target, max_spend, lock_id, _now(),
        )
        self.pending[(market.id, account_id)] = order
        return order

    def close_round(self, market_id: int) -> dict[str, Any]:
        market = self._open_market(market_id)
        orders = [
            order for (mid, _), order in self.pending.items() if mid == market.id
        ]
        orders.sort(key=lambda order: order.id)
        participants = len(orders)
        if not orders:
            result = self._finish_round(market, market.posted_price, 0)
            return {**result, "fills": []}

        p = market.posted_price
        sizes: dict[int, Decimal] = {}
        for order in orders:
            target_yes = order.target if order.outcome == "yes" else ONE - order.target
            desired = market.b * (_logit(target_yes) - _logit(p)) / participants
            limit = min(market.net_cap, abs(market.b * (_logit(target_yes) - _logit(p))))
            sizes[order.id] = max(-limit, min(limit, desired))

        price = p
        for _ in range(3):
            price = self._clearing_price(p, market.b, sum(sizes.values(), ZERO))
            changed = False
            for order in orders:
                unit = price if sizes[order.id] >= ZERO else ONE - price
                affordable = order.max_spend / unit
                if abs(sizes[order.id]) > affordable:
                    sizes[order.id] = (ONE if sizes[order.id] >= ZERO else -ONE) * affordable
                    changed = True
            if not changed:
                break

        sizes = {order_id: _toward_zero(size) for order_id, size in sizes.items()}
        price = self._clearing_price(p, market.b, sum(sizes.values(), ZERO))
        for order in orders:
            size = sizes[order.id]
            unit = price if size >= ZERO else ONE - price
            if unit * abs(size) > order.max_spend:
                sizes[order.id] = size - (SHARE_QUANTUM if size > ZERO else -SHARE_QUANTUM)
        net = sum(sizes.values(), ZERO)
        price = self._clearing_price(p, market.b, net)

        round_fills = []
        escrow = market.escrow_account_id
        for order in orders:
            signed = sizes[order.id]
            shares = abs(signed)
            unit = price if signed >= ZERO else ONE - price
            spend = _money(unit * shares)
            if spend > order.max_spend:
                raise ClearingError("final tick clip exceeded maxSpend")
            self.risk.release_lock(order.lock_id, trade_id=order.id)
            if spend:
                self.risk.transfer_available(
                    order.account_id, escrow, spend, market.id, "batch_fill"
                )
            outcome = "yes" if signed >= ZERO else "no"
            self._add_position(order.account_id, market.id, outcome, shares)
            by_market = self.cost_basis.setdefault(order.account_id, {})
            by_market[market.id] = by_market.get(market.id, ZERO) + spend
            self._fill_seq += 1
            fill = BatchFill(
                self._fill_seq, order.id, order.account_id, market.id,
                market.round, outcome, order.target, shares, unit, spend,
                order.created_at,
            )
            self.fills.setdefault(market.id, []).append(fill)
            round_fills.append(fill)
            del self.pending[(market.id, order.account_id)]

        market.posted_price = _logistic(_logit(p) + net / market.b)
        if abs(market.posted_price - _logistic(_logit(p) + net / market.b)) > SHARE_QUANTUM:
            raise ClearingError("posted price mismatch")
        self._assert_escrow(market)
        result = self._finish_round(market, price, participants)
        return {**result, "fills": round_fills}

    def resolve(self, market_id: int, outcome: str) -> BatchMarket:
        market = self._open_market(market_id)
        outcome = outcome.lower()
        if outcome not in market.outcomes:
            raise InvalidOutcome(f"unknown outcome: {outcome}")
        self._release_pending(market.id)
        escrow = market.escrow_account_id
        for account_id, markets in self.positions.items():
            position = markets.get(market.id)
            if not position:
                continue
            payout = position[outcome]
            if payout:
                self.risk.transfer_available(
                    escrow, account_id, payout, market.id, "batch_resolution"
                )
            position["yes"] = position["no"] = ZERO
        market.status, market.resolution = "resolved", outcome
        self._sweep_escrow(market)
        return market

    def void(self, market_id: int) -> BatchMarket:
        market = self._open_market(market_id)
        self._release_pending(market.id)
        escrow = market.escrow_account_id
        for account_id, markets in self.cost_basis.items():
            refund = markets.get(market.id, ZERO)
            if refund:
                self.risk.transfer_available(
                    escrow, account_id, refund, market.id, "batch_void"
                )
            markets[market.id] = ZERO
        for markets in self.positions.values():
            if market.id in markets:
                markets[market.id]["yes"] = markets[market.id]["no"] = ZERO
        market.status = "void"
        self._sweep_escrow(market)
        return market

    def estimate(self, market_id: int, outcome: str, target: Decimal, max_spend: Decimal) -> dict:
        market = self._open_market(market_id)
        outcome = outcome.lower()
        if outcome not in market.outcomes:
            raise InvalidOutcome(f"unknown outcome: {outcome}")
        target, max_spend = _decimal(target, "target"), _decimal(max_spend, "maxSpend")
        if not ZERO < target < ONE or max_spend <= ZERO:
            raise InvalidTarget("target must be in (0, 1) and maxSpend positive")
        target_yes = target if outcome == "yes" else ONE - target
        signed = market.b * (_logit(target_yes) - _logit(market.posted_price))
        signed = max(-market.net_cap, min(market.net_cap, signed))
        price = self._clearing_price(market.posted_price, market.b, signed)
        shares = min(abs(signed), max_spend / (price if signed >= ZERO else ONE - price))
        shares = _toward_zero(shares)
        signed = shares if signed >= ZERO else -shares
        price = self._clearing_price(market.posted_price, market.b, signed)
        return {
            "marketId": market.id,
            "outcome": outcome,
            "shares": str(shares),
            "price": str(price if signed >= ZERO else ONE - price),
            "estimatedSpend": str((price if signed >= ZERO else ONE - price) * shares),
            "cost": str(max_spend),
        }

    def position(self, account_id: int, market_id: int) -> dict[str, Decimal]:
        return dict(self.positions.get(account_id, {}).get(
            market_id, {"yes": ZERO, "no": ZERO}
        ))

    def snapshot(self) -> dict[str, Any]:
        return self._encode({
            "marketSeq": self._market_seq,
            "orderSeq": self._order_seq,
            "fillSeq": self._fill_seq,
            "markets": [asdict(market) for market in self.markets.values()],
            "pending": [asdict(order) for order in self.pending.values()],
            "fills": {mid: [asdict(fill) for fill in fills] for mid, fills in self.fills.items()},
            "positions": self.positions,
            "costBasis": self.cost_basis,
        })

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any], risk_engine: RiskEngine) -> "BatchEngine":
        engine = cls(risk_engine)
        engine._market_seq = int(data.get("marketSeq", 0))
        engine._order_seq = int(data.get("orderSeq", 0))
        engine._fill_seq = int(data.get("fillSeq", 0))
        for raw in data.get("markets", []):
            item = dict(raw)
            for key in ("id", "escrow_account_id", "round"):
                item[key] = int(item[key])
            item["funding_account_id"] = int(item["funding_account_id"]) if item.get("funding_account_id") is not None else None
            for key in ("b", "net_cap", "posted_price"):
                item[key] = Decimal(item[key])
            engine.risk.get_account(item["escrow_account_id"])
            market = BatchMarket(**item)
            engine.markets[market.id] = market
        for raw in data.get("pending", []):
            item = dict(raw)
            for key in ("id", "account_id", "market_id", "round", "lock_id"):
                item[key] = int(item[key])
            for key in ("target", "max_spend"):
                item[key] = Decimal(item[key])
            order = SealedOrder(**item)
            lock = risk_engine.get_account(order.account_id).lock_for(order.market_id, "batch_order")
            if lock is None or lock.lock_id != order.lock_id or lock.amount != order.max_spend:
                raise ValueError(f"pending order {order.id} lock does not match risk snapshot")
            engine.pending[(order.market_id, order.account_id)] = order
        engine.fills = {
            int(mid): [engine._fill_from_raw(raw) for raw in fills]
            for mid, fills in data.get("fills", {}).items()
        }
        engine.positions = engine._decimal_tree(data.get("positions", {}), depth=2)
        engine.cost_basis = engine._decimal_tree(data.get("costBasis", {}), depth=1)
        return engine

    @staticmethod
    def _fill_from_raw(raw: Mapping[str, Any]) -> BatchFill:
        item = dict(raw)
        for key in ("id", "order_id", "account_id", "market_id", "round"):
            item[key] = int(item[key])
        for key in ("target", "shares", "price", "spend"):
            item[key] = Decimal(item[key])
        return BatchFill(**item)

    @classmethod
    def _decimal_tree(cls, value: Mapping, depth: int) -> dict:
        if depth == 0:
            return {key: Decimal(item) for key, item in value.items()}
        return {int(key): cls._decimal_tree(item, depth - 1) for key, item in value.items()}

    @classmethod
    def _encode(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): cls._encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._encode(item) for item in value]
        return value

    @staticmethod
    def _clearing_price(p: Decimal, b: Decimal, net: Decimal) -> Decimal:
        if net == ZERO:
            return p
        p2 = _logistic(_logit(p) + net / b)
        return (_cost(p2, b) - _cost(p, b)) / net

    def _finish_round(self, market: BatchMarket, price: Decimal, participants: int) -> dict:
        record = {
            "round": market.round,
            "clearingPrice": str(price),
            "participants": participants,
        }
        market.round_history.append(record)
        market.round += 1
        return record

    def _add_position(self, account_id: int, market_id: int, outcome: str, shares: Decimal) -> None:
        by_market = self.positions.setdefault(account_id, {})
        position = by_market.setdefault(market_id, {"yes": ZERO, "no": ZERO})
        position[outcome] += shares

    def _release_pending(self, market_id: int) -> None:
        for key, order in list(self.pending.items()):
            if order.market_id == market_id:
                self.risk.release_lock(order.lock_id, trade_id=order.id)
                del self.pending[key]

    def _sweep_escrow(self, market: BatchMarket) -> None:
        if market.funding_account_id is None:
            return
        escrow = self.risk.get_account(market.escrow_account_id)
        if escrow.available_balance:
            self.risk.transfer_available(
                escrow.id, market.funding_account_id, escrow.available_balance,
                market.id, "batch_amm_sweep",
            )

    def _assert_escrow(self, market: BatchMarket) -> None:
        total_no = sum((
            markets.get(market.id, {}).get("no", ZERO)
            for markets in self.positions.values()
        ), ZERO)
        expected = total_no + _cost(market.posted_price, market.b)
        actual = self.risk.get_account(market.escrow_account_id).available_balance
        fill_count = len(self.fills.get(market.id, []))
        if abs(actual - expected) > MONEY_QUANTUM * (fill_count + 1):
            raise ClearingError(f"escrow invariant: {actual} != {expected}")

    def _open_market(self, market_id: int) -> BatchMarket:
        market = self.markets.get(int(market_id))
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        if market.status != "open":
            raise MarketClosed(f"market {market_id} is {market.status}")
        return market


class BatchVenue:
    kind = "batch"

    def __init__(self, engine: BatchEngine):
        self.engine = engine

    @classmethod
    def from_snapshot(cls, data: dict, risk_engine: RiskEngine) -> "BatchVenue":
        return cls(BatchEngine.from_snapshot(data, risk_engine))

    def create_market(self, question: str, **kwargs) -> dict:
        return self.get_market(self.engine.create_market(question, **kwargs).id)

    def market_ids(self) -> list[int]:
        return list(self.engine.markets)

    def get_market(self, market_id: int) -> dict:
        market = self.engine.markets.get(int(market_id))
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        return {
            "id": market.id,
            "question": market.question,
            "status": market.status,
            "outcomes": list(market.outcomes),
            "postedPrice": str(market.posted_price),
            "round": market.round,
            "roundHistory": list(market.round_history),
            "b": str(market.b),
            "deadline": market.deadline,
            "resolution": market.resolution,
        }

    def quote(self, account_id: int, payload: dict) -> dict:
        market_id, outcome, target, max_spend = self._parse(payload)
        return self.engine.estimate(market_id, outcome, target, max_spend)

    def place(self, account_id: int, payload: dict) -> dict:
        market_id, outcome, target, max_spend = self._parse(payload)
        return self.order_record(self.engine.submit_order(
            account_id, market_id, outcome, target, max_spend
        ))

    def close_round(self, market_id: int) -> dict:
        result = self.engine.close_round(int(market_id))
        return {
            **{key: value for key, value in result.items() if key != "fills"},
            "fills": [self.fill_record(fill) for fill in result["fills"]],
        }

    def resolve(self, market_id: int, outcome_id: str) -> dict:
        market = self.engine.resolve(int(market_id), outcome_id)
        return {"market": self.get_market(market.id)}

    def void(self, market_id: int) -> dict:
        market = self.engine.void(int(market_id))
        return {"market": self.get_market(market.id)}

    def snapshot(self) -> dict:
        return self.engine.snapshot()

    def stats(self) -> dict:
        return {
            "markets": len(self.engine.markets),
            "orders_or_trades": self.engine._order_seq + self.engine._fill_seq,
        }

    def orders_for(self, account_id: int) -> list[dict]:
        return [
            self.order_record(order) for order in self.engine.pending.values()
            if order.account_id == account_id
        ]

    def fills_for(self, account_id: int) -> list[dict]:
        return [
            self.fill_record(fill) for fills in self.engine.fills.values()
            for fill in fills if fill.account_id == account_id
        ]

    def positions_for(self, account_id: int) -> list[dict]:
        return [
            {"marketId": mid, **{outcome: str(value) for outcome, value in pos.items()}}
            for mid, pos in self.engine.positions.get(account_id, {}).items()
        ]

    @staticmethod
    def order_record(order: SealedOrder) -> dict:
        return {
            "orderId": order.id, "marketId": order.market_id,
            "round": order.round, "outcome": order.outcome,
            "target": str(order.target), "maxSpend": str(order.max_spend),
            "status": "pending",
        }

    @staticmethod
    def fill_record(fill: BatchFill) -> dict:
        return {
            "fillId": fill.id, "orderId": fill.order_id,
            "marketId": fill.market_id, "round": fill.round,
            "outcome": fill.outcome, "target": str(fill.target),
            "shares": str(fill.shares), "price": str(fill.price),
            "spend": str(fill.spend),
        }

    @staticmethod
    def _parse(payload: dict) -> tuple[int, str, Decimal, Decimal]:
        try:
            return (
                int(payload["marketId"]), payload["outcome"].lower(),
                _decimal(payload["target"], "target"),
                _decimal(payload["maxSpend"], "maxSpend"),
            )
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise InvalidTarget(str(exc)) from exc


Engine = BatchEngine
