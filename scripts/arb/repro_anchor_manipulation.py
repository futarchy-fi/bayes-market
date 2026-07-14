#!/usr/bin/env python3
"""Repro: a transient net-marginal spike drives a lasting AMM move.

The arb agent takes the `net` venue's marginal as ground truth and marks the
AMM/book to it. The net is *tradable* — a probability edit moves the marginal
(for a frozen stake). So an attacker can spike the net for a moment, let the
agent chase the AMM to the spiked value with real credits, then let the net
revert — leaving the AMM stranded off-true and the agent's balance spent. It
is the textbook oracle-manipulation shape: the consumer trusts an
instantaneous reading.

Fix (anchor_alpha < 1): the agent follows an EMA of the marginal, so a
one-tick spike barely moves it and a manipulator must HOLD the net off-true
for many ticks (sustained stake + exposure) to move the agent at all.

Scenario per run: converge the AMM to the true net (0.60); an attacker spikes
gcx_a to 0.95 for ONE tick; the net reverts to 0.60; the agent runs a few
more ticks. We report the peak AMM displacement and credits the agent burned.

    python3 scripts/arb/repro_anchor_manipulation.py                # both
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


async def scenario(alpha: Decimal, label: str) -> None:
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
            policy = ArbPolicy(client, ArbConfig(report_only=False, anchor_alpha=alpha))

            # 1) converge to the true net
            for _ in range(6):
                await policy.tick(instrument)
            converged = amm_yes()

            # 2) attacker spikes the net for ONE tick, agent reacts, net reverts
            app.state.joint.place_edit(attacker.id, VARIABLE, "yes", SPIKE)
            await policy.tick(instrument)
            after_spike = amm_yes()
            app.state.joint.place_edit(attacker.id, VARIABLE, "yes", float(TRUE))

            # 3) let the agent settle back
            peak = after_spike
            for _ in range(6):
                await policy.tick(instrument)
                peak = max(peak, amm_yes())

        burned = start_bal - bal()
        displacement = after_spike - converged
        print(f"\n[{label}] anchor_alpha={alpha}")
        print(f"  converged AMM (true 0.60):     {converged:.4f}")
        print(f"  AMM after 1-tick net spike→.95: {after_spike:.4f}  "
              f"(chased +{displacement:.4f})")
        print(f"  peak AMM displacement:          {peak:.4f}")
        print(f"  agent credits burned on the manipulation round: {burned:.2f}")


async def main() -> None:
    # The knob is a tradeoff, shown explicitly: smaller alpha = a transient
    # spike does less damage, but legitimate net moves are also followed more
    # slowly. It converts one-shot manipulation into sustained-cost
    # manipulation; it does not eliminate it.
    await scenario(Decimal("1.0"), "CURRENT — no smoothing")
    await scenario(Decimal("0.3"), "FIXED — alpha 0.30 (default)")
    await scenario(Decimal("0.1"), "FIXED — alpha 0.10 (more resistant)")


if __name__ == "__main__":
    asyncio.run(main())
