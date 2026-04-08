# T553 Current-Architecture Cache Invalidation Boundary Freeze

Date: 2026-04-08
Branch: `ff/Ttemporal-fleet-i57-r1-bayes-t553-freeze-current-cache-boundary`

## Question

Reconcile three things:

- the historical unmerged `task/T553` branch
- the historical unmerged `task/T554` branch
- the rebuilt Bayes backend in `apps/bayes-market/backend/server.py`

and explicitly decide the cache invalidation boundary for the current architecture:

- whether any public `/v1/cache/invalidate/*` endpoints remain in scope
- whether T553 is still public or internal
- where the line sits between T553 and T554

## Findings

### 1. The current public Bayes surface is market-scoped and contains no cache-control routes

The checked-in backend now advertises only:

- `GET /health`, `GET /healthz`
- `GET /v1/markets`
- `GET /v1/markets/{id}`
- `GET /v1/markets/{id}/events`
- `GET /v1/markets/{id}/engine-stats`
- `POST /v1/markets/{id}/orders/probability-edit`
- `POST /v1/markets/{id}/orders/event-trade`
- `GET /v1/accounts/{id}/risk`

There is no current public `/v1/cache/*` surface and no current public `/v1/compile*` surface.

Evidence:

- `service_index_payload()` in `apps/bayes-market/backend/server.py` advertises only the market-scoped routes above.
- `route_request(...)` in the same file handles only those market/account resources and otherwise raises `404 not_found`.
- `tests/test_bayes_market_api.py` explicitly asserts that the legacy unscoped write route `POST /v1/orders/probability-edit` returns `404`.
- repo-local source search on the current branch finds no live `/v1/cache` or `/v1/compile` path handlers in the rebuilt backend.

This matters because T553 cannot be frozen as a public route contract if the current architecture no longer exposes that family of routes at all.

### 2. The rebuilt backend already localizes compile/cache state per market

The current backend does have cache/compile state, but it is modeled as an internal per-market read model:

- `MARKET_ENGINE_STATS` is keyed by `market_id`
- `ensure_market_engine_state(...)` initializes cache hits/misses, compile metadata, and cliques per market
- `refresh_market_compile_snapshot(...)` rebuilds:
  - `compile_id`
  - `compile_type`
  - `source_state_hash`
  - `compile_time_ms`
  - `memory_bytes`
  - `cliques`

from the current market state

- `get_market_engine_stats(...)` exposes that state only through `GET /v1/markets/{id}/engine-stats`

That is already a market-scoped boundary, not a process-global invalidation API.

### 3. In the current architecture, the invalidation/rebuild trigger is internal to accepted ProbabilityEdit writes

`route_request(...)` records per-market engine request telemetry for both write routes, but only one route refreshes the compile snapshot:

- accepted `POST /v1/markets/{id}/orders/probability-edit`
  - records a market-local engine request
  - then calls `refresh_market_compile_snapshot(market_id, compile_time_ms=duration_ms)` on `201`
- accepted `POST /v1/markets/{id}/orders/event-trade`
  - records a market-local engine request
  - does **not** call `refresh_market_compile_snapshot(...)`

The test suite confirms that split:

- after an accepted ProbabilityEdit, `GET /v1/markets/m1/engine-stats` returns a populated `compile_id`, `compile_type`, `source_state_hash`, and one-clique snapshot
- after an accepted EventTrade, `GET /v1/markets/m1/engine-stats` shows request counters but still leaves `compile_id`, `compile_type`, and `source_state_hash` as `null`

So the current architecture already expresses a narrow invalidation boundary:

- mutate market probabilities -> refresh that market's compiled snapshot
- non-mutating EventTrade -> do not rebuild compiled state

### 4. Historical `task/T553` was a different server architecture with public cache debug/control routes

The historical `task/T553` branch consists of:

- `a5151687fb` — `T553: Implement junction-tree cache invalidation logic`
- `a925238156` — `T553: harden junction-tree cache invalidation`

That branch added internal types such as:

- `Clique`
- `Separator`
- `CacheEntry`
- `JunctionTreeCacheManager`

and also exposed public HTTP routes such as:

- `GET /v1/cache/cliques`
- `GET /v1/cache/separators`
- `GET /v1/cache/stats`
- `GET /v1/cache/state`
- `POST /v1/cache/cliques`
- `POST /v1/cache/separators`
- `PUT /v1/cache/invalidate/node/{node_id}`
- `PUT /v1/cache/invalidate/clique/{clique_id}`
- `PUT /v1/cache/invalidate/scope`

The companion `apps/bayes-market/backend/test_cache_invalidation.py` on that branch is also implementation-level: it primarily tests those internal cache datatypes and manager behaviors directly.

That is useful historical input, but it is not the current public contract.

### 5. Historical `task/T553` also predates the rebuilt market-scoped write surface

The same `task/T553` branch still handled:

- `POST /v1/orders/probability-edit`
- `POST /v1/orders/event-trade`

