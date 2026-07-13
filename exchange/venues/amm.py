"""Venue adapter for the per-market LMSR engine."""

from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from exchange.core.lmsr import amount_for_cost, cost_to_buy, prices
from exchange.core.market_engine import MarketEngine
from exchange.core.models import ZERO
from exchange.core.risk_engine import InsufficientBalance
from exchange.venues.base import (
    InsufficientCredits,
    InvalidOutcome,
    MarketClosed,
    TradeRejected,
    UnknownMarket,
)


class AmmVenue:
    """Thin Venue wrapper around an existing ``MarketEngine``."""

    kind = "amm"

    def __init__(self, engine: MarketEngine):
        self.engine = engine

    def market_ids(self) -> list[int]:
        return list(self.engine.markets)

    def get_market(self, market_id: int) -> dict:
        market = self.engine.markets.get(int(market_id))
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        record = asdict(market)
        record["prices"] = (
            prices(market.q, market.b) if market.status == "open" else {}
        )
        return record

    def quote(self, account_id: int, payload: dict) -> dict:
        try:
            market_id = int(payload["marketId"])
            side = payload["side"]
            outcome = payload["outcome"]
            if side == "buy":
                return self._quote_buy(
                    market_id, account_id, outcome, Decimal(str(payload["budget"]))
                )
            if side == "sell":
                return self._quote_sell(
                    market_id, account_id, outcome, Decimal(str(payload["amount"]))
                )
            raise TradeRejected(f"unknown side: {side}")
        except (InsufficientCredits, InvalidOutcome, MarketClosed,
                TradeRejected, UnknownMarket):
            raise
        except (KeyError, TypeError, ValueError) as err:
            raise TradeRejected(str(err)) from err

    def _open_market(self, market_id: int):
        market = self.engine.markets.get(market_id)
        if market is None:
            raise UnknownMarket(f"market {market_id} not found")
        if market.status != "open":
            raise MarketClosed(f"market {market_id} is {market.status}")
        return market

    def _quote_buy(self, market_id, account_id, outcome, budget) -> dict:
        market = self._open_market(market_id)
        if outcome not in market.outcomes:
            raise InvalidOutcome(f"unknown outcome: {outcome}")
        available = self.engine.risk.get_account(account_id).available_balance
        if budget > available:
            raise InsufficientCredits(
                f"account {account_id}: need {budget}, have {available}"
            )

        amount_quantum = Decimal(10) ** -market.amount_precision
        price_quantum = Decimal(10) ** -market.price_precision
        tokens = amount_for_cost(
            market.q, market.b, outcome, budget
        ).quantize(amount_quantum, rounding=ROUND_FLOOR)
        if tokens <= ZERO:
            raise TradeRejected("budget too small for any tokens")
        avg_price = (cost_to_buy(market.q, market.b, outcome, tokens) / tokens).quantize(
            price_quantum, rounding=ROUND_CEILING
        )
        cost = tokens * avg_price
        if cost > available:
            tokens -= amount_quantum
            if tokens <= ZERO:
                raise TradeRejected("budget too small for any tokens")
            avg_price = (
                cost_to_buy(market.q, market.b, outcome, tokens) / tokens
            ).quantize(price_quantum, rounding=ROUND_CEILING)
            cost = tokens * avg_price
        if cost > available:
            raise InsufficientCredits(
                f"account {account_id}: need {cost}, have {available}"
            )
        return {
            "estimatedShares": str(tokens),
            "averagePrice": str(avg_price),
            "cost": str(cost),
        }

    def _quote_sell(self, market_id, account_id, outcome, amount) -> dict:
        market = self._open_market(market_id)
        if outcome not in market.outcomes:
            raise InvalidOutcome(f"unknown outcome: {outcome}")
        amount_quantum = Decimal(10) ** -market.amount_precision
        if amount != amount.quantize(amount_quantum):
            raise TradeRejected(
                f"sell amount {amount} exceeds precision "
                f"(max {market.amount_precision} dp)"
            )
        held = market.position(account_id).get(outcome, ZERO)
        if amount > held:
            raise TradeRejected(
                f"account {account_id}: can't sell {amount} {outcome}, only holds {held}"
            )
        if amount <= ZERO:
            raise TradeRejected("sell amount must be positive")
        price_quantum = Decimal(10) ** -market.price_precision
        proceeds = -cost_to_buy(market.q, market.b, outcome, -amount)
        avg_price = (proceeds / amount).quantize(
            price_quantum, rounding=ROUND_FLOOR
        )
        if avg_price < ZERO:
            avg_price = ZERO
        return {"proceeds": str(amount * avg_price)}

    def place(self, account_id: int, payload: dict) -> dict:
        try:
            market_id = int(payload["marketId"])
            side = payload["side"]
            outcome = payload["outcome"]
            if side == "buy":
                trade = self.engine.buy(
                    market_id, account_id, outcome,
                    Decimal(str(payload["budget"])),
                )
            elif side == "sell":
                trade = self.engine.sell(
                    market_id, account_id, outcome,
                    Decimal(str(payload["amount"])),
                )
            else:
                raise TradeRejected(f"unknown side: {side}")
        except InsufficientBalance as err:
            raise InsufficientCredits(str(err)) from err
        except (KeyError, TypeError) as err:
            raise TradeRejected(str(err)) from err
        except ValueError as err:
            raise self._map_engine_error(err) from err
        return {
            "tradeId": trade.id,
            "marketId": trade.market_id,
            "outcome": trade.outcome,
            "amount": str(trade.amount),
            "averagePrice": str(trade.price),
            "cost": str(trade.amount * trade.price),
        }

    @staticmethod
    def _map_engine_error(err: ValueError):
        message = str(err)
        if "market" in message and "not found" in message:
            return UnknownMarket(message)
        if "market" in message and (" is resolved" in message or " is void" in message):
            return MarketClosed(message)
        if "unknown outcome" in message:
            return InvalidOutcome(message)
        return TradeRejected(message)

    def resolve(self, market_id: int, outcome_id: str) -> dict:
        try:
            self.engine.resolve(market_id, outcome_id)
        except ValueError as err:
            raise self._map_engine_error(err) from err
        return self.get_market(market_id)

    def void(self, market_id: int) -> dict:
        try:
            self.engine.void(market_id)
        except ValueError as err:
            raise self._map_engine_error(err) from err
        return self.get_market(market_id)

    def snapshot(self) -> dict:
        return deepcopy({
            "markets": {
                market_id: asdict(market)
                for market_id, market in self.engine.markets.items()
            }
        })

    def stats(self) -> dict:
        return {
            "markets": len(self.engine.markets),
            "orders_or_trades": sum(
                len(market.trades) for market in self.engine.markets.values()
            ),
        }
