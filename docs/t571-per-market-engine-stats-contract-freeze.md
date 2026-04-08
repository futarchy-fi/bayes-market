# T571 Per-Market Engine Stats Contract Freeze

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-0s8-r1-bayes-t571-freeze-per-market-engine-stats-contract`

## Question

Reconcile the launch-gate route `GET /v1/markets/{id}/engine-stats` with the historical T571 payload shape:

- `engine`
- `cliques`
- `diagnostics`
- `meta`

and explicitly decide:

- the market-scoped response fields
- the error semantics
- whether any global `/v1/engine-stats` alias remains in scope

## Findings

### 1. The current branch exposes neither engine-stats route today

The restored backend currently advertises only:

- `GET /v1/markets`
- `GET /v1/markets/{id}`
- `GET /v1/markets/{id}/events`
- `POST /v1/markets/{id}/orders/probability-edit`
- `GET /v1/accounts/{id}/risk`

Evidence:

- `service_index_payload()` in `apps/bayes-market/backend/server.py` does not list either engine-stats route.
- `route_request(...)` in the same file has no branch for either `/v1/markets/{id}/engine-stats` or `/v1/engine-stats`.
- A direct runtime probe against the checked-in `route_request(...)` returned:
  - `404 not_found` for `GET /v1/markets/m1/engine-stats`
  - `404 not_found` for `GET /v1/engine-stats`
  - `404 not_found` for `POST /v1/markets/m1/engine-stats`

So this task is freezing a missing contract, not documenting an already-merged route.

### 2. Historical T571 implemented only a global route

The historical T571 server implementations existed, but they exposed only:

- `GET /v1/engine-stats`

not the market-scoped launch-gate path.

Evidence from git history:

- `f7d344d9fe` ("T571: Implement /engine-stats endpoint with clique/runtime diagnostics")
- `f2bffb11c7` ("T571: reduce engine-stats implementation to minimal clean server")

Both versions returned the same top-level payload sections:

- `engine`
- `cliques`
- `diagnostics`
- `meta`

and both mounted them on the global `/v1/engine-stats` path.

Repo-wide history search found no prior implementation of `/v1/markets/{id}/engine-stats`; that path appears only in the launch-gate contract doc.

### 3. Later history confirms the old route was process-global diagnostics, not a market read model

The later T567 work extended the same global route with `diagnostics.latency_tiers`.

That is important because it shows the old surface was drifting toward a host/process diagnostics endpoint, not a resource-shaped market subdocument. Fields such as:

- `uptime_seconds`
- `thread_pool_size`
- process-wide request counters
- global latency tier distributions

do not naturally compose with a market-scoped path.

This is the core reconciliation point: preserve the historical section names, but do not freeze host-global semantics onto a per-market route.

### 4. Current Bayes read-surface conventions already define the right error model

The restored backend already uses stable conventions on market/account read routes:

- unknown market on `GET /v1/markets/{id}` and `GET /v1/markets/{id}/events` -> `404 market_not_found`
- wrong method on an existing resource -> `405 method_not_allowed`
- successful read responses include top-level resource data plus `meta.timestamp`
- existing resource with empty state is still a `200` response

That last point matters. `GET /v1/markets/{id}/events` returns `200` even for a market with zero events. The engine-stats route should follow the same pattern for a market with zero compiled/runtime engine state.

### 5. Older Bayes compile-path experiments provide better market-local field names than T571's host-runtime fields

Earlier Bayes backend work on compiled representations used market-specific identifiers and metrics such as:

- `compile_id`
- `compile_type`
- `source_state_hash`
- `compile_time_ms`
- `memory_bytes`
- `created_at`
- `last_updated`

Those names map naturally to a market-scoped engine read model. They are better inputs for the frozen per-market contract than legacy host/runtime fields like `thread_pool_size` or `uptime_seconds`.

## Freeze Decision

### 1. Canonical route

Freeze the public contract as:

- `GET /v1/markets/{id}/engine-stats`

This route should be advertised from the service index under the market routes.

No query parameters are in scope for v1.

### 2. Success envelope

Preserve the historical T571 top-level section names and add one explicit market identifier:

```json
{
  "marketId": "m1",
  "engine": {},
  "cliques": {},
  "diagnostics": {},
  "meta": {
    "timestamp": "2026-04-05T00:00:00Z"
  }
}
```

Decision:

- keep `engine`, `cliques`, `diagnostics`, and `meta` at top level
- add top-level `marketId` so the market-scoped response is self-identifying
- do not wrap the payload in an extra `engineStats` object

### 3. `engine` fields

Freeze `engine` as market-specific engine identity, not a dump of process runtime inventory.

Required:

- `mode`
  - enum: `EXACT | APPROX`
- `backend`
  - string, for example `junction_tree`

Stable if available and therefore safe to freeze:

- `version`
- `precision`
- `compile_id`
- `compile_type`
- `source_state_hash`

Out of scope for the v1 contract:

- `thread_pool_size`
- process worker counts
- process uptime

Rationale:

- `mode` is already aligned with `engineMode` in the snapshot contract and with `approxFlag` usage elsewhere.
- `compile_*` and `source_state_hash` are market-local.
- `thread_pool_size` and uptime are properties of the host process, not of the market.

### 4. `cliques` fields

Freeze the `cliques` section in the historical T571 shape, but scope it to the compiled representation for the requested market.

Required:

- `num_cliques`
- `max_clique_size`
- `junction_tree_width`
- `cliques`

Each `cliques[]` item:

- `id`
- `nodes`
- `size`
- `states`

Do not add a required `separators` field in v1. The old T571 payload never exposed it, and the launch-gate requirement is satisfied by clique/runtime visibility rather than full structural dump parity.

### 5. `diagnostics` fields

Keep the historical subsection names, but make the semantics explicitly market-local.

Required:

- `request_count`
  - count of engine/inference requests attributable to this market
- `error_count`
  - count of engine failures attributable to this market
- `inference`
  - required object with:
    - `count`
    - `mean_ms`
    - `p50_ms`
    - `p95_ms`
    - `p99_ms`
- `cache`
  - required object with:
    - `hits`
    - `misses`
    - `hit_rate`

Safe optional additions if the implementation already has them:

- `compile_time_ms`
- `memory_bytes`
- `last_updated`

Not part of the required v1 contract:

- `uptime_seconds`
- global `latency_tiers`

Rationale:

- the inference/cache shapes are already present in historical T571 and remain useful
- compile time and memory are market-local if available
- uptime and global latency tiers are host/process diagnostics and should not be frozen into the public market route

### 6. Empty-state behavior

For an existing market with no compiled engine state or no observed inference traffic yet:

- return `200`
- keep `engine` as an object
- allow nullable `compile_id`, `compile_type`, and `source_state_hash`
- return:
  - `cliques.num_cliques = 0`
  - `cliques.max_clique_size = 0`
  - `cliques.junction_tree_width = 0`
  - `cliques.cliques = []`
- return zeroed diagnostics:
  - `request_count = 0`
  - `error_count = 0`
  - `inference.count = 0`
  - latency percentiles/means = `0`
  - `cache.hits = 0`
  - `cache.misses = 0`
  - `cache.hit_rate = 0.0`

This mirrors the existing `GET /v1/markets/{id}/events` contract, where "no data yet" is still a valid `200` read on a known market.

### 7. Error semantics

Freeze the error model as:

- unknown `market_id`
  - `404`
  - `error.code = "market_not_found"`
  - `error.details = {"market_id": "<id>"}`
- non-`GET` methods on `/v1/markets/{id}/engine-stats`
  - `405`
  - `error.code = "method_not_allowed"`
  - `error.details = {"method": "<METHOD>", "path": "/v1/markets/<id>/engine-stats"}`

Do not introduce a separate `not_compiled`, `engine_unavailable`, or `not_ready` failure for an existing market in v1. Existing market + empty engine state should be a zeroed `200`, not a domain error.

Because v1 defines no query parameters, there is no additional query-validation contract to freeze here.

### 8. `meta` fields

Freeze `meta` to the same minimal read-route convention used elsewhere:

- `meta.timestamp`

No additional `meta` keys are required for v1.

### 9. Legacy global alias decision

The historical `/v1/engine-stats` alias should not remain in the public contract.

Decision:

- do not advertise `/v1/engine-stats` from the service index
- do not require tests for `/v1/engine-stats`
- do not treat the alias as launch-gate evidence
- if an implementation temporarily keeps a compatibility handler during migration, treat it as undocumented compatibility only, not as a stable public API surface

Reasoning:

- the launch-gate contract is market-scoped
- the old alias never matched the launch-gate path
- the old alias accumulated host-global diagnostics semantics
- keeping it public would reintroduce ambiguity between per-market state and process-global diagnostics

## Consequence

The correct reconciliation is not "lift the old T571 route unchanged." The stable successor contract is:

- the market-scoped path from T539
- the historical top-level section names from T571
- the current Bayes `meta` and error conventions from the restored backend
- market-local semantics inside `engine`, `cliques`, and `diagnostics`

That preserves the useful parts of the old payload shape without carrying forward legacy process-global debug fields that do not belong on a per-market resource.

## Verification

Verification performed on this branch:

- source review of:
  - `apps/bayes-market/backend/server.py`
  - `apps/bayes-market/docs/t539-mvp-launch-gate.md`
  - historical T571 commits `f7d344d9fe` and `f2bffb11c7`
  - later T567 diagnostics extension history
- direct runtime probe of current `route_request(...)`:
  - `GET /v1/markets/m1/engine-stats` -> `404 not_found`
  - `GET /v1/engine-stats` -> `404 not_found`
- regression suite:

```bash
python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'
```

Result:

- `Ran 113 tests in 4.278s`
- `OK`
