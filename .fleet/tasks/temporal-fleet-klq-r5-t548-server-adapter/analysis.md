# t548-server-adapter

## Goal

- Route the remaining server-side inference reads through the extracted T548 seam in `backend/inference`.
- Keep the frozen HTTP contracts unchanged for:
  - `GET /v1/markets/{id}/engine-stats`
  - `POST /v1/markets/{id}/orders/probability-edit`
  - `POST /v1/markets/{id}/orders/event-trade`
- Limit this task to server-side compile/query adaptation. Do not take ownership of soft-evidence mutation, cache invalidation, incremental compile hooks, or broader EventTrade execution.

## Current state

- The inference seam now exists:
  - `backend/inference/current_model.py` exports `CURRENT_MODEL_COMPILER` and `CURRENT_MODEL_QUERY_BACKEND`.
  - The current model compiler produces immutable `CompileResult` values with attached artifacts.
  - The query backend already supports:
    - exact marginal lookup
    - exact atomic EventTrade probability lookup
    - unconditional fallback when a conditional slice is missing
- `backend/server.py` still bypasses that seam in all of the places this task is supposed to cover:
  - engine-stats snapshot construction still uses the synthetic `build_market_compile_result(...)`
  - ProbabilityEdit base-slice reads still use `resolve_probability_edit_base_marginals(...)` against `MARKETS` and `CONDITIONAL_MARGINALS`
  - unconditional preview still reads `market["marginals"]` directly in `preview_unconditional_probability_edit(...)`
  - EventTrade unit pricing still reads `MARKETS[market_id]["marginals"][outcome_id]` directly in `create_event_trade_order(...)`
- The current engine-stats contract is intentionally snapshot-based, not eager:
  - untouched markets return zeroed diagnostics with `compile_id = null`
  - accepted ProbabilityEdit requests refresh compile metadata
  - accepted EventTrade requests only increment request telemetry and do not create a compile snapshot
- The current ProbabilityEdit write semantics are still server-owned:
  - unconditional edits mutate `MARKETS[market_id]["marginals"]`
  - conditional edits mutate `CONDITIONAL_MARGINALS[market_id][context_key]`
  - invariant/property tests compare those mutations against brute-force tiny-net references
- The current EventTrade boundary is also still server-owned:
  - `backend/formula_schema.py` plus server helpers freeze the public market-id adapter
  - broader CNF and negated literals still fail with `501 event_trade_inference_unavailable`

## Constraints and ownership boundaries

- Do not change any public payload shapes or route-local error codes that are already frozen by:
  - `docs/t571-per-market-engine-stats-contract-freeze.md`
  - `docs/t1737-probability-edit-http-contract-freeze.md`
  - `docs/t547-shared-event-formula-contract-freeze.md`
- Do not make `GET /v1/markets/{id}/engine-stats` compile on read. Existing tests freeze the zero-state response for a market with no refreshed snapshot.
- Do not move or reinterpret soft-evidence mutation logic. T549/T550/T551 still own:
  - how unconditional edits change marginals
  - how conditional slices are stored
  - structure-preserving validation
- Do not add new compile caching or invalidation policy. T553/T554 own cache invalidation and broader incremental compile behavior.
- Do not widen the EventTrade execution subset. Keep the route-local market-id adapter and the existing `501` boundary in place.
- Do not leak `InferenceCompileError`, `InferenceQueryError`, or `InferenceUnsupportedQueryError` directly into public HTTP error payloads.

## Main integration points

### 1. Engine-stats snapshot path

Current server behavior:

- `refresh_market_compile_snapshot(...)` populates `MARKET_ENGINE_STATS` from `build_market_compile_result(...)`
- `build_market_compile_result(...)` is still synthetic and does not use the compiled artifact seam
- `get_market_engine_stats(...)` only reads the stored snapshot plus telemetry counters

What should change:

- keep `MARKET_ENGINE_STATS` as the market-scoped public read model
- replace the synthetic compile builder with a helper that snapshots:
  - `deepcopy(MARKETS[market_id])`
  - `deepcopy(CONDITIONAL_MARGINALS.get(market_id, {}))`
  and delegates to `CURRENT_MODEL_COMPILER.compile_result(...)`
- keep snapshot timing unchanged:
  - accepted ProbabilityEdit refreshes compile metadata
  - EventTrade does not
  - untouched markets still report `compile_id = null` and `cliques = []`

Important non-goal:

- do not start persisting a generic compile cache or recompile-on-read policy here

### 2. ProbabilityEdit base-slice reads

Current server behavior:

- `resolve_probability_edit_base_marginals(...)` returns:
  - unconditional `market["marginals"]` for empty context
  - stored `CONDITIONAL_MARGINALS[market_id][context_key]` when present
  - unconditional `market["marginals"]` when the conditional slice is missing
- `normalize_probability_edit_payload(...)` relies on that helper to validate against the base slice
- `preview_unconditional_probability_edit(...)` reads `market["marginals"]` directly
- `create_probability_edit_order(...)` uses direct reads for both unconditional and contextual before-slices

