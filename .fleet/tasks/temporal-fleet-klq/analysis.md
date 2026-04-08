# bayes-T548-implement-inference-engine

## Current state

- The backend has no standalone inference module. All inference-like behavior lives inside `backend/server.py`.
- Exact-engine identity exists only as constants and diagnostics (`ENGINE_MODE`, `ENGINE_BACKEND`, `ENGINE_COMPILE_TYPE`, `MARKET_ENGINE_STATS`), not as a reusable compiler/query service.
- Probability edits mutate either `MARKETS[market_id]["marginals"]` or `CONDITIONAL_MARGINALS[market_id][context_key]` via `_preview_probability_target_distribution(...)`, `apply_probability_target(...)`, `resolve_probability_edit_base_marginals(...)`, and `preview_unconditional_probability_edit(...)`.
- Event trades still use the atomic subset only. `require_atomic_event_trade_formula(...)` raises `501 event_trade_inference_unavailable` for any multi-literal, multi-clause, or negated CNF, and `create_event_trade_order(...)` prices the trade from the current market marginal instead of asking an inference service.
- `refresh_market_compile_snapshot(...)` and `build_market_cliques(...)` synthesize compile metadata from current state hashes and context keys. There is no compiled factor graph, clique potential, separator state, or exact query object in memory.

## What the tests and docs freeze

- `tests/test_bayes_market_api.py` already treats the current probability-edit path as exact for the current toy net. `BayesMarketApiInferenceInvariantTests` compare accepted edits against a brute-force reference joint distribution and currently pass.
- That reference builds the joint distribution as the product of per-market marginals. On this branch, the live "network" is still an independent-product model plus stored conditional slices, not a general CPT-backed Bayes net.
- `docs/t537-epic-execution-baseline.md` and `docs/t538-scope-matrix.md` keep the task split explicit:
  - T548 = exact inference module skeleton
  - T549/T550 = soft-evidence application paths
  - T551 = structure-preserving validator
  - T553/T554 = cache invalidation and incremental compile hooks
  - T555 = approximate fallback
- `docs/t547-shared-event-formula-contract-freeze.md` freezes richer CNF as schema-valid but execution-unavailable. T548 can create the internal query seam that later removes that `501`, but it should not silently widen the public execution subset on its own.
- `docs/t571-per-market-engine-stats-contract-freeze.md` freezes the market-scoped engine-stats response shape. T548 must preserve `engine`, `cliques`, and `diagnostics` while making those fields come from a real engine artifact instead of synthetic bookkeeping.

## Task interpretation on this branch

T548 should not try to jump directly to a full generic junction-tree implementation across arbitrary Bayes nets. This checkout does not yet contain a BN structure contract, CPT storage layer, or compile service interface beyond the current stub state. Inventing those wholesale inside T548 would blur the responsibility boundaries with adjacent tasks and force new contracts that are not present in this repo.

The right implementation target is a real exact-engine skeleton:

- extract a dedicated inference package/service boundary out of `backend/server.py`
- define compile artifacts and query interfaces that future tasks can build on
- compile the current independent-market model into truthful exact-engine metadata
- expose exact query hooks for marginal lookup and atomic formula pricing
- keep the current public API behavior and brute-force parity intact
- leave soft-evidence mutation algorithms, cache invalidation, incremental compile propagation, and approximate fallback to their own tasks

## Risks and sequencing constraints

- If T548 only renames current helpers without creating a compile/query boundary, T549/T550/T553/T554 remain blocked on the same monolithic server file.
- If T548 tries to solve general BN authoring now, it will have to invent missing schema/CPT contracts that are not present in this repo.
- Engine-stats cannot stay purely synthetic after T548. The compile id, cliques, width, and source hash need to come from the new engine artifact so the route remains a truthful observability surface.
- Probability-edit invariant tests are the compatibility floor. The new engine boundary must preserve current brute-force parity before any richer graph semantics are attempted.

## Recommended child DAG

1. Freeze the exact-engine boundary for the current repo state.
   - State explicitly that T548 owns extraction of the exact engine module and current-model compile/query interfaces, while T549/T550/T551/T553/T554/T555 retain their later responsibilities.

2. Extract an inference package and typed interfaces.
   - Move engine config, compile/query result types, and engine-specific exceptions out of `backend/server.py`.
   - Give the server a narrow adapter boundary instead of direct helper ownership.

3. Implement a real compile artifact for the current model.
   - Compile current market state into an immutable exact-engine artifact with source-state hash inputs, clique summaries, width metadata, and bounded-treewidth eligibility data.
   - On this branch the truthful baseline artifact is an independent-product model, which implies singleton cliques and width `0`.

4. Add exact query hooks on top of that artifact.
   - Support marginal lookup for the current market model and atomic EventTrade price queries.
   - Preserve the current `event_trade_inference_unavailable` boundary for broader CNF shapes that remain outside the skeleton.

5. Rewire the server to consume the engine boundary.
   - Engine-stats should read from the compiled artifact.
   - Probability-edit preview/base-slice reads and EventTrade pricing should go through the engine adapter where possible without stealing T549/T550 ownership.

6. Lock the skeleton down with verification.
   - Add engine-focused unit tests plus contract/invariant coverage proving parity with the existing brute-force tiny-net fixtures and current engine-stats response.

## Baseline verification

- `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
- Result on this branch: `Ran 135 tests in 4.450s` and `OK`
