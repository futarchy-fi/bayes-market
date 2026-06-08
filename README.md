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

## Deployment

Runs on the **farol** host as a systemd user service (`bayes-market.service`, `WorkingDirectory=~/bayes-market`,
binding `127.0.0.1:3205`). It is exposed publicly at `bayes.futarchy.ai` via Caddy
(`bayes.futarchy.ai → 127.0.0.1:3205`) behind a Cloudflare tunnel. State is in-memory, so a service
restart re-seeds the initial markets.

See `docs/` for the event-sourcing contract and endpoint-ownership specifications.
