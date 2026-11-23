#!/usr/bin/env python3
"""Execute a round-robin manifest of guest-trader positions on futarchy-exchange.

Dry-run / report-only by default: pass ``--execute`` (with ``--admin-key`` or
``FUTARCHY_ADMIN_KEY``) to create named trader accounts and submit orders.
Raw API keys are kept strictly in memory and are never written to disk or logs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

LOG = logging.getLogger("guest_trades")

ZERO = Decimal("0")
DEFAULT_API_URL = "http://127.0.0.1:3210"
DEFAULT_MANIFEST = "scripts/dwarkesh/guest_trades.json"
DEFAULT_RECEIPT_OUT = "/tmp/guest_trades_receipt.json"
DEFAULT_INITIAL_CREDITS = Decimal("1000")

DEADBAND = 0.015
MAX_STEP = 0.14
PROB_MIN = 0.03
PROB_MAX = 0.97
MIN_EFFECTIVE_STEP = 0.008
BISECTION_STEPS = 8

CONVICTION_ALPHA: dict[str, float] = {
    "low": 0.22,
    "medium": 0.36,
    "high": 0.50,
}

_CLOSED_STATUSES = {"resolved", "void", "voided", "closed"}


@dataclass(frozen=True)
class TradeSpec:
    variable_id: str
    target_prob: float
    conviction: str = "medium"
    rationale: str = ""
    quote: str = ""
    outcome_id: str = "yes"
    context: dict[str, str] | None = None


@dataclass(frozen=True)
class GuestSpec:
    username: str
    display_name: str
    trades: list[TradeSpec]
    initial_credits: Decimal = DEFAULT_INITIAL_CREDITS


@dataclass(frozen=True)
class RunnerConfig:
    api_url: str = DEFAULT_API_URL
    admin_key: str = ""
    max_stake_per_trade: Decimal = Decimal("120")
    min_buffer: Decimal = Decimal("100")
    execute: bool = False
    rotate_existing: bool = False
    timeout: float = 20.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _first_present(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def parse_manifest(manifest: dict[str, Any]) -> list[GuestSpec]:
    """Parse ``manifest["traders"]`` into structured GuestSpec objects."""
    raw_traders = manifest.get("traders")
    if not isinstance(raw_traders, list):
        raise ValueError("manifest must contain a 'traders' list")

    guests: list[GuestSpec] = []
    seen_usernames: set[str] = set()
    for idx, entry in enumerate(raw_traders):
        if not isinstance(entry, dict):
            raise ValueError(f"trader at index {idx} must be an object")
        raw_username = _first_present(entry, "username", "slug", "id", "handle")
        if not raw_username or not str(raw_username).strip():
            raise ValueError(f"trader at index {idx} is missing username")
        username = str(raw_username).strip()
        if username in seen_usernames:
            raise ValueError(f"duplicate trader username in manifest: {username}")
        seen_usernames.add(username)

        raw_display = _first_present(
            entry, "display_name", "displayName", "name", "guest_name",
            default=username,
        )
        display_name = str(raw_display).strip() or username

        raw_credits = _first_present(
            entry, "initial_credits", "initialCredits",
            default=str(DEFAULT_INITIAL_CREDITS),
        )
        initial_credits = Decimal(str(raw_credits))

        raw_trades = _first_present(entry, "trades", "positions", "orders", default=[])
        if not isinstance(raw_trades, list):
            raise ValueError(f"trader '{username}' trades must be a list")

        trades: list[TradeSpec] = []
        for t_idx, tr in enumerate(raw_trades):
            if not isinstance(tr, dict):
                raise ValueError(f"trade {t_idx} for '{username}' must be an object")
            raw_var = _first_present(tr, "variable_id", "variableId", "target_var", "variable")
            if not raw_var or not str(raw_var).strip():
                raise ValueError(f"trade {t_idx} for '{username}' is missing variable_id")
            raw_prob = _first_present(tr, "target_prob", "targetProb", "target", "probability")
            if raw_prob is None:
                raise ValueError(f"trade {t_idx} for '{username}' is missing target_prob")
            target_prob = float(raw_prob)
            if not (0.0 <= target_prob <= 1.0):
                raise ValueError(
                    f"trade {t_idx} for '{username}' target_prob {target_prob} out of [0, 1]"
                )
            conviction = str(tr.get("conviction") or "medium").strip().lower()
            if conviction not in CONVICTION_ALPHA:
                raise ValueError(
                    f"trade {t_idx} for '{username}' has invalid conviction '{conviction}'"
                )
            outcome_id = str(
                _first_present(tr, "outcome_id", "outcomeId", "outcome", default="yes")
            ).strip()
            context = tr.get("context")
            if context is not None:
                context = {str(k): str(v) for k, v in context.items()}
            trades.append(
                TradeSpec(
                    variable_id=str(raw_var).strip(),
                    target_prob=target_prob,
                    conviction=conviction,
                    rationale=str(tr.get("rationale") or ""),
                    quote=str(tr.get("quote") or ""),
                    outcome_id=outcome_id,
                    context=context,
                )
            )
        guests.append(
            GuestSpec(
                username=username,
                display_name=display_name,
                trades=trades,
                initial_credits=initial_credits,
            )
        )
    return guests


def compute_desired_probability(
    p_cur: float,
    target_prob: float,
    conviction: str,
) -> float | None:
    """Return the fractional step probability toward target_prob, or None if skipped."""
    if abs(target_prob - p_cur) < DEADBAND:
        return None
    alpha = CONVICTION_ALPHA.get(conviction.lower(), CONVICTION_ALPHA["medium"])
    raw_step = _clamp(alpha * (target_prob - p_cur), -MAX_STEP, MAX_STEP)
    desired = _clamp(p_cur + raw_step, PROB_MIN, PROB_MAX)
    if abs(desired - p_cur) < MIN_EFFECTIVE_STEP:
        return None
    return round(desired, 6)


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = client.request(method, path, headers=headers, json=json_body)
    resp.raise_for_status()
    return resp.json()


def _order_payload(trade: TradeSpec, target: float) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "variableId": trade.variable_id,
        "outcomeId": trade.outcome_id,
        "target": target,
    }
    if trade.context:
        payload["context"] = trade.context
    return payload


def _select_feasible_target(
    client: httpx.Client,
    guest_key: str,
    trade: TradeSpec,
    p_cur: float,
    desired: float,
    allowed_stake: Decimal,
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    """Preview desired target and shrink via 8-step bisection if stake exceeds allowed_stake."""
    try:
        preview = _request_json(
            client,
            "POST",
            "/v1/net/orders/preview",
            api_key=guest_key,
            json_body=_order_payload(trade, desired),
        )
    except httpx.HTTPStatusError as err:
        return None, None, f"preview_http_{err.response.status_code}"

    stake = Decimal(str(preview["stake"]))
    if stake <= allowed_stake:
        return desired, preview, None

    lo = 0.0
    hi = 1.0
    delta = desired - p_cur
    best_target: float | None = None
    best_preview: dict[str, Any] | None = None

    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        cand = round(_clamp(p_cur + mid * delta, PROB_MIN, PROB_MAX), 6)
        if abs(cand - p_cur) < 1e-6:
            lo = mid
            continue
        try:
            cand_preview = _request_json(
                client,
                "POST",
                "/v1/net/orders/preview",
                api_key=guest_key,
                json_body=_order_payload(trade, cand),
            )
        except httpx.HTTPStatusError:
            hi = mid
            continue
        cand_stake = Decimal(str(cand_preview["stake"]))
        if cand_stake <= allowed_stake:
            best_target = cand
            best_preview = cand_preview
            lo = mid
        else:
            hi = mid

    if best_target is None:
        return None, None, "infeasible_stake"
    if abs(best_target - p_cur) < MIN_EFFECTIVE_STEP:
        return None, None, "step_too_small_after_bisection"
    return best_target, best_preview, None


def run_guest_trades(
    manifest: dict[str, Any],
    config: RunnerConfig,
    *,
    manifest_label: str = "",
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Execute (or dry-run) all guest trades round-robin against the exchange API."""
    guests = parse_manifest(manifest)

    if config.execute and not config.admin_key:
        raise ValueError(
            "Admin key is required for --execute (pass --admin-key or set FUTARCHY_ADMIN_KEY)"
        )

    with httpx.Client(
        base_url=config.api_url.rstrip("/"),
        transport=transport,
        timeout=config.timeout,
    ) as client:
        markets_resp = _request_json(client, "GET", "/v1/net/markets")
        raw_markets = markets_resp.get("markets", [])
        if not isinstance(raw_markets, list):
            raise ValueError("/v1/net/markets response missing 'markets' list")
        var_to_market: dict[str, dict[str, Any]] = {
            str(m["variableId"]): m
            for m in raw_markets
            if isinstance(m, dict) and "variableId" in m and "id" in m
        }

        # Guest runtime tracking — raw keys are stored strictly in memory here.
        guest_keys: dict[str, str] = {}
        guest_account_ids: dict[str, int | None] = {g.username: None for g in guests}
        guest_available: dict[str, Decimal] = {g.username: g.initial_credits for g in guests}
        guest_staked: dict[str, Decimal] = {g.username: ZERO for g in guests}
        guest_orders: dict[str, int] = {g.username: 0 for g in guests}
        guests_created = 0

        if config.execute:
            for guest in guests:
                create_body: dict[str, Any] = {
                    "username": guest.username,
                    "display_name": guest.display_name,
                    "is_service_account": False,
                    "initial_credits": str(guest.initial_credits),
                }
                if config.rotate_existing:
                    create_body["rotate_if_exists"] = True
                created = _request_json(
                    client,
                    "POST",
                    "/v1/admin/service-accounts",
                    api_key=config.admin_key,
                    json_body=create_body,
                )
                guest_keys[guest.username] = str(created["api_key"])
                guest_account_ids[guest.username] = int(created["account_id"])
                guests_created += 1
                if config.rotate_existing:
                    me = _request_json(
                        client, "GET", "/v1/me", api_key=guest_keys[guest.username]
                    )
                    guest_available[guest.username] = Decimal(str(me["available"]))
                else:
                    guest_available[guest.username] = guest.initial_credits

        executed_trades: list[dict[str, Any]] = []
        skipped_trades: list[dict[str, Any]] = []
        sim_prices: dict[tuple[str, str], float] = {}

        max_rounds = max((len(g.trades) for g in guests), default=0)
        for round_idx in range(max_rounds):
            for guest in guests:
                if round_idx >= len(guest.trades):
                    continue
                trade = guest.trades[round_idx]
                market = var_to_market.get(trade.variable_id)
                if market is None:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "variable_id": trade.variable_id,
                        "target_prob": trade.target_prob,
                        "reason": "market_not_found",
                    })
                    continue

                market_id = str(market["id"])
                try:
                    market_detail = _request_json(
                        client, "GET", f"/v1/net/markets/{market_id}"
                    )
                except httpx.HTTPStatusError as err:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "target_prob": trade.target_prob,
                        "reason": f"market_fetch_http_{err.response.status_code}",
                    })
                    continue

                status = str(market_detail.get("status", "open")).lower()
                if status in _CLOSED_STATUSES:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "target_prob": trade.target_prob,
                        "reason": "market_closed",
                    })
                    continue

                marginals = market_detail.get("marginals") or {}
                if trade.outcome_id not in marginals:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "target_prob": trade.target_prob,
                        "reason": f"unknown_outcome:{trade.outcome_id}",
                    })
                    continue

                if not config.execute and (market_id, trade.outcome_id) in sim_prices:
                    p_cur = sim_prices[(market_id, trade.outcome_id)]
                else:
                    p_cur = float(marginals[trade.outcome_id])

                if abs(trade.target_prob - p_cur) < DEADBAND:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "before": p_cur,
                        "target_prob": trade.target_prob,
                        "reason": "within_deadband",
                    })
                    continue

                desired = compute_desired_probability(
                    p_cur, trade.target_prob, trade.conviction
                )
                if desired is None:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "before": p_cur,
                        "target_prob": trade.target_prob,
                        "reason": "step_too_small",
                    })
                    continue

                title = str(market_detail.get("title") or market.get("title") or "")

                if not config.execute:
                    sim_prices[(market_id, trade.outcome_id)] = desired
                    guest_orders[guest.username] += 1
                    executed_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "title": title,
                        "before": p_cur,
                        "after": desired,
                        "target_prob": trade.target_prob,
                        "stake": "0",
                        "order_id": None,
                        "conviction": trade.conviction,
                        "rationale": trade.rationale,
                        "quote": trade.quote,
                        "dry_run": True,
                    })
                    continue

                budget_left = guest_available[guest.username] - config.min_buffer
                allowed_stake = min(config.max_stake_per_trade, budget_left)
                if allowed_stake <= ZERO:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "before": p_cur,
                        "target_prob": trade.target_prob,
                        "reason": "insufficient_budget",
                    })
                    continue

                guest_key = guest_keys[guest.username]
                chosen_target, _preview, skip_reason = _select_feasible_target(
                    client,
                    guest_key,
                    trade,
                    p_cur,
                    desired,
                    allowed_stake,
                )
                if chosen_target is None:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "before": p_cur,
                        "target_prob": trade.target_prob,
                        "reason": skip_reason or "infeasible_stake",
                    })
                    continue

                try:
                    order_resp = _request_json(
                        client,
                        "POST",
                        "/v1/net/orders",
                        api_key=guest_key,
                        json_body=_order_payload(trade, chosen_target),
                    )
                except httpx.HTTPStatusError as err:
                    skipped_trades.append({
                        "round": round_idx,
                        "guest_name": guest.display_name,
                        "username": guest.username,
                        "market_id": market_id,
                        "variable_id": trade.variable_id,
                        "before": p_cur,
                        "target_prob": trade.target_prob,
                        "reason": f"order_http_{err.response.status_code}",
                    })
                    continue

                stake = Decimal(str(order_resp["stake"]))
                balance_info = order_resp.get("balance")
                if isinstance(balance_info, dict) and "available" in balance_info:
                    guest_available[guest.username] = Decimal(str(balance_info["available"]))
                else:
                    guest_available[guest.username] -= stake

                guest_staked[guest.username] += stake
                guest_orders[guest.username] += 1

                executed_trades.append({
                    "round": round_idx,
                    "guest_name": guest.display_name,
                    "username": guest.username,
                    "market_id": market_id,
                    "variable_id": trade.variable_id,
                    "title": title,
                    "before": float(order_resp.get("before", p_cur)),
                    "after": float(order_resp.get("after", chosen_target)),
                    "target_prob": trade.target_prob,
                    "stake": str(stake),
                    "order_id": str(order_resp["orderId"]),
                    "conviction": trade.conviction,
                    "rationale": trade.rationale,
                    "quote": trade.quote,
                })

    total_volume = sum((Decimal(str(t["stake"])) for t in executed_trades), ZERO)
    per_guest = [
        {
            "guest_name": g.display_name,
            "username": g.username,
            "account_id": guest_account_ids[g.username],
            "orders_placed": guest_orders[g.username],
            "total_staked": str(guest_staked[g.username]),
            "remaining_balance": str(guest_available[g.username]),
        }
        for g in guests
    ]

    top_moves = sorted(
        (
            {
                "guest_name": t["guest_name"],
                "username": t["username"],
                "market_id": t["market_id"],
                "variable_id": t["variable_id"],
                "title": t["title"],
                "before": t["before"],
                "after": t["after"],
                "delta": round(t["after"] - t["before"], 6),
                "abs_delta": round(abs(t["after"] - t["before"]), 6),
                "stake": t["stake"],
                "order_id": t["order_id"],
            }
            for t in executed_trades
        ),
        key=lambda m: (-m["abs_delta"], -Decimal(str(m["stake"])), m["variable_id"]),
    )[:15]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_url": config.api_url.rstrip("/"),
        "manifest": manifest_label,
        "dry_run": not config.execute,
        "config": {
            "max_stake_per_trade": str(config.max_stake_per_trade),
            "min_buffer": str(config.min_buffer),
        },
        "summary": {
            "guests_total": len(guests),
            "guests_created": guests_created,
            "orders_placed": len(executed_trades) if config.execute else 0,
            "trades_planned": len(executed_trades),
            "trades_skipped": len(skipped_trades),
            "total_volume": str(total_volume),
            "per_guest": per_guest,
            "top_moves": top_moves,
        },
        "trades": executed_trades,
        "skipped": skipped_trades,
    }


