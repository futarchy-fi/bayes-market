# t548-query-backend

## Goal

- Implement the first concrete `InferenceQueryBackend` on top of the new `CurrentModelCompileArtifact`.
- Support exact marginal lookup for the current compiled market model.
- Support atomic EventTrade price/probability lookup without reaching back into `backend/server.py`.
- Keep the existing `501 event_trade_inference_unavailable` boundary for broader CNF shapes intact.

## Current state

- `backend/inference/contracts.py` already defines:
  - `InferenceQueryBackend`
  - `MarginalQueryResult`
  - `AtomicEventQueryResult`
- `backend/inference/current_model.py` already defines:
  - `CurrentModelCompileArtifact`
  - deterministic compile helpers
  - `CompileResult.artifact` population through `compile_current_market_result(...)`
- The artifact already contains everything the current exact query path needs:
  - `market_id`
  - `variable_id`
  - `marginals`
  - `conditional_marginals`
  - `outcomes`
  - `exact_eligible`
  - `eligibility_reason`
- There is still no concrete query backend implementation.
- `backend/server.py` still performs query-like work directly from globals:
  - `resolve_probability_edit_base_marginals(...)` reads `MARKETS` and `CONDITIONAL_MARGINALS`
  - `create_event_trade_order(...)` prices directly from `MARKETS[market_id]["marginals"][outcome_id]`
- The current server compile snapshot path (`build_market_compile_result(...)`) still synthesizes a `CompileResult` without an attached artifact, which means the new query backend cannot be wired into the HTTP path yet without the later server-adapter task.

## Behavioral constraints from the live checkout

- The current model is still market-local and effectively independent at compile/query time.
  - Exact marginal lookup is just an artifact lookup.
  - Truthful structure remains one singleton clique with width `0`.
- Conditional edits are persisted as alternate marginal slices under canonical string keys such as:
  - `btc_etf_approval_week=yes`
  - `btc_etf_approval_week=yes|fed_rate_cut_mar_2026=no`
- Existing probability-edit read behavior is:
  - empty context -> use unconditional `market["marginals"]`
  - known context key -> use stored conditional slice
  - unknown context key -> fall back to unconditional `market["marginals"]`
- `normalize_context_assignments(...)` in `backend/server.py` sorts assignments by `variableId`, so any query-backend context encoding must sort mapping keys the same way.
- The EventTrade execution boundary is still owned by `backend/formula_schema.py` and `backend/server.py`.
  - `require_atomic_event_trade_formula(...)` rejects:
    - multi-clause CNF
    - multi-literal clauses
    - negated literals
  - Those failures must remain `501 event_trade_inference_unavailable`.
- The query backend should not absorb public-route responsibilities:
  - no market-id to variable-id translation
  - no CNF parsing or shape validation
  - no HTTP error mapping

## Main gap this task should close

The inference seam now has a real compiler and artifact, but no executable query backend.

That leaves three concrete problems:

1. `InferenceQueryBackend` is still only a protocol.
2. Later server rewiring would still have to read state from globals unless this task adds artifact-backed lookup logic first.
3. There is no internal validation layer for "this `CompileResult` actually carries a queryable current-model artifact."

## Scope interpretation

In scope:

- add a concrete current-model query backend
- make it consume `CompileResult.artifact`
- implement exact marginal lookup semantics for the current artifact
- implement atomic single-literal probability lookup for the compiled market variable
- add focused inference-module unit coverage

Out of scope:

- rewiring `backend/server.py` call sites to use the backend
- changing EventTrade formula normalization or widening the accepted formula subset
- adding generic multi-variable or multi-clause inference
- introducing cache invalidation / cache-hit accounting changes
- changing the `GET /v1/markets/{id}/engine-stats` payload

That wiring remains owned by `t548-server-adapter`.

## Recommended implementation shape

The cleanest implementation is to keep the query backend alongside the artifact in `backend/inference/current_model.py`.

Recommended additions there:

- `CurrentModelQueryBackend`
  - concrete implementation of `InferenceQueryBackend`
- `CURRENT_MODEL_QUERY_BACKEND`
  - module-level singleton, parallel to `CURRENT_MODEL_COMPILER`
- internal artifact validation helper, for example:
  - `_require_current_model_artifact(compile_result: CompileResult) -> CurrentModelCompileArtifact`
- internal context-key helper, for example:
  - `_context_mapping_key(context: Mapping[str, str] | None) -> str`

Then export the new backend from `backend/inference/__init__.py`.

This keeps the query logic:

- artifact-local
- server-independent
- colocated with the compile representation it understands

## Recommended query semantics

### 1. Artifact validation

Before any query executes, require that:

- `compile_result.artifact` is present
- it is a `CurrentModelCompileArtifact`
- `compile_result.compile_id == artifact.compile_id`
- `compile_result.source_state_hash == artifact.source_state_hash`
- `compile_result.compile_type == artifact.compile_type`
- `artifact.exact_eligible` is still true

If any of those fail, raise an internal inference exception, not an API error.

Recommended split:

