#!/usr/bin/env python3
"""Repro: reference filters bound a manipulated NET anchor.

The NET venue is tradable, so its marginal is a reference rather than truth.
This scenario first shows that a one-sample 0.60 -> 0.95 spike is rejected.
It then holds the spike for a confirming sample and shows that EMA smoothing
plus the atomic two-percentage-point action cap bounds the resulting AMM move.

Run from the repository root:

    python -m scripts.arb.repro_anchor_manipulation
"""

from __future__ import annotations

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

TRUE = Decimal("0.60")       # gcx_a true marginal
SPIKE = 0.95                 # attacker's transient push
VARIABLE = "gcx_a"           # g1's variableId


async def scenario() -> None:
    tmp = tempfile.mkdtemp(prefix="arb-manip-")
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
        amm, _ = app.state.me.create_market("A", "manip", "a", {}, b=Decimal("20"))
        agent = await _authenticate_github_identity({"id": 9100, "login": "arb"})
        attacker = app.state.risk.create_account(balance=Decimal("100000"))
        instrument = {
            "instrumentId": "manip-a", "title": "A",
            "listings": [
                {"venue": "net", "marketId": "g1"},
                {"venue": "amm", "marketId": str(amm.id)},
            ],
        }
        transport = httpx.ASGITransport(app=app)

        def amm_yes() -> Decimal:
            return prices(amm.q, amm.b)["yes"]

        def bal() -> Decimal:
            return app.state.risk.get_account(agent.account_id).available_balance

        start_bal = bal()
        async with HttpExchange("http://test", agent.api_key, transport=transport) as client:
            policy = ArbPolicy(client, ArbConfig(report_only=False))

            # 1) converge to the true net
            for _ in range(6):
                await policy.tick(instrument)
            converged = amm_yes()

            # 2) One spike sample is rejected, then the reference reverts.
            app.state.joint.place_edit(attacker.id, VARIABLE, "yes", SPIKE)
            await policy.tick(instrument)
            after_one_spike = amm_yes()
            app.state.joint.place_edit(attacker.id, VARIABLE, "yes", float(TRUE))
            await policy.tick(instrument)
            await policy.tick(instrument)

            # 3) A sustained spike clears the two-sample filter, but one AMM
            # action remains capped at two percentage points.
            before_sustained = amm_yes()
            app.state.joint.place_edit(attacker.id, VARIABLE, "yes", SPIKE)
            await policy.tick(instrument)
            after_first_sustained = amm_yes()
            await policy.tick(instrument)
            after_confirmed = amm_yes()

        burned = start_bal - bal()
        print(f"  converged AMM (true 0.60):       {converged:.4f}")
        print(f"  after one-sample spike to 0.95:  {after_one_spike:.4f}")
        print(f"  after first sustained sample:    {after_first_sustained:.4f}")
        print(f"  after confirming spike sample:   {after_confirmed:.4f}")
        print(f"  confirmed one-tick AMM movement: "
              f"{after_confirmed - before_sustained:.4f}")
        print(f"  total agent credits spent:       {burned:.2f}")

        assert after_one_spike == converged
        assert after_first_sustained == before_sustained
        assert after_confirmed - before_sustained <= Decimal("0.02")


async def main() -> None:
    await scenario()


if __name__ == "__main__":
    asyncio.run(main())
