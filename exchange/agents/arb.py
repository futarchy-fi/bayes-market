"""Keep AMM and book listings aligned to an instrument's net listing."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

import httpx


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


_PRICE_EPS = Decimal("0.0001")


def _budget_to_reach(price: Decimal, anchor: Decimal, b: Decimal) -> Decimal:
    """Credits to move a binary LMSR's YES price to ``anchor`` from ``price``.

    Closed form: buying YES to raise the price p0->p1 costs
    ``b * ln((1 - p0) / (1 - p1))``; buying NO to lower it costs
    ``b * ln(p0 / p1)``. Sizing to the anchor this way targets it exactly
    instead of the depth-blind ``budget_cap * gap``, which overshoots a thin
    (small-b) AMM and sends the agent into a price-flipping oscillation that
    bleeds LMSR spread every tick. If the cap later binds, the agent moves
    part-way and converges over successive ticks rather than overshooting.
    """
    p0 = min(Decimal("1") - _PRICE_EPS, max(_PRICE_EPS, price))
    p1 = min(Decimal("1") - _PRICE_EPS, max(_PRICE_EPS, anchor))
    if p1 > p0:
        ratio = (Decimal("1") - p0) / (Decimal("1") - p1)
    else:
        ratio = p0 / p1
    return b * Decimal(str(math.log(float(ratio))))


@dataclass
class ArbConfig:
    spread_thr: Decimal = Decimal("0.02")
    budget_cap: Decimal = Decimal("25")
    size_cap: Decimal = Decimal("10")
    delta: Decimal = Decimal("0.01")
    requote_thr: Decimal = Decimal("0.005")
    min_balance: Decimal = Decimal("50")
    action_cap: int = 10
    # Anchor smoothing: the agent follows an EMA of the net marginal, not the
    # instantaneous reading, so a transient net spike can't be converted into
    # a permanent AMM move in one tick. anchor_alpha is the weight on each new
    # reading (1.0 = no smoothing = follow instantly; lower = slower to trust
    # a change). A manipulator must now HOLD the net off-true for many ticks
    # (sustained stake + exposure) to move the agent, instead of one blip.
    anchor_alpha: Decimal = Decimal("0.3")
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
        self._anchor_ema: dict[str, Decimal] = {}

    def _smooth_anchor(self, instrument_id: str, raw: Decimal) -> Decimal:
        """EMA-smooth the net marginal, clamped to (0, 1).

        The clamp keeps a net pushed to an extreme from producing runaway
        edits; the EMA means the agent chases a *sustained* net move, not a
        single-tick spike (the manipulation-resistance point — see
        ArbConfig.anchor_alpha)."""
        clamped = min(Decimal("1") - _PRICE_EPS, max(_PRICE_EPS, raw))
        alpha = _decimal(self.config.anchor_alpha)
        prev = self._anchor_ema.get(instrument_id)
        smoothed = clamped if prev is None else alpha * clamped + (1 - alpha) * prev
        self._anchor_ema[instrument_id] = smoothed
        return smoothed

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
        instrument_id = instrument["instrumentId"]
        anchor = self._smooth_anchor(
            instrument_id, _decimal(anchor_market["marginals"]["yes"])
        )
        actions: list[ArbAction] = []
        book_orders: list[dict] | None = None
        # Spend only what keeps the account at or above min_balance AFTER this
        # tick. The top-of-tick gate proves we're above the floor now; without
        # reserving, one tick's AMM buy + book collateral could still dip
        # below it. Every spend below draws down this running reserve.
        spendable = _decimal(account["available"]) - _decimal(self.config.min_balance)

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
                    # Size to the anchor via the AMM's own depth (b), capped —
                    # not budget_cap * gap, which is depth-blind and overshoots
                    # thin markets into an oscillation. Also capped by the
                    # floor reserve.
                    needed = _budget_to_reach(yes, anchor, _decimal(market["b"]))
                    budget = min(
                        _decimal(self.config.budget_cap), needed, spendable,
                    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                    if budget <= Decimal("0"):
                        continue
                    outcome = "yes" if yes < anchor else "no"
                    action = ArbAction(
                        "would_buy" if self.config.report_only else "buy",
                        instrument_id, venue, market_id, outcome=outcome,
                        budget=budget, anchor=anchor,
                    )
                    actions.append(action)
                    spendable -= budget
                    if not self.config.report_only:
                        await self.client.buy_amm(market_id, outcome, budget)
            elif venue == "book":
                market = await self.client.market(venue, market_id)
                if not _tradable(market):
                    continue
                if book_orders is None:
                    book_orders = await self.client.book_orders()
                spendable = await self._quote_book(
                    instrument_id, market_id, anchor, book_orders, actions, spendable,
                )
        return actions

    async def _quote_book(
        self,
        instrument_id: str,
        market_id: str,
        anchor: Decimal,
        all_orders: list[dict],
        actions: list[ArbAction],
        spendable: Decimal,
    ) -> Decimal:
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

        # Cancel stale quotes before posting replacements. Cancels free
        # collateral, so they don't draw the floor reserve.
        for order in stale:
            if len(actions) >= self.config.action_cap:
                return spendable
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
                return spendable
            # A bid to buy `size` at `price` locks up to price*size; skip it
            # if posting would breach the floor reserve.
            collateral = price * size
            if collateral > spendable:
                continue
            action = ArbAction(
                "would_quote" if self.config.report_only else "quote",
                instrument_id, "book", market_id, outcome=outcome,
                price=price, size=size, anchor=anchor,
            )
            actions.append(action)
            spendable -= collateral
            if not self.config.report_only:
                await self.client.place_book_order(market_id, outcome, price, size)
        return spendable


def _env_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="perform intended actions")
    mode.add_argument("--report-only", action="store_true", help="print without mutating (default)")
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
    parser.add_argument("--anchor-alpha", type=Decimal, default=_env_decimal("ANCHOR_ALPHA", "0.3"))
    return parser


async def run_pass(
    client: ExchangeClient, policy: ArbPolicy, selected: set[str] | None,
) -> int:
    """One coherence sweep over all instruments; returns the error count.

    Every remote call is fallible (a busy pass can hit the 60/min rate
    limit and 429), and a live agent must not die on a transient error and
    crash-loop under systemd. So the instruments fetch and each per-instrument
    tick are isolated: a failure is logged and the pass moves on, retrying on
    the next interval rather than tearing down the process. The returned
    count lets the caller back off when a pass is erroring (e.g. sustained
    rate-limiting) instead of hammering at the fixed interval.
    """
    try:
        instruments = await client.instruments()
    except Exception as err:  # noqa: BLE001 — a fetch failure must not kill the loop
        print(f"ERROR fetching instruments: {err}", flush=True)
        return 1
    errors = 0
    for instrument in instruments:
        if selected is not None and instrument["instrumentId"] not in selected:
            continue
        try:
            actions = await policy.tick(instrument)
        except Exception as err:  # noqa: BLE001 — one bad market must not kill the loop
            print(f"ERROR instrument={instrument.get('instrumentId')}: {err}", flush=True)
            errors += 1
            continue
        if actions:
            for action in actions:
                print(action, flush=True)
        else:
            print(f"NOOP instrument={instrument['instrumentId']}", flush=True)
    return errors


def _backoff_delay(base: float, consecutive_error_passes: int, cap: float) -> float:
    """Exponential backoff: base doubles per consecutive erroring pass, capped.

    A pass with no errors resets the caller's counter to 0, so a transient
    blip costs one longer sleep and recovers; a sustained outage (or a
    rate-limit storm) settles at ``cap`` instead of retrying every ``base``
    seconds and deepening the storm."""
    if consecutive_error_passes <= 0:
        return base
    if base <= 0 or cap <= base:
        return min(base, cap)
    max_doublings = math.ceil(math.log2(cap / base))
    return min(cap, base * (2 ** min(consecutive_error_passes, max_doublings)))


async def run(args: argparse.Namespace) -> None:
    config = ArbConfig(
        spread_thr=args.spread_thr, budget_cap=args.budget_cap,
        size_cap=args.size_cap, delta=args.delta,
        requote_thr=args.requote_thr, min_balance=args.min_balance,
        action_cap=args.action_cap, anchor_alpha=args.anchor_alpha,
        report_only=not args.execute,
    )
    selected = None if args.instruments == "all" else {
        item.strip() for item in args.instruments.split(",") if item.strip()
    }
    async with HttpExchange(
        args.api_url, args.api_key,
    ) as client:
        policy = ArbPolicy(client, config)
        consecutive_error_passes = 0
        backoff_cap = max(args.interval, float(os.getenv("ARB_BACKOFF_CAP", "600")))
        while True:
            errors = await run_pass(client, policy, selected)
            if args.once:
                return
            consecutive_error_passes = (
                consecutive_error_passes + 1 if errors else 0
            )
            delay = _backoff_delay(
                args.interval, consecutive_error_passes, backoff_cap
            )
            if consecutive_error_passes:
                print(
                    f"BACKOFF passes={consecutive_error_passes} sleep={delay:.0f}s",
                    flush=True,
                )
            await asyncio.sleep(delay)


def main() -> None:
    asyncio.run(run(_parser().parse_args()))


if __name__ == "__main__":
    main()
