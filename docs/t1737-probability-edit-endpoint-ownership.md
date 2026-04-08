# T1737 ProbabilityEdit Endpoint Ownership Findings

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-d6g-r1-bayes-t1737-find-endpoint-owner`

## Status Update

This document captures the pre-restoration findings from the earlier ownership pass.
On branch `ff/Ttemporal-fleet-d6g-r2-bayes-t1737-restore-backend-surface`, the missing backend surface described below has been restored via:

- `apps/bayes-market/backend/server.py`
- `tests/test_bayes_market_api.py`
- `infra/host/systemd/bayes-market.service`
- `infra/secrets/env/bayes-market.env.example`
- `scripts/bayes_public_route_probe.sh`

## Question

Find the real service, route, and handler that own `/v1/markets/{id}/orders/probability-edit`, or confirm that the backend endpoint surface is still missing.

## Findings

### 1. Current branch does not contain a Bayes backend implementation

- `apps/bayes-market/` in this branch contains only docs plus `scripts/t587_load_harness.py`.
- There is no `apps/bayes-market/backend/` tree in `HEAD`.
- There is no `infra/host/systemd/bayes-market.service` file in `HEAD`.
- There is no `infra/secrets/env/bayes-market.env.example` file in `HEAD`.
- Repo-wide search for `probability-edit`, `ProbabilityEdit`, and related route strings only hits Bayes docs, not live source files.

### 2. The last identifiable code owner exists only on unmerged task branches

The implementation history points to the Bayes HTTP server at `apps/bayes-market/backend/server.py`, but only on task branches that are not merged into the current branch.

#### Legacy owner before contract alignment

- Branch/commit: `task/T569`, commit `42cefcd93e828b62a447e400117fffb73ba02888`
- Service/module: `apps/bayes-market/backend/server.py`
- Handler: `MarketHandler.do_POST`
- Route at that point: `POST /v1/orders/probability-edit`
- Business helper: `create_probability_edit_order(market_id, probabilities, user_id)`

That version used the pre-alignment payload shape (`market_id` plus `probabilities`) and does not match the documented market-scoped route.

#### Contract-aligned owner

- Branch tip: `task/T1736`
- Alignment commit: `4490d24ad819ab9bfb12bdb06e366bca92c5f863`
- Service/module: `apps/bayes-market/backend/server.py`
- Handler: `BayesHandler.do_POST`
- Route logic: path is split and accepted only when it matches `/v1/markets/{marketId}/orders/probability-edit`
- Business helper: `create_probability_edit_order(market_id, payload, account_id)`

That branch is the last identifiable source that actually owns the documented route.

### 3. The route contract is verified only on the historical task branch

`task/T1736:apps/bayes-market/backend/test_probability_edit.py` contains direct HTTP coverage showing:

- `POST /v1/markets/m1/orders/probability-edit` returns `201`
- legacy `POST /v1/orders/probability-edit` returns `404`

So the aligned route did exist in source, but only on `task/T1736`.

### 4. Related Bayes API work is fragmented across separate unmerged branches

- `task/T568` contains a different `apps/bayes-market/backend/server.py` that implements `GET /v1/markets` and `GET /v1/markets/{id}`.
- `task/T1736` contains the contract-aligned ProbabilityEdit POST route.
- `task/T568`, `task/T569`, and `task/T1736` are all unmerged relative to this branch.

This means there is no single current branch in this repo where the documented Bayes API surface is present as one integrated backend.

### 5. Deploy docs describe a service that is not present in the current tree

`docs/ops/bayes-market-deploy.md` and `apps/bayes-market/docs/t581-dns-cloudflare-tunnel-public-runbook.md` describe:

- service binary: `python3 apps/bayes-market/backend/server.py`
- local bind: `127.0.0.1:3200`
- systemd unit: `bayes-market.service`

But:

- the current branch does not contain that backend tree
- the current branch does not contain the referenced systemd unit
- the current branch does not contain the referenced env template

Even `task/T1736` only contains the backend source and test; it still does not contain `infra/host/systemd/bayes-market.service` or `infra/secrets/env/bayes-market.env.example`.

There is also a doc/code mismatch: T581 expects `/healthz` to include `"service": "bayes-market"`, while `task/T1736`'s health handler returns only `{"status":"ok","timestamp":...}`.

### 6. The live listener on port 3200 is not Bayes

Local runtime checks on this host show:

- `systemctl --user status bayes-market.service` -> unit not found
- `ss -ltnp` shows `127.0.0.1:3200` is owned by `/home/kelvin/.local/bin/node backend/api.mjs`
- that process is running from `/home/kelvin/repos/futarchy-fi/simple-bond`
- `curl http://127.0.0.1:3200/healthz` returns `404 {"error":"Not found"}`
- `curl http://127.0.0.1:3200/v1/markets/m1/orders/probability-edit` also returns `404 {"error":"Not found"}`

So the current host runtime on `:3200` is not the Bayes service described by the docs and does not own the ProbabilityEdit route.

## Conclusion

The last real, contract-aligned code owner for `/v1/markets/{id}/orders/probability-edit` is the unmerged `task/T1736` branch:

- service/module: `apps/bayes-market/backend/server.py`
- HTTP handler: `BayesHandler.do_POST`
- order-construction helper: `create_probability_edit_order(...)`

On the analyzed branch, the backend endpoint surface is still missing. The Bayes API exists only as historical, unmerged task-branch work plus forward-looking docs. Before contract-alignment or integration work can proceed on the current branch, the backend surface must be restored, scaffolded, or merged in from the task branches.

## Recommended Unblock

1. Treat `task/T1736` as the source of truth for the market-scoped ProbabilityEdit route and payload semantics.
2. Reconcile it with `task/T568` so market read routes and market-scoped order routes live in the same backend tree.
3. Add the missing runtime packaging (`bayes-market.service` and env template) or revise the deploy docs to match the actual state.
