# Futarchy exchange

Imported from `futarchy-fi/agents@8df23de` (`exchange-v2`), implementing Plans A+B from the donor's `docs/superpowers/plans/2026-07-05-futarchy-exchange.md`.

The service combines a `RiskEngine` credit ledger, whose only money inlet is minting, with venue A's per-market LMSR (`MarketEngine`), venue B's staked probability edits (log-MSR), and an always-on complete-set order book. Venue B uses the same canonical factored inference engine in `backend/inference/` that powers `backend/server.py`; no inference implementation is vendored here.

## Configuration

| Variable | Purpose / default |
| --- | --- |
| `FUTARCHY_STATE` | Snapshot path (`./futarchy_state.json`) |
| `INITIAL_CREDITS` | Credits minted at signup (`1000`) |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | GitHub OAuth credentials (unset) |
| `GITHUB_OAUTH_REDIRECT_URI` | OAuth callback URL |
| `FUTARCHY_ADMIN_KEY` | Administrative API key (unset) |
| `EXCHANGE_SEEDS_PATH` | Venue B seeds file; unset disables venue B. Use `backend/seeds_takeoff.json`. |
| `JOINT_LIQUIDITY` | Venue B liquidity (`50`) |
| `JOINT_MAX_WIDTH` | Maximum inference width (`8`) |
| `RATE_LIMIT_PER_MIN` | Per-key request rate (`60`) |
| `CORS_ORIGINS` | Comma-separated allowed origins (`*`) |
| `FUTARCHY_DASHBOARD_URL` | Dashboard URL |
| `FUTARCHY_TREASURY_ID` | Treasury account ID (unset) |
| `MARKET_EXPIRY_CHECK_INTERVAL_SECONDS` | Expiry scan interval (`60`; `0` disables) |
| `LIQUIDITY_INITIAL` | Initial venue A liquidity (`40`) |
| `LIQUIDITY_STEP` | Venue A ramp increment (`40`) |
| `LIQUIDITY_RAMP_STEPS` | Venue A ramp step count (`4`) |
| `LIQUIDITY_RAMP_INTERVAL_MINUTES` | Venue A ramp interval (`30`) |
| `LIQUIDITY_BUDGET` | Venue A liquidity budget (`200`) |

## Run and test

Python 3.10 or newer is required. From the repository root:

```bash
pip install -r exchange/requirements.txt
uvicorn exchange.core.api:app
```

Run the exchange suite with:

```bash
python3 -m pytest exchange/ -q
```

The live Bayes server in `backend/server.py` is untouched and runs separately.

## Venue contract

A venue kind implements the runtime-checkable `Venue` protocol in
`exchange/venues/base.py`, uses the shared `RiskEngine` for every credit
mutation, and exposes quotes as read-only operations. To add one, subclass the
reusable `VenueContractSuite` in `exchange/venues/contract_suite.py`, provide
the three small venue/payload fixtures, and pass the suite. Then construct the
venue in `exchange.core.api.lifespan` and add it to
`app.state.venues_by_kind` under its unique `kind`; existing routes need not
change.

## Order-book venue

Create markets with `POST /v1/book/markets` (`{"question":"...","deadline":null}`), then place or quote orders with `{"marketId":1,"side":"bid|ask","outcome":"yes|no","price":"0.6000","size":"1.00"}`. Public market, aggregated depth, and fill history live under `/v1/book/markets`; authenticated order and position views live under `/v1/book/orders` and `/v1/book/positions`.

A YES bid and NO bid cross when their prices sum to at least 1, minting one YES+NO complete set per matched unit.
One credit per set is held in market escrow until the set is redeemed or the market settles.
YES asks and NO asks can cross to redeem a set; same-outcome bid/ask orders transfer existing shares.
All four intents share one YES-axis price-time-priority book, with NO prices represented as `1 - YES`.
