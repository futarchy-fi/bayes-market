# t548-compile-artifact

## Goal

- Replace the synthetic compile snapshot in `backend/server.py` with a real immutable exact-engine artifact for the current repo model.
- Make that artifact deterministic from explicit source-state inputs and consistent with the current replay-hash contract.
- Freeze truthful structure metadata for the current independent-market baseline so later query and server tasks stop inferring fake cross-market junction-tree structure.

## Current state

- `backend/inference/contracts.py` defines immutable summary/result types, but there is still no concrete compiler or compiled artifact type.
- `backend/server.py` still synthesizes `CompileResult` directly in `build_market_compile_result(...)`.
- The current compile path derives `compile_id`, clique summaries, `memory_bytes`, and `last_updated` from live globals, not from a reusable artifact object.
- `market_replay_state_hash(...)` already computes a deterministic hash from:
  - `MARKETS[market_id]`
  - `CONDITIONAL_MARGINALS.get(market_id, {})`
- Those hash inputs are not preserved anywhere on the compiled result, so the compile output is not self-describing.
- `build_market_cliques(...)` currently turns every conditional-slice context key into a larger clique. That is convenient for engine-stats, but it is not truthful for the current model.

## What the current model actually is

- The live inference baseline on this branch is still an independent-product model over markets.
- Unconditional state lives in `MARKETS[market_id]["marginals"]`.
- Conditional edits only persist alternate marginal slices under `CONDITIONAL_MARGINALS[market_id][context_key]`.
- Those stored conditional slices do not establish a compiled multi-variable factor graph. They are per-context overrides, not proof that the engine owns pairwise or higher-order clique factors.

That matters for this task because the compile artifact needs to tell the truth about the model it compiled. On the current branch, the truthful bounded-treewidth structure for a market-local exact artifact is:

- one singleton clique for the market variable
- no separators
- `junction_tree_width = 0`
- exact eligibility is always true for the current independent-market baseline

## Main gap this task needs to close

The repo now has a generic `CompileResult`, but not the thing that result is supposed to summarize.

Today the server computes:

- `source_state_hash`
- `compile_id`
- `cliques`
- `memory_bytes`

without ever materializing an immutable artifact that a query backend can later consume.

That leaves three problems:

1. `t548-query-backend` has nothing concrete to query except server globals.
2. The current clique summaries overstate structure whenever conditional slices exist.
3. The compiled output does not retain the exact source-state snapshot that produced its hash.

## Recommended interpretation of scope

This task should implement the current-model compiler and artifact, but it should not take ownership of later tasks.

In scope:

- add a concrete compiler for the current independent-market model
- add an immutable compiled artifact type that retains the source-state snapshot used for hashing
- derive truthful clique and treewidth metadata from that artifact
- expose exact-eligibility fields needed by later query/server tasks
- add direct unit coverage for compile determinism and artifact truthfulness

Out of scope:

- rewiring the HTTP handlers to consume the new compiler everywhere
- implementing marginal or atomic-event query execution on top of the artifact
- widening the public EventTrade execution subset
- cache invalidation, incremental propagation, or approximate fallback behavior

Those remain owned by `t548-query-backend`, `t548-server-adapter`, `t553`, `t554`, and `t555`.

## Recommended artifact shape

The artifact needs to be richer than the current `CompileResult`, because later exact queries must be able to execute without reaching back into `backend/server.py`.

Recommended internal artifact contents:

- `market_id`
- `variable_id`
- `outcomes`
- `marginals`
- `conditional_marginals`
- `source_state_inputs`
- `source_state_hash`
- `cliques`
- `junction_tree_width`
- `exact_eligible`
- `eligibility_reason` or similarly explicit eligibility metadata

Important details:

- `source_state_inputs` should match the current hashed payload shape exactly:
  - `{"market": ..., "conditionalMarginals": ...}`
- `source_state_hash` should be computed from that exact snapshot under the same canonical JSON hashing profile already used by `market_replay_state_hash(...)`.
- `conditional_marginals` should be frozen into deterministic key order so artifact equality and hash-derived behavior stay stable.
- `cliques` should be truthful singleton summaries for the market variable even when conditional slices exist.

## Where to put it

The cleanest shape is a new inference implementation module, for example:

