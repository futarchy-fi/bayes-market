# exchange/agents — resident arbitrage agent

`arb.py` is a resident bot that keeps an instrument's AMM and book listings
aligned to its **net** (Bayes-network) listing. For each registry instrument
it reads the net marginal as the reference price, nudges the AMM toward it,
and two-sided-quotes the book around it. It runs headless under systemd
(`deploy/futarchy-arb.service`, `--execute --interval 30`).

This file is the contract the agent is written against. It is a naive
price-follower by design; the notes below are the guardrails that keep that
naivety from misbehaving, and the limits that are known and deliberately not
yet addressed. **Read this before changing the sizing, the anchor, or the
loop** — each guardrail exists because its absence was a demonstrated failure
(see `scripts/arb/repro_*.py`).

## What the agent assumes

- **Binary markets.** AMM sizing and book quoting assume `yes`/`no`. A
  multi-outcome AMM would be mis-sized.
- **The net marginal is a *reference*, not gospel.** It is a tradable venue;
  anyone can move it. The agent must never treat a single reading as truth
  (see anchor smoothing below).
- **Every remote call can fail.** The agent holds a user API key subject to
  the 60/min rate limit and will occasionally 429.
- **Play credits.** Balances are exchange credits, not fiat. Caps are sized
  for that; revisit every cap before any real-value deployment.

## Invariants the code enforces (do not regress)

1. **Sized to the anchor, not to the gap.** An AMM correction spends the
   credits that move the LMSR price *to* the anchor
   (`b·ln((1-p0)/(1-p1))` / `b·ln(p0/p1)`), capped at `budget_cap`. The old
   `budget_cap * gap` was depth-blind and oscillated a thin AMM, bleeding
   spread every tick. Repro: `scripts/arb/repro_overshoot.py`.
2. **Follows an EMA of the anchor, not the instant reading.**
   `anchor_alpha` (default 0.3) smooths the net marginal so a one-tick spike
   can't be converted into a permanent AMM move; a manipulator must *hold*
   the net off-true for many ticks. Mitigation, not elimination — the knob
   trades resistance against speed of following real moves. Repro:
   `scripts/arb/repro_anchor_manipulation.py`.
3. **The balance floor is reserved, not just checked.** A tick spends at most
   `available - min_balance` across all its AMM buys and book collateral, so
   it never dips the account below the floor mid-tick.
4. **A transient error never tears down the loop.** `run_pass` isolates the
   instruments fetch and each per-instrument tick; a failure is logged and
   the sweep continues, retrying next interval rather than crash-looping
   under systemd.

## Known limitations (deliberately not yet fixed)

- **One-sided book inventory.** The agent only ever posts *bids* (both
  sides), never asks, and has no inventory manager. Asymmetric fills
  accumulate a directional position it never unwinds. Positions are acquired
  at favorable prices (inside the anchor ± delta spread), so this is exposure
  growth, not an immediate loss — but a real market-making bot needs ask-side
  quoting and an inventory limit. Left as a design task, not a quick patch,
  precisely because a half-built inventory manager in money code is worse
  than a documented gap.
- **No backoff on sustained failure.** `run_pass` survives a transient error,
  but repeated failures just retry every `interval`. A backoff/circuit-breaker
  is a sensible follow-up.
- **Per-instrument, not portfolio-level, risk.** Caps apply per tick per
  instrument; there is no global exposure or loss budget across instruments.
