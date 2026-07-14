#!/usr/bin/env python3
"""Regression demo: bounded LMSR sizing converges on thin and deep AMMs.

The old depth-blind ``budget_cap * gap`` rule overshot a thin AMM and reversed
on every pass. The current agent sizes from the listing's ``b``, limits each
selected-outcome move, and lets the server recompute the target atomically.
Both thin and deep cases therefore approach the reference without flipping.

This drives the real ArbPolicy against the real in-process exchange over
several ticks and prints, per tick, the AMM YES price, the gap to the net
anchor (0.60), and the agent's balance. Run from the repository root:

    python -m scripts.arb.repro_overshoot            # thin (b=3)
    python -m scripts.arb.repro_overshoot --b 20     # deep

Standalone; uses ASGITransport against the app in-process (no network, no
deploy). State is ephemeral under a tmp dir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from decimal import Decimal

os.environ.setdefault("FUTARCHY_ADMIN_KEY", "repro-admin-key")

import httpx

import exchange.core.api as api_module
from exchange.agents.arb import ArbConfig, ArbPolicy, HttpExchange
from exchange.core.api import _authenticate_github_identity, app
from exchange.core.lmsr import prices
from exchange.core.middleware import rate_limiter
from exchange.core.models import reset_counters
from exchange.venues.joint.test_venue import TINY_SEEDS

ANCHOR = Decimal("0.60")  # g1 net marginal in TINY_SEEDS


async def run(b: Decimal, ticks: int) -> None:
    tmp = tempfile.mkdtemp(prefix="arb-repro-")
    seeds = os.path.join(tmp, "seeds.json")
    tiny = json.loads(json.dumps(TINY_SEEDS))
    for market in tiny["markets"].values():
        market["status"] = "active"
    with open(seeds, "w") as handle:
        json.dump(tiny, handle)
    os.environ["EXCHANGE_SEEDS_PATH"] = seeds
    api_module.STATE_PATH = os.path.join(tmp, "state.json")
    reset_counters()
    rate_limiter.buckets.clear()

    async with api_module.lifespan(app):
        amm, _ = app.state.me.create_market("A", "arb-repro", "a", {}, b=b)
        auth = await _authenticate_github_identity({"id": 9001, "login": "arb"})
        account = app.state.risk.get_account(auth.account_id)
        instrument = {
            "instrumentId": "repro-a",
            "title": "A",
            "listings": [
                {"venue": "net", "marketId": "g1"},
                {"venue": "amm", "marketId": str(amm.id)},
            ],
        }

        start_balance = account.available_balance
        print(f"\nAMM b={b}  (deep≈20, thin≈3)   net anchor={ANCHOR}")
        print(f"start: amm_yes={prices(amm.q, amm.b)['yes']:.4f}  "
              f"balance={start_balance:.2f}")
        print(f"{'tick':>4} {'amm_yes':>9} {'gap':>8} {'side':>5} "
              f"{'balance':>10} {'spent':>8}")

        transport = httpx.ASGITransport(app=app)
        async with HttpExchange("http://test", auth.api_key, transport=transport) as client:
            policy = ArbPolicy(client, ArbConfig(report_only=False))
            prev_balance = start_balance
            for tick in range(1, ticks + 1):
                actions = await policy.tick(instrument)
                yes = prices(amm.q, amm.b)["yes"]
                gap = yes - ANCHOR
                balance = app.state.risk.get_account(auth.account_id).available_balance
                buy = next((a for a in actions if a.kind in ("buy", "would_buy")), None)
                side = buy.outcome if buy else "-"
                spent = prev_balance - balance
                print(f"{tick:>4} {yes:>9.4f} {gap:>+8.4f} {side:>5} "
                      f"{balance:>10.2f} {spent:>8.2f}")
                prev_balance = balance

        total_spent = start_balance - app.state.risk.get_account(auth.account_id).available_balance
        final_yes = prices(amm.q, amm.b)["yes"]
        settled = abs(final_yes - ANCHOR) < Decimal("0.02")
        print(f"result: final amm_yes={final_yes:.4f}  "
              f"{'CONVERGED' if settled else 'DID NOT CONVERGE'} to anchor; "
              f"total spent={total_spent:.2f} credits over {ticks} ticks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b", type=Decimal, default=Decimal("3"),
                        help="AMM liquidity b (thin≈3, deep≈20)")
    parser.add_argument("--ticks", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(run(args.b, args.ticks))


if __name__ == "__main__":
    main()
