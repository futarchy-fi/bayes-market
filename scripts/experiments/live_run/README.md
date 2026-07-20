# Live run — combinatorial-vs-flat agent forecasting on the exchange

The live deployment of the experiment arc (Stages 0–4). Real LLM agents trade a
cluster of real questions two ways — the **net venue** (combinatorial) and
**independent AMM markets** (flat) — with the exchange's log-score settlement.
Kelvin approved the prod run (2026-07-15). This packages the three prep pieces.

## 1. Wiring confirmed (dry-run against the live API, read-only)

- The combinatorial net is live at **`https://api.futarchy.ai/v1/net`** —
  909 AI-takeoff markets, real `variableId`s (`ftm_agi_by_2041`, …).
  (`bayes.futarchy.ai` is the old standalone; it 404s on `/v1/net`.)
- The net DAG has **196 genuine cross-family conditional edges** (e.g.
  `ftm_agi_by_2041 → ftm_auto_goods_t0_by_2039` — AGI drives automation),
  distinct from the deterministic by-year ladders. **Use these** — Stage 3
  showed pure ladders only test coherence, not information.
- Trade path (net venue): `POST /v1/net/orders`
  `{variableId, outcomeId, target, context?}`, Bearer auth. Preview stake
  first: `POST /v1/net/orders/preview` (same body). `stage4_runner.py`'s
  `ExchangeBackend` emits exactly this shape (verified in dry-run).
- **Live wiring VERIFIED end-to-end (read-only, 2026-07-15, account 47):**
  `GET /v1/me` → 200 (1000 credits); marginal preview → 200 (AGI at 0.443,
  stake 10.7 to move to 0.55); **conditional preview** `goods|AGI=yes` → 200
  (**live P = 0.626**, stake 36.8 to move to 0.30). Net liquidity **b=50**.
  The runner drives the live exchange.
- **Cloudflare gotcha:** authenticated routes 403 (error 1010) on non-browser
  User-Agents; a browser UA is required. `ExchangeBackend` now sends one.
- Marginal read endpoint takes `GET /v1/net/marginal?variable=<id>` (param is
  `variable`, not `variableId`); `context` as a URL-encoded JSON object.

## 2. Question set + information design (`question_set.json`)

A small cluster with **genuine conditional structure** (AGI → goods automation),
not a deterministic ladder. Information is split so:

- **marginal agents** know only a marginal (P(AGI), or P(goods automation)) —
  usable by BOTH markets;
- **relational agents** know the *dependence* (goods automation is gated by AGI)
  — expressible ONLY in the net (a conditional edit); the flat market drops it.

This is the Stage 1b design on real live questions. It is the case that tests
the dimension that matters (relational information), which the Stage 3 backtest
questions (price ladders) could not.

## 3. Admin setup package for Kelvin (needs `FUTARCHY_ADMIN_KEY`)

The net questions already exist. Remaining admin steps (he has the admin key;
these are the concrete inputs, not permission):

```bash
API=https://api.futarchy.ai
ADMIN="Authorization: Bearer $FUTARCHY_ADMIN_KEY"

# (a) N agent service-accounts + credits — returns each account's API key
for i in $(seq 1 9); do
  curl -s -XPOST $API/v1/admin/service-accounts -H "$ADMIN" \
    -H 'Content-Type: application/json' -d "{\"label\":\"exp-agent-$i\"}"
  # then mint play credits to each returned accountId:
  # curl -s -XPOST $API/v1/admin/mint -H "$ADMIN" -d '{"accountId":<id>,"amount":"1000"}'
done

# (b) FLAT arm: list the SAME cluster questions as INDEPENDENT AMM markets,
#     in a separate experiment category so the public leaderboard stays clean:
#   curl -s -XPOST $API/v1/admin/markets -H "$ADMIN" -d '{
#     "question":"AI automates 5% of goods tasks by 2039","category":"experiment",
#     "category_id":"exp/combinatorial-vs-flat", ...}'
```

Hand back to the runner: **(1)** the service-account API keys (one per agent),
**(2)** confirmation of the flat-arm AMM market ids, **(3)** the experiment
category/namespace. Then the runner does the rest.

## Run procedure

1. Orchestrator elicits each agent's decision via `stage4_runner.build_prompt`
   (neutral; both trade types offered), using its private brief from
   `question_set.json` and live prices from `GET /v1/net/markets`.
2. `ExchangeBackend(execute=False)` → **preview** every intended order first
   (confirm stakes/acceptance). Only then flip `execute=True` with the
   service-account key.
3. Net venue = combinatorial arm; independent AMM markets = flat arm.
4. Measure (see `question_set.json`): coherence + vs-crowd now; agent P&L via
   log-score payout (does scoring arbitrage away the false-independence
   pollution? — the thing the offline model couldn't test); resolution accuracy
   is long-horizon (the fast verdict stays with the Stage 3 backtest).

## Flat-arm parameters (for Kelvin to create the AMM markets)

Match the net venue's depth so the comparison is fair: net **b=50**. For a
binary AMM, `max_loss = b·ln 2`, so **funding ≈ 34.7 credits** per market gives
**b ≈ 50**. Create the 4 cluster questions as independent AMM markets in
category `exp/combinatorial-vs-flat`, funding ≈ 35 each.

## Setup status (2026-07-15, via Kelvin's agent)

- 9 service-accounts on **api.futarchy.ai** (accounts 47–55), 1000 credits
  each. Keys held locally outside the repo (`~/.config/futarchy-exp/`), never
  committed. (An earlier key set on `bayes.futarchy.ai` was the wrong host —
  discarded.)
- Base URL for everything: **`https://api.futarchy.ai`**.
- The resident arb only touches instruments in the admin registry; the
  experiment's flat AMM markets will **not** be registered as instruments, so
  they are free of arb interference. Experiment accounts are disjoint from the
  arb/calibrator, and these keys are for the experiment only.

## Safety

Nothing here fires a live trade without `execute=True` **and** a service-account
key. Kelvin's rule: `execute=True` only after this `live_run/` is merged into
`futarchy-fi/bayes-market` (reviewable runner in the repo). Preview first
(read-only), then execute. Target the experiment namespace, never the public
leaderboard.
