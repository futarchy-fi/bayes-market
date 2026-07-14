"""Keep AMM and book listings aligned to an instrument's net listing."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

import httpx


def _execution_enabled(args: argparse.Namespace) -> bool:
    requested = bool(getattr(args, "execute", False))
    enabled = requested and bool(getattr(args, "enable_live_trading", False))
    if requested and not enabled:
        print("REPORT live trading disabled; add --enable-live-trading to activate", flush=True)
    return enabled


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass
class ArbConfig:
    spread_thr: Decimal = Decimal("0.02")
    budget_cap: Decimal = Decimal("25")
    size_cap: Decimal = Decimal("10")
    delta: Decimal = Decimal("0.01")
    requote_thr: Decimal = Decimal("0.005")
    min_balance: Decimal = Decimal("50")
    action_cap: int = 10
    report_only: bool = True


@dataclass
class ArbAction:
    kind: str
    instrument_id: str
    venue: str
    market_id: str
    outcome: str | None = None
    price: Decimal | None = None
    size: Decimal | None = None
    budget: Decimal | None = None
    order_id: int | None = None
    anchor: Decimal | None = None

    def __str__(self) -> str:
        prefix = "REPORT" if self.kind.startswith("would_") else "EXECUTE"
        kind = self.kind.removeprefix("would_")
        fields = [
            f"instrument={self.instrument_id}", f"venue={self.venue}",
            f"market={self.market_id}",
        ]
        for name in ("outcome", "price", "size", "budget", "order_id", "anchor"):
            value = getattr(self, name)
            if value is not None:
                fields.append(f"{name}={value}")
        return f"{prefix} {kind} " + " ".join(fields)


class ExchangeClient(Protocol):
    async def account(self) -> dict: ...
    async def market(self, venue: str, market_id: str) -> dict: ...
    async def buy_amm(self, market_id: str, outcome: str, budget: Decimal) -> dict: ...
    async def book_orders(self) -> list[dict]: ...
    async def place_book_order(
        self, market_id: str, outcome: str, price: Decimal, size: Decimal,
    ) -> dict: ...
    async def cancel_book_order(self, order_id: int) -> dict: ...


class HttpExchange:
    """Thin async HTTP backing; tests inject ``httpx.ASGITransport``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers,
            transport=transport, timeout=15,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpExchange:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        response = await self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as err:
            try:
                detail = response.json().get("error", {}).get("message")
            except ValueError:
                detail = response.text
            raise RuntimeError(
                f"exchange {method} {path} failed ({response.status_code}): {detail}"
            ) from err
        return response.json()

    async def instruments(self) -> list[dict]:
        return await self._request("GET", "/v1/instruments")

    async def account(self) -> dict:
        return await self._request("GET", "/v1/me")

    async def market(self, venue: str, market_id: str) -> dict:
        prefixes = {
            "amm": "/v1/markets/",
            "net": "/v1/net/markets/",
            "book": "/v1/book/markets/",
        }
        return await self._request("GET", prefixes[venue] + str(market_id))

    async def buy_amm(self, market_id: str, outcome: str, budget: Decimal) -> dict:
        return await self._request(
            "POST", f"/v1/markets/{market_id}/buy",
            json={"outcome": outcome, "budget": str(budget)},
        )

    async def book_orders(self) -> list[dict]:
        result = await self._request("GET", "/v1/book/orders/mine")
        return result["orders"]

    async def place_book_order(
        self, market_id: str, outcome: str, price: Decimal, size: Decimal,
    ) -> dict:
        return await self._request(
            "POST", "/v1/book/orders",
            json={
                "marketId": int(market_id), "side": "bid", "outcome": outcome,
                "price": f"{price:.4f}", "size": f"{size:.2f}",
            },
        )

    async def cancel_book_order(self, order_id: int) -> dict:
        return await self._request("DELETE", f"/v1/book/orders/{order_id}")



_TERMINAL_STATUSES = {"resolved", "void", "voided", "closed"}


def _tradable(market: dict) -> bool:
    """True unless the market reached a terminal state.

    Venue kinds disagree on the live-status word ("open" for amm/book,
    "active" for net seeds), so reject known-terminal states instead of
    matching one live one.
    """
    return str(market.get("status", "open")).lower() not in _TERMINAL_STATUSES