- `backend/inference/current_model.py`

with:

- a frozen artifact dataclass for the current model
- a pure compiler/helper that accepts market snapshots and conditional-slice snapshots
- summary helpers that produce the existing `CompileResult` fields from the artifact

That keeps the new compile logic out of `backend/server.py` and leaves the later server-adapter task with a narrow integration surface.

## Contract pressure on the existing inference types

The current `InferenceCompiler` protocol only takes `market_id` and `source_state_hash`.

That is not enough information to build a truthful artifact unless the compiler closes over server globals, which would defeat the point of this task.

The safer direction is:

- introduce a concrete pure compiler for this task that accepts explicit source snapshots
- keep protocol changes minimal unless they are required for the later server adapter
- avoid making the new compiler depend directly on `MARKETS` or `CONDITIONAL_MARGINALS`

If `CompileResult` needs to remain the protocol return type, it should either:

- gain an `artifact` field, or
- be paired with a concrete current-model artifact object that the query backend can hold alongside the summary

The important requirement is that `t548-query-backend` receives a real compiled object, not another server-side recomputation helper.

## Truthful structure decision

The biggest design choice in this task is whether to keep the current context-derived clique expansion.

It should not.

Reasons:

- `CONDITIONAL_MARGINALS` stores alternate marginal slices keyed by context. It does not store separator potentials, pairwise factors, or a compiled elimination order.
- Reporting cross-market cliques from those keys would make `GET /engine-stats` look more sophisticated than the engine really is.
- The task description explicitly asks for truthful clique summaries and metadata for the current independent-market model.

So the compile artifact should encode:

- `num_cliques = 1`
- `max_clique_size = 1`
- `junction_tree_width = 0`
- clique `states = len(outcomes)`

for each compiled market artifact.

## Determinism and ID strategy

To minimize downstream churn, keep the current compile identity story unless the implementation proves it insufficient:

- `source_state_hash` stays derived from the canonical source snapshot
- `compile_id` can continue using the current `comp-{digest[:12]}` scheme
- `compile_type` stays `ENGINE_CONFIG.compile_type`

That preserves compatibility with the frozen engine-stats expectations while replacing only the internals behind those fields.

## Expected implementation steps

1. Add the current-model artifact and compiler implementation under `backend/inference`.
2. Freeze the source-state snapshot shape and canonical hash computation used by that compiler.
3. Derive truthful singleton clique summaries and width metadata from the compiled artifact.
4. Add exact-eligibility fields for the independent-market baseline.
5. Either extend `CompileResult` or pair it with the concrete artifact so later tasks can query the compiled state directly.
6. Add focused unit tests for compile determinism, truthfulness, and immutability.
7. Leave HTTP rewiring to the later server-adapter task.

## Tests that should exist after implementation

- compiler returns an immutable artifact with frozen nested state
- `source_state_hash` matches the canonical hash of `source_state_inputs`
- compile output is deterministic for repeated compiles of the same snapshot
- compile output changes when either market marginals or conditional slices change
- markets with stored conditional slices still compile to singleton cliques and width `0`
- exact-eligibility fields report the current independent-market baseline truthfully
- malformed market snapshots raise `InferenceCompileError`

## File-level impact

Most likely touched files:

- `backend/inference/contracts.py`
- `backend/inference/__init__.py`
- `backend/inference/current_model.py`
- `tests/test_bayes_market_inference_module.py`

`backend/server.py` should stay mostly untouched in this task unless a minimal shim is needed for compile helper importability. The real server rewiring belongs to `t548-server-adapter`.

## Risks

- If this task keeps the existing context-derived clique synthesis, the artifact will remain structurally misleading and later engine-stats wiring will freeze the wrong semantics.
- If the compiler reads server globals directly, `t548-query-backend` will still be coupled to `backend/server.py`.
- If the artifact does not retain the exact hashed source snapshot, later determinism/debugging work will have to reconstruct provenance indirectly.
- If this task also rewires route handlers now, it will blur task ownership and make it harder to isolate regressions.

## Recommended verification

- `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
- Add targeted compile-artifact tests in `tests/test_bayes_market_inference_module.py` for:
  - deterministic hashing
  - immutable artifact shape
  - truthful singleton clique metadata
  - eligibility fields