def write_receipt(receipt: dict[str, Any], path: Path) -> None:
    """Atomically write receipt JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def format_summary(receipt: dict[str, Any]) -> str:
    """Format a human-readable execution summary for stdout."""
    summary = receipt["summary"]
    mode = "DRY-RUN" if receipt.get("dry_run") else "EXECUTED"
    lines = [
        f"=== Guest Trader Run ({mode}) ===",
        f"Guests total:    {summary['guests_total']}",
        f"Guests created:  {summary['guests_created']}",
        f"Orders placed:   {summary['orders_placed']}"
        + (f" (planned: {summary['trades_planned']})" if receipt.get("dry_run") else ""),
        f"Trades skipped:  {summary['trades_skipped']}",
        f"Total volume:    {summary['total_volume']} credits",
        "",
        "Per-guest spend & remaining balance:",
    ]
    for g in summary["per_guest"]:
        lines.append(
            f"  - {g['guest_name']} (@{g['username']}): "
            f"{g['orders_placed']} orders, staked={g['total_staked']}, "
            f"remaining={g['remaining_balance']}"
        )

    lines.append("")
    lines.append("Top 15 biggest probability moves:")
    if not summary["top_moves"]:
        lines.append("  (none)")
    for idx, move in enumerate(summary["top_moves"], 1):
        sign = "+" if move["delta"] >= 0 else ""
        label = move["title"] or move["variable_id"]
        lines.append(
            f"  {idx:2d}. {move['guest_name']} on {move['variable_id']} ({label}): "
            f"{move['before']:.3f} -> {move['after']:.3f} ({sign}{move['delta']:.3f}), "
            f"stake={move['stake']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST,
        help=f"Path to guest trades manifest JSON (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("FUTARCHY_API_URL", DEFAULT_API_URL),
        help=f"Exchange API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--admin-key",
        default=None,
        help="Admin bearer key (defaults to FUTARCHY_ADMIN_KEY env var)",
    )
    parser.add_argument(
        "--max-stake-per-trade",
        default="120",
        help="Maximum credits to stake on any single trade (default: 120)",
    )
    parser.add_argument(
        "--min-buffer",
        default="100",
        help="Minimum available credit balance to retain per guest (default: 100)",
    )
    parser.add_argument(
        "--receipt-out",
        default=DEFAULT_RECEIPT_OUT,
        help=f"Path to write receipt JSON (default: {DEFAULT_RECEIPT_OUT})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually create accounts and place orders (default: dry-run)",
    )
    parser.add_argument(
        "--rotate-existing",
        action="store_true",
        help="Rotate API keys instead of failing if guest usernames already exist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    admin_key = (
        args.admin_key
        if args.admin_key is not None
        else os.environ.get("FUTARCHY_ADMIN_KEY", "")
    )
    config = RunnerConfig(
        api_url=args.api_url,
        admin_key=admin_key,
        max_stake_per_trade=Decimal(str(args.max_stake_per_trade)),
        min_buffer=Decimal(str(args.min_buffer)),
        execute=args.execute,
        rotate_existing=args.rotate_existing,
    )

    receipt = run_guest_trades(
        manifest,
        config,
        manifest_label=str(manifest_path),
    )
    if args.receipt_out:
        write_receipt(receipt, Path(args.receipt_out))

    print(format_summary(receipt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
