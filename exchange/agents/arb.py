"""Keep identical cross-venue listings near a configured reference."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from time import monotonic
from typing import Any, Protocol

import httpx


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


_PRICE_EPS = Decimal("0.0001")


def _budget_to_reach(price: Decimal, anchor: Decimal, b: Decimal) -> Decimal:
    """Credits to move a binary LMSR's YES price from ``price`` to ``anchor``.

    Closed form: buying YES to raise the price p0->p1 costs
    ``b * ln((1 - p0) / (1 - p1))``; buying NO to lower it costs
    ``b * ln(p0 / p1)``. The caller passes a bounded one-tick target, avoiding
    the thin-market overshoot caused by the old depth-blind sizing rule.
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
    instrument_budget_cap: Decimal = Decimal("25")
    min_balance: Decimal = Decimal("50")
    inventory_cap: Decimal = Decimal("50")
    max_price_move: Decimal = Decimal("0.02")
    action_cap: int = 10
    reference_venue: str = "net"
    anchor_alpha: Decimal = Decimal("0.3")
    anchor_max_age: Decimal = Decimal("120")
    anchor_max_jump: Decimal = Decimal("0.10")
    report_only: bool = True

    def __post_init__(self) -> None:
        self.reference_venue = self.reference_venue.lower()
        if self.reference_venue not in {"net", "amm", "book"}:
            raise ValueError("reference_venue must be net, amm, or book")
        positive = (
            "budget_cap", "instrument_budget_cap", "inventory_cap",
            "max_price_move", "anchor_alpha", "anchor_max_age",
            "anchor_max_jump",
        )
        nonnegative = ("spread_thr", "min_balance")
        for name in positive:
            value = _decimal(getattr(self, name))
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in nonnegative:
            value = _decimal(getattr(self, name))
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if _decimal(self.anchor_alpha) > 1:
            raise ValueError("anchor_alpha must be at most 1")
        if _decimal(self.anchor_max_jump) >= 1 or _decimal(self.max_price_move) >= 1:
            raise ValueError("anchor_max_jump and max_price_move must be below 1")
        if self.action_cap <= 0:
            raise ValueError("action_cap must be positive")


@dataclass
class _AnchorState:
    raw: Decimal
    sampled_at: float
    ema: Decimal | None = None


@dataclass
class ArbAction:
    kind: str
    instrument_id: str
    venue: str
    market_id: str
    outcome: str | None = None
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
        for name in ("outcome", "budget", "order_id", "anchor"):
            value = getattr(self, name)
            if value is not None:
                fields.append(f"{name}={value}")
        return f"{prefix} {kind} " + " ".join(fields)


class ExchangeClient(Protocol):
    async def account(self) -> dict: ...
    async def market(self, venue: str, market_id: str) -> dict: ...
    async def buy_amm(
        self,
        market_id: str,
        outcome: str,
        budget: Decimal,
        target_price: Decimal,
        max_price_move: Decimal,
        position_limit: Decimal,
        min_balance: Decimal,
    ) -> dict | None: ...
    async def book_orders(self) -> list[dict]: ...
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
        return None if response.status_code == 204 else response.json()

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

    async def buy_amm(
        self,
        market_id: str,
        outcome: str,
        budget: Decimal,
        target_price: Decimal,
        max_price_move: Decimal,
        position_limit: Decimal,
        min_balance: Decimal,
    ) -> dict | None:
        return await self._request(
            "POST", f"/v1/markets/{market_id}/buy-to-price",
            json={
                "outcome": outcome,
                "maxBudget": str(budget),
                "targetPrice": str(target_price),
                "maxPriceMove": str(max_price_move),
                "positionLimit": str(position_limit),
                "minBalance": str(min_balance),
            },
        )

    async def book_orders(self) -> list[dict]:
        result = await self._request("GET", "/v1/book/orders/mine")
        return result["orders"]

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


def _binary_market(venue: str, market: dict) -> bool:
    """Require the exact YES/NO contract shape used by the sizing math."""
    try:
        outcomes = market["outcomes"]
        outcome_ids = (
            {str(item["id"]).lower() for item in outcomes}
            if venue == "net" else {str(item).lower() for item in outcomes}
        )
    except (KeyError, TypeError):
        return False
    return outcome_ids == {"yes", "no"} and len(outcomes) == 2