What should change:

- rewrite the base-slice read helper to:
  - compile the current market snapshot through `CURRENT_MODEL_COMPILER`
  - convert normalized context arrays into the sorted `{variableId: outcomeId}` mapping expected by `CURRENT_MODEL_QUERY_BACKEND.query_marginals(...)`
  - return `MarginalQueryResult.marginals`
- reuse that query-backed helper everywhere the server needs the current or contextual base slice
- preserve the existing fallback semantics for missing conditional slices, because the current query backend already falls back to unconditional marginals when `context_key` is absent

Important non-goal:

- do not change how accepted edits write new marginals back into `MARKETS` or `CONDITIONAL_MARGINALS`

### 3. EventTrade pricing

Current server behavior:

- the route normalizes the public formula with market ids
- `require_atomic_event_trade_formula(...)` enforces the single-clause, single-literal, non-negated subset
- `create_event_trade_order(...)` prices the order directly from `MARKETS[market_id]["marginals"][outcome_id]`

What should change:

- keep the public formula adapter and `501 event_trade_inference_unavailable` behavior exactly where they are
- in `create_event_trade_order(...)`, translate the accepted target market to its internal `market["variableId"]`
- call `CURRENT_MODEL_QUERY_BACKEND.query_atomic_event(...)` against a compiler-backed snapshot instead of reading the marginal directly from server globals
- keep EventTrade itself read-only in this stub:
  - no market mutation
  - no account-risk mutation
  - no compile snapshot refresh

Important non-goal:

- do not let the query backend absorb market-id translation or CNF-shape ownership; that belongs to the route adapter already frozen in T547

## Recommended adapter shape

Keep the new logic in small server-local helpers instead of spreading compile/query calls through every route function.

Recommended helper set:

- `compile_market_for_inference(market_id: str, *, compile_time_ms: float = 0.0, last_updated: str | None = None) -> CompileResult`
  - deep-copy current market and conditional-slice state
  - delegate to `CURRENT_MODEL_COMPILER.compile_result(...)`
- `context_mapping_from_assignments(context: list[dict[str, str]]) -> dict[str, str]`
  - convert the normalized context array into the query backend mapping shape
- `query_market_marginals_for_inference(market_id: str, context: list[dict[str, str]]) -> dict[str, float]`
  - compile current state
  - query marginals through `CURRENT_MODEL_QUERY_BACKEND`
  - return only the marginals payload the existing server helpers need
- `query_market_atomic_probability_for_inference(market_id: str, outcome_id: str) -> float`
  - compile current state
  - call `query_atomic_event(...)` using the market's internal `variableId`
  - return the numeric probability for order pricing
- a small internal translator for unexpected inference failures
  - keep `Inference*` exceptions behind the HTTP boundary

This keeps the compile/query boundary explicit without moving soft-evidence ownership out of `backend/server.py`.

## Concrete implementation plan

1. Add server-local compiler/query adapter helpers that snapshot the current market state and call `CURRENT_MODEL_COMPILER` / `CURRENT_MODEL_QUERY_BACKEND`.
2. Replace the internals of `refresh_market_compile_snapshot(...)` so engine-stats metadata and cliques come from a real `CompileResult`, not from `build_market_compile_result(...)`.
3. Replace `resolve_probability_edit_base_marginals(...)` with an inference-backed read helper and route unconditional preview/base-slice reads through it.
4. Replace EventTrade unit pricing in `create_event_trade_order(...)` with `query_atomic_event(...)`, translating the route-local market id to the compiled variable id first.
5. Catch unexpected inference-layer exceptions at the server adapter seam so public HTTP contracts do not start exposing internal inference error codes.
6. Add or adjust parity coverage around:
  - zeroed engine-stats before any accepted ProbabilityEdit
  - compile snapshot population after accepted ProbabilityEdit
  - side-effect-free unconditional preview
  - ProbabilityEdit brute-force invariant parity after base-slice reads move behind the adapter
  - EventTrade atomic pricing parity through the query backend
7. Run the Bayes suite:
  - `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`

## Files most likely touched

- `backend/server.py`
- `tests/test_bayes_market_api.py`
- possibly `tests/test_bayes_market_inference_module.py` if small parity assertions are useful, but the main surface change should stay at the API/server layer

## Risks

- If engine-stats starts compiling on `GET`, the frozen zero-state contract will break.
- If the adapter changes write semantics instead of only read/query paths, it will steal scope from T549/T550/T551 and risk breaking the brute-force invariant suite.
- If EventTrade passes public market ids straight into `query_atomic_event(...)`, the route-local adapter boundary from T547 will blur.
- If internal inference exceptions leak out directly, the public API will grow unplanned error codes.
- If this task adds cache or invalidation policy beyond the existing snapshot refresh point, it will overlap with T553/T554.

## Baseline verification

Current baseline before implementation:

- command: `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
- result: `Ran 156 tests in 4.464s`
- status: `OK`