rather than the current:

- `POST /v1/markets/{id}/orders/probability-edit`
- `POST /v1/markets/{id}/orders/event-trade`

So the public `/v1/cache/*` routes from `task/T553` were tied to an older, unscoped server surface that the rebuilt backend has already replaced.

That makes it unsafe to "restore T553" literally. Doing so would revive both:

- outdated cache-control routes
- outdated write-route scoping assumptions

### 6. Historical `task/T554` owns the broader compile-propagation contract space

The historical `task/T554` branch consists of:

- `c4f3944f39` — `T554: Implement incremental compile hook contracts`
- `836f0523db` — `T554: Update task metadata`

That branch introduced:

- `CompileHookType`
- `CompileResult`
- `IncrementalCompiler`
- compile history/statistics
- cache invalidation with dependency tracking
- hook registration/unregistration

and public routes such as:

- `GET /v1/compile/stats`
- `GET /v1/compile/hooks`
- `GET /v1/compile/history`
- `POST /v1/compile`
- `POST /v1/compile/invalidate`
- `POST /v1/compile/hooks/register`
- `POST /v1/compile/hooks/unregister`

This is a broader contract than "refresh the current market's compiled snapshot after a market mutation." It is explicit compile orchestration and propagation control.

That scope belongs to T554, not to a frozen interpretation of T553 on the rebuilt backend.

### 7. The planning docs already support keeping T553 narrow and deferring broader propagation

Repo docs already separate the two tasks:

- `apps/bayes-market/docs/t537-epic-execution-baseline.md`
  - T553: junction-tree cache invalidation logic
  - T554: incremental compile hook contracts
- `apps/bayes-market/docs/t538-scope-matrix.md`
  - exact bounded-treewidth inference is MVP work
  - "incremental compile and cache strategy hardening" is a V2 throughput optimization row linked to T553, T554, and T567
- `apps/bayes-market/docs/t539-mvp-launch-gate.md`
  - requires `GET /v1/markets/{id}/engine-stats`
  - does not require any public `/v1/cache/*` or `/v1/compile*` endpoints

So the current docs already point toward:

- market-scoped engine visibility as public contract
- cache/compile hardening as deeper engine work, not mandatory public control surface

## Freeze Decision

### 1. T553 stays internal and market-scoped on the rebuilt backend

For the current architecture, T553 should be read as:

- internal invalidation/rebuild of the current compiled state for a single market
- behind market-scoped write handlers
- surfaced only indirectly through `GET /v1/markets/{id}/engine-stats`

It should **not** be read as a surviving public cache-control API family.

### 2. Do not revive public `/v1/cache/invalidate/*` endpoints

The following historical routes are explicitly out of the current public contract:

- `PUT /v1/cache/invalidate/node/{node_id}`
- `PUT /v1/cache/invalidate/clique/{clique_id}`
- `PUT /v1/cache/invalidate/scope`

And the broader `/v1/cache/*` inspection routes are also out of scope:

- `GET /v1/cache/cliques`
- `GET /v1/cache/separators`
- `GET /v1/cache/stats`
- `GET /v1/cache/state`
- `POST /v1/cache/cliques`
- `POST /v1/cache/separators`

Adding any of those back would be a new public API expansion on top of the rebuilt market-scoped server, not a faithful freeze of the current architecture.

### 3. The current invalidation boundary is "refresh this market's compiled snapshot," not "expose cache controls"

Freeze the current behavior as:

- ProbabilityEdit acceptance may invalidate/rebuild the compiled state for the addressed market
- that rebuild is internal
- the public read model is `GET /v1/markets/{id}/engine-stats`
- EventTrade does not currently imply compiled-state rebuild because it does not mutate market marginals in this stub

This is the narrowest interpretation that matches the checked-in server and tests.

### 4. Broader incremental compile propagation belongs to T554

The following concerns are left to T554, not frozen into T553 on this branch:

- explicit incremental compile hooks
- hook registration/unregistration contracts
- compile history/statistics APIs
- explicit compile invalidation APIs
- host-global or multi-market propagation semantics
- dependency-tracked propagation beyond the current market-scoped rebuild path

If any of those are needed publicly, they should be introduced through an explicit T554-style contract decision, not by quietly reanimating `task/T553`'s old `/v1/cache/*` routes.

## Consequence

For the rebuilt Bayes backend, the safe contract assumptions are:

- public API stays market-scoped
- cache invalidation remains an internal engine concern
- `GET /v1/markets/{id}/engine-stats` is the public observability surface for compile/cache state
- no public `/v1/cache/*` routes exist
- no public `/v1/compile*` routes are implied by T553
- broader compile propagation contracts remain deferred to T554

That preserves the current architecture instead of mixing old pre-rebuild debug routes back into the live public surface.

## Verification

Runtime verification on this branch:

```bash
python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'
```

Result:

- `Ran 128 tests in 4.403s`
- `OK`