- malformed/missing artifact wrapper -> `InferenceQueryError`
- unsupported artifact eligibility or unsupported query shape -> `InferenceUnsupportedQueryError`

This gives the later server-adapter task a clean internal failure surface.

### 2. Marginal lookup

`query_marginals(...)` should:

- treat `context=None` and `{}` as unconditional lookup
- canonicalize any provided context mapping by sorting variable ids and joining as:
  - `variableId=outcomeId|variableId=outcomeId`
- return:
  - `artifact.conditional_marginals[context_key]` when present
  - otherwise `artifact.marginals`

Important constraint:

- do not depend on `backend/server.py::context_state_key(...)`

The inference package should own its own deterministic encoder so it remains import-safe and cycle-free.

Also keep context validation intentionally narrow:

- require keys and values to be non-empty strings
- do not try to re-resolve referenced markets from global state

The artifact does not carry a full market registry, and that validation already belongs to the server normalization layer.

### 3. Atomic event lookup

`query_atomic_event(...)` should:

- only support the compiled artifact's own `variable_id`
- require `outcome_id` to exist in the compiled marginal slice
- return the exact probability from unconditional `artifact.marginals`

For the current model, this is enough to support EventTrade pricing parity because the live EventTrade path is still unconditional and market-local.

### 4. Negation and broader-shape handling

The safest interpretation for this slice is:

- reject `negated=True` inside the query backend with `InferenceUnsupportedQueryError`
- do not add any CNF evaluator here

Reason:

- the live public contract still treats negated literals and broader CNF shapes as outside the supported atomic execution subset
- allowing the query backend to silently handle them would create pressure to widen execution accidentally in the later server-adapter task

So the execution split stays:

- formula shape boundary -> `backend/formula_schema.py`
- atomic compiled lookup -> `CurrentModelQueryBackend`

## Recommended result metadata

Keep result payloads minimal and compatibility-friendly.

Reasonable defaults:

- `runtime_ms`
  - measured with a lightweight monotonic clock and rounded
- `cache_hit=False`
  - there is no separate query cache in this slice
- `compile_id=compile_result.compile_id`
- `metadata`
  - optional low-risk breadcrumbs such as:
    - `contextKey`
    - `resolutionSource` (`unconditional` or `conditional`)
    - `eligibilityReason`

The exact metadata contents are less important than not inventing a larger public contract around them.

## Unit coverage that should exist after implementation

Add focused tests to `tests/test_bayes_market_inference_module.py` for:

- `CurrentModelQueryBackend` returns unconditional marginals from the artifact
- conditional context lookup returns the stored slice
- context mapping order does not matter because keys are canonicalized
- missing conditional context falls back to unconditional marginals
- atomic event query returns the exact unconditional probability for the compiled variable
- querying a different variable id raises `InferenceUnsupportedQueryError`
- querying an unknown outcome id raises `InferenceQueryError`
- negated atomic query raises `InferenceUnsupportedQueryError`
- querying a `CompileResult` without a `CurrentModelCompileArtifact` raises `InferenceQueryError`
- querying a mismatched or ineligible artifact raises the expected internal inference error

These should stay module-level tests. API tests should not need to change in this task if the server remains unwired.

## Expected file impact

Primary files:

- `backend/inference/current_model.py`
- `backend/inference/__init__.py`
- `tests/test_bayes_market_inference_module.py`

Possible small contract/export touch:

- `backend/inference/contracts.py`

Only if a tiny helper or typing refinement is needed. The protocol already looks sufficient.

`backend/server.py` should remain mostly untouched here. If this task starts rewriting `create_event_trade_order(...)` or probability-edit reads directly, it is stealing scope from `t548-server-adapter`.

## Risks to watch

- If the backend depends on `MARKETS` or `CONDITIONAL_MARGINALS`, the inference seam is not real yet.
- If context encoding does not exactly match the current sorted `variableId` behavior, conditional marginal lookup will drift from existing probability-edit semantics.
- If the backend accepts market ids instead of internal variable ids, it will blur the boundary between the public EventTrade adapter and the internal inference seam.
- If negated or broader CNF support is added here, the later adapter work may widen the frozen EventTrade contract by accident.
- If artifact validation is omitted, later callers can pass synthetic `CompileResult` wrappers and get misleading query results.

## Concrete implementation plan

1. Add artifact-validation and context-key helpers in `backend/inference/current_model.py`.
2. Implement `CurrentModelQueryBackend.query_marginals(...)` using artifact-only lookup and fallback semantics.
3. Implement `CurrentModelQueryBackend.query_atomic_event(...)` for non-negated atomic lookup on the compiled variable.
4. Export the backend instance from `backend/inference/__init__.py`.
5. Add module-level tests for unconditional lookup, conditional lookup, fallback, and error cases.
6. Leave HTTP/server integration for `t548-server-adapter`.

## Verification

Baseline on the current branch before changes:

- `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
- result: `Ran 146 tests in 4.437s`
- status: `OK`

After implementation, rerun at least:

- `python3 -m unittest tests.test_bayes_market_inference_module`
- `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