def _yes_price(venue: str, market: dict) -> Decimal | None:
    try:
        if venue == "net":
            value = market.get("marginals", {}).get("yes")
        elif venue == "amm":
            value = market.get("prices", {}).get("yes")
        else:
            bid, ask = _decimal(market["bestBid"]), _decimal(market["bestAsk"])
            if (
                not bid.is_finite() or not ask.is_finite()
                or not _PRICE_EPS <= bid <= ask <= 1 - _PRICE_EPS
            ):
                return None
            value = (bid + ask) / 2
        if value is None:
            return None
        price = _decimal(value)
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if not price.is_finite() or not _PRICE_EPS <= price <= 1 - _PRICE_EPS:
        return None
    return price


def _fresh_net_observation(market: dict, max_age: Decimal) -> bool:
    try:
        observed = datetime.fromisoformat(
            str(market["observedAt"]).replace("Z", "+00:00")
        )
        if observed.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    return -5 <= age <= float(max_age)


class ArbPolicy:
    def __init__(self, client: ExchangeClient, config: ArbConfig) -> None:
        self.client = client
        self.config = config
        self._anchors: dict[str, _AnchorState] = {}

    def _accept_anchor(self, instrument_id: str, raw: Decimal) -> Decimal | None:
        """Confirm two nearby samples, then return the smoothed reference."""
        now = monotonic()
        max_age = float(_decimal(self.config.anchor_max_age))
        previous = self._anchors.get(instrument_id)
        if previous is None or now - previous.sampled_at > max_age:
            self._anchors[instrument_id] = _AnchorState(raw, now)
            # A dry run may preview an unconfirmed sample because it cannot
            # mutate state. Execution always waits for the follow-up sample.
            return raw if self.config.report_only else None
        if abs(raw - previous.raw) > _decimal(self.config.anchor_max_jump):
            # Require one nearby follow-up before accepting a large step.
            self._anchors[instrument_id] = _AnchorState(raw, now, ema=previous.ema)
            return None
        alpha = _decimal(self.config.anchor_alpha)
        smoothed = raw if previous.ema is None else (
            alpha * raw + (1 - alpha) * previous.ema
        )
        self._anchors[instrument_id] = _AnchorState(raw, now, smoothed)
        return smoothed

    async def _cancel_untraded_book_quotes(
        self, instrument_id: str, listings: list[dict], actions: list[ArbAction],
    ) -> None:
        market_ids = {
            str(item["marketId"]) for item in listings if item["venue"] == "book"
        }
        if not market_ids:
            return
        orders = await self.client.book_orders()
        for order in orders:
            if (
                str(order["marketId"]) not in market_ids
                or order["status"] not in ("open", "partial")
            ):
                continue
            action = ArbAction(
                "would_cancel" if self.config.report_only else "cancel",
                instrument_id, "book", str(order["marketId"]),
                outcome=order["outcome"], order_id=order["orderId"],
            )
            if not self.config.report_only:
                await self.client.cancel_book_order(order["orderId"])
            actions.append(action)

    async def tick(self, instrument: dict) -> list[ArbAction]:
        """Run at most one coherence pass for one registry instrument."""
        instrument_id = instrument["instrumentId"]
        listings = instrument["listings"]
        actions: list[ArbAction] = []
        await self._cancel_untraded_book_quotes(
            instrument_id, listings, actions,
        )
        if len(actions) >= self.config.action_cap:
            return actions

        account = await self.client.account()
        if _decimal(account["available"]) < _decimal(self.config.min_balance):
            return actions

        anchor_listing = next(
            (item for item in listings if item["venue"] == self.config.reference_venue),
            None,
        )
        if anchor_listing is None:
            return actions
        anchor_market = await self.client.market(
            self.config.reference_venue, anchor_listing["marketId"],
        )
        if (
            not _tradable(anchor_market)
            or not _binary_market(self.config.reference_venue, anchor_market)
        ):
            return actions
        if self.config.reference_venue == "net" and not _fresh_net_observation(
            anchor_market, _decimal(self.config.anchor_max_age),
        ):
            return actions
        raw_anchor = _yes_price(self.config.reference_venue, anchor_market)
        if raw_anchor is None:
            return actions
        anchor = self._accept_anchor(instrument_id, raw_anchor)
        if anchor is None:
            return actions

        reference_key = (
            self.config.reference_venue, str(anchor_listing["marketId"]),
        )
        traded = [
            item for item in listings
            if (item["venue"], str(item["marketId"])) != reference_key
            and item["venue"] == "amm"
        ]
        if not traded:
            return actions
        position_limit = _decimal(self.config.inventory_cap) / len(traded)
        spendable = min(
            _decimal(account["available"]) - _decimal(self.config.min_balance),
            _decimal(self.config.instrument_budget_cap),
        )
        if spendable <= 0:
            return actions

        for listing in traded:
            if len(actions) >= self.config.action_cap:
                break
            venue, market_id = listing["venue"], str(listing["marketId"])
            market = await self.client.market(venue, market_id)
            if not _tradable(market) or not _binary_market(venue, market):
                continue
            yes = _yes_price("amm", market)
            if yes is None:
                continue
            gap = abs(yes - anchor)
            if gap > _decimal(self.config.spread_thr):
                move = _decimal(self.config.max_price_move)
                bounded = (
                    min(anchor, yes + move) if yes < anchor
                    else max(anchor, yes - move)
                )
                needed = _budget_to_reach(yes, bounded, _decimal(market["b"]))
                budget = min(
                    _decimal(self.config.budget_cap), needed, spendable,
                ).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
                if budget <= Decimal("0"):
                    continue
                outcome = "yes" if yes < anchor else "no"
                target_price = anchor if outcome == "yes" else 1 - anchor
                action = ArbAction(
                    "would_buy" if self.config.report_only else "buy",
                    instrument_id, venue, market_id, outcome=outcome,
                    budget=budget, anchor=anchor,
                )
                if self.config.report_only:
                    actions.append(action)
                    spendable -= budget
                    continue
                result = await self.client.buy_amm(
                    market_id, outcome, budget, target_price,
                    _decimal(self.config.max_price_move), position_limit,
                    _decimal(self.config.min_balance),
                )
                if result is None:
                    continue
                actual = _decimal(result["value"])
                if not actual.is_finite() or not 0 < actual <= budget:
                    raise RuntimeError(
                        f"AMM debit {actual} exceeded requested budget {budget}"
                    )
                action.budget = actual
                actions.append(action)
                spendable -= actual
        return actions


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
    parser.add_argument("--instrument-budget-cap", type=Decimal, default=_env_decimal("INSTRUMENT_BUDGET_CAP", "25"))
    parser.add_argument("--min-balance", type=Decimal, default=_env_decimal("MIN_BALANCE", "50"))
    parser.add_argument("--inventory-cap", type=Decimal, default=_env_decimal("INVENTORY_CAP", "50"))
    parser.add_argument("--max-price-move", type=Decimal, default=_env_decimal("MAX_PRICE_MOVE", "0.02"))
    parser.add_argument("--action-cap", type=int, default=int(os.getenv("ACTION_CAP", "10")))
    parser.add_argument("--reference-venue", default=os.getenv("REFERENCE_VENUE", "net"))
    parser.add_argument("--anchor-alpha", type=Decimal, default=_env_decimal("ANCHOR_ALPHA", "0.3"))
    parser.add_argument("--anchor-max-age", type=Decimal, default=_env_decimal("ANCHOR_MAX_AGE", "120"))
    parser.add_argument("--anchor-max-jump", type=Decimal, default=_env_decimal("ANCHOR_MAX_JUMP", "0.10"))
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
        instrument_budget_cap=args.instrument_budget_cap,
        min_balance=args.min_balance,
        inventory_cap=args.inventory_cap, max_price_move=args.max_price_move,
        action_cap=args.action_cap, reference_venue=args.reference_venue,
        anchor_alpha=args.anchor_alpha, anchor_max_age=args.anchor_max_age,
        anchor_max_jump=args.anchor_max_jump,
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
