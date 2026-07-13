# bayes-market

A Bayesian prediction-market engine — an **event-sourced** market backend where prices are
driven by a Bayesian inference model and an LMSR market maker, with a React/D3 frontend for
trading and visualising the underlying belief network.

Live at **https://bayes.futarchy.ai**.

## Architecture

- **Backend** — `backend/server.py`: a single-module HTTP service built on the Python standard
  library (`http.server`), dispatched through an in-process router. Market state is **event-sourced**
  (append-only events per market, hash-chained), held in memory — so a restart loses state and the
  markets must be re-seeded. Key modules:
  - `backend/inference/` — the Bayesian model (config, contracts, current model, cache invalidation).
  - `backend/lmsr.py` — the LMSR (logarithmic market scoring rule) market maker.
  - `backend/formula_schema.py` — the event/formula contract schema.
- **Frontend** — `frontend/` (`bayes-market-ui`): React + Vite + TanStack Query, with D3
  (`d3-force`/`d3-zoom`/`d3-drag`) for the belief-network graph and trading UI.

## Run it

**Backend** (defaults to port 3205, overridable via `BAYES_MARKET_PORT`):

```bash
python3 backend/server.py --host 127.0.0.1 --port 3205
```

**Frontend**:

```bash
cd frontend && npm install && npm run dev      # build: npm run build · test: npm test
```

## HTTP API (`/v1`)

| Endpoint | Purpose |
|---|---|
| `GET /healthz`, `GET /v1/health`, `GET /v1/version`, `GET /v1/stats` | liveness / build / aggregate stats |
| `GET /v1/markets`, `GET /v1/markets/{id}` | list / fetch markets |
| `GET /v1/markets/{id}/events`, `/trades`, `/meta`, `/engine-stats` | per-market event log, trades, metadata, engine internals |
| `GET /v1/accounts/{id}/positions`, `/exposure`, `/pnl`, `/risk` | per-account portfolio views |

### Self-serve markets & resolvers

Authenticated users can create an AMM market with `POST /v1/markets`:

```json
{
  "question": "Will the release ship this week?",
  "outcomes": ["yes", "no"],
  "deadline": "2030-01-02T12:00:00Z",
  "funding": "25"
}
```

The funding is transferred from the creator's credits into the AMM. It must
be between `MIN_USER_FUNDING` (default `10`) and `MAX_USER_FUNDING` (default
`500`). A deadline is required, must be in the future, and may be at most 400
days away. `POST /v1/book/markets` accepts `question` and `deadline`; book
markets require no subsidy. `USER_MARKET_CAP` (default `10`) limits each
account's open self-serve markets across both venues.

Every market publishes its creator and resolver on its public detail route.
Self-serve markets use a `creator` resolver, admin-created markets use
`admin`, and pull-request webhook markets use `github_pr`. Creators may call
`POST /v1/markets/{id}/resolve` (or the corresponding `/void` route) only at
or after the deadline; the book venue uses the same operations below
`/v1/book/markets/{id}`.

Administrators can resolve or void any market at any time. This is the
dispute override: use the admin key with the venue's settlement route, or use
the existing AMM admin routes at `/v1/admin/markets/{id}/resolve` and
`/v1/admin/markets/{id}/void`.

### Sealed batch venue

The always-on batch venue is a binary LMSR that accepts one sealed pending
order per account and market in each round. Submit an authenticated
`POST /v1/batch/orders` with:

```json
{"marketId": 1, "outcome": "yes", "target": "0.70", "maxSpend": "10"}
```

Submitting again in the same round replaces that account's order and adjusts
its locked balance. `GET /v1/batch/orders/mine` returns only the caller's
pending orders; other accounts' targets, budgets, and orders are never
disclosed by public market routes.

Admins create markets with `POST /v1/batch/markets` using `question` and
either `b` or `funding` (`funding = b * ln(2)`). An optional positive
`roundSeconds` enables automatic rounds. A round can always be cleared
manually at `POST /v1/batch/markets/{id}/close-round`; clearing executes all
sealed orders competitively, advances the round, and publishes only the
clearing price and participant count in `roundHistory`. Admins finish a market
with `/resolve` and an `outcome`, or `/void` to refund filled cost basis and
release pending locks.

## Deployment

Runs on the **farol** host as a systemd user service (`bayes-market.service`, `WorkingDirectory=~/bayes-market`,
binding `127.0.0.1:3205`). It is exposed publicly at `bayes.futarchy.ai` via Caddy
(`bayes.futarchy.ai → 127.0.0.1:3205`) behind a Cloudflare tunnel. State is in-memory, so a service
restart re-seeds the initial markets.

See `docs/` for the event-sourcing contract and endpoint-ownership specifications.