class ArbPolicy:
    def __init__(self, client: ExchangeClient, config: ArbConfig) -> None:
        self.client = client
        self.config = config

    async def tick(self, instrument: dict) -> list[ArbAction]:
        """Run at most one coherence pass for one registry instrument."""
        account = await self.client.account()
        if _decimal(account["available"]) < _decimal(self.config.min_balance):
            return []

        listings = instrument["listings"]
        anchor_listing = next((item for item in listings if item["venue"] == "net"), None)
        if anchor_listing is None:
            return []
        anchor_market = await self.client.market("net", anchor_listing["marketId"])
        if not _tradable(anchor_market):
            return []
        anchor = _decimal(anchor_market["marginals"]["yes"])
        instrument_id = instrument["instrumentId"]
        actions: list[ArbAction] = []
        book_orders: list[dict] | None = None

        for listing in listings:
            if len(actions) >= self.config.action_cap:
                break
            venue, market_id = listing["venue"], str(listing["marketId"])
            if venue == "amm":
                market = await self.client.market(venue, market_id)
                if not _tradable(market):
                    continue
                yes = _decimal(market["prices"]["yes"])
                gap = abs(yes - anchor)
                if gap > _decimal(self.config.spread_thr):
                    budget = min(
                        _decimal(self.config.budget_cap),
                        _decimal(self.config.budget_cap) * gap,
                    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                    outcome = "yes" if yes < anchor else "no"
                    action = ArbAction(
                        "would_buy" if self.config.report_only else "buy",
                        instrument_id, venue, market_id, outcome=outcome,
                        budget=budget, anchor=anchor,
                    )
                    actions.append(action)
                    if not self.config.report_only:
                        await self.client.buy_amm(market_id, outcome, budget)
            elif venue == "book":
                market = await self.client.market(venue, market_id)
                if not _tradable(market):
                    continue
                if book_orders is None:
                    book_orders = await self.client.book_orders()
                await self._quote_book(
                    instrument_id, market_id, anchor, book_orders, actions,
                )
        return actions

    async def _quote_book(
        self,
        instrument_id: str,
        market_id: str,
        anchor: Decimal,
        all_orders: list[dict],
        actions: list[ArbAction],
    ) -> None:
        quantum = Decimal("0.0001")
        desired = {
            "yes": (anchor - _decimal(self.config.delta)).quantize(
                quantum, rounding=ROUND_HALF_UP
            ),
            "no": (Decimal("1") - anchor - _decimal(self.config.delta)).quantize(
                quantum, rounding=ROUND_HALF_UP
            ),
        }
        desired = {
            outcome: min(Decimal("0.9999"), max(quantum, price))
            for outcome, price in desired.items()
        }
        live = [
            order for order in all_orders
            if str(order["marketId"]) == market_id
            and order["status"] in ("open", "partial")
        ]

        keep: set[str] = set()
        stale: list[dict] = []
        for order in live:
            outcome = order["outcome"]
            close = (
                order["side"] == "bid"
                and outcome in desired
                and abs(_decimal(order["price"]) - desired[outcome])
                <= _decimal(self.config.requote_thr)
                and outcome not in keep
            )
            if close:
                keep.add(outcome)
            else:
                stale.append(order)

        # Cancel stale quotes before posting replacements.
        for order in stale:
            if len(actions) >= self.config.action_cap:
                return
            action = ArbAction(
                "would_cancel" if self.config.report_only else "cancel",
                instrument_id, "book", market_id,
                outcome=order["outcome"], order_id=order["orderId"], anchor=anchor,
            )
            actions.append(action)
            if not self.config.report_only:
                await self.client.cancel_book_order(order["orderId"])

        size = _decimal(self.config.size_cap).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        for outcome, price in desired.items():
            if outcome in keep:
                continue
            if len(actions) >= self.config.action_cap:
                return
            action = ArbAction(
                "would_quote" if self.config.report_only else "quote",
                instrument_id, "book", market_id, outcome=outcome,
                price=price, size=size, anchor=anchor,
            )
            actions.append(action)
            if not self.config.report_only:
                await self.client.place_book_order(market_id, outcome, price, size)


def _env_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true",
        help="request execution (also requires --enable-live-trading)",
    )
    mode.add_argument("--report-only", action="store_true", help="print without mutating (default)")
    parser.add_argument(
        "--enable-live-trading", action="store_true",
        help="allow --execute to mutate markets",
    )
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--api-url", default=os.getenv("FUTARCHY_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("FUTARCHY_API_KEY", ""))
    parser.add_argument("--interval", type=float, default=float(os.getenv("ARB_INTERVAL", "30")))
    parser.add_argument("--instruments", default=os.getenv("ARB_INSTRUMENTS", "all"))
    parser.add_argument("--spread-thr", type=Decimal, default=_env_decimal("SPREAD_THR", "0.02"))
    parser.add_argument("--budget-cap", type=Decimal, default=_env_decimal("BUDGET_CAP", "25"))
    parser.add_argument("--size-cap", type=Decimal, default=_env_decimal("SIZE_CAP", "10"))
    parser.add_argument("--delta", type=Decimal, default=_env_decimal("DELTA", "0.01"))
    parser.add_argument("--requote-thr", type=Decimal, default=_env_decimal("REQUOTE_THR", "0.005"))
    parser.add_argument("--min-balance", type=Decimal, default=_env_decimal("MIN_BALANCE", "50"))
    parser.add_argument("--action-cap", type=int, default=int(os.getenv("ACTION_CAP", "10")))
    return parser


async def run(args: argparse.Namespace) -> None:
    args.execute = _execution_enabled(args)
    config = ArbConfig(
        spread_thr=args.spread_thr, budget_cap=args.budget_cap,
        size_cap=args.size_cap, delta=args.delta,
        requote_thr=args.requote_thr, min_balance=args.min_balance,
        action_cap=args.action_cap, report_only=not args.execute,
    )
    selected = None if args.instruments == "all" else {
        item.strip() for item in args.instruments.split(",") if item.strip()
    }
    async with HttpExchange(
        args.api_url, args.api_key,
    ) as client:
        policy = ArbPolicy(client, config)
        while True:
            for instrument in await client.instruments():
                if selected is not None and instrument["instrumentId"] not in selected:
                    continue
                actions = await policy.tick(instrument)
                if actions:
                    for action in actions:
                        print(action, flush=True)
                else:
                    print(
                        f"NOOP instrument={instrument['instrumentId']}",
                        flush=True,
                    )
            if args.once:
                return
            await asyncio.sleep(args.interval)


def main() -> None:
    asyncio.run(run(_parser().parse_args()))


if __name__ == "__main__":
    main()
