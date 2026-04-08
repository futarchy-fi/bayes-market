# T549 Base Slice Analysis

## Summary

The requested `T549` base-slice seam is already present in the current checkout.

For empty-context `ProbabilityEdit` requests, the server now resolves the addressed market's unconditional marginal slice through the exact-inference adapter and feeds that slice into the normalized preview/application path instead of reading straight from `MARKETS[market_id]["marginals"]` at the call sites that matter.

## Current Implementation Evidence

### 1. Unconditional base marginals already come from the inference seam

- `backend/server.py::query_market_marginals_for_inference(...)` compiles the addressed market snapshot and queries `CURRENT_MODEL_QUERY_BACKEND.query_marginals(...)`.
- `backend/inference/current_model.py::CurrentModelQueryBackend.query_marginals(...)` returns `artifact.marginals` when no context is supplied, which is the current unconditional slice.
- `backend/server.py::resolve_probability_edit_base_marginals(...)` now delegates to that inference-backed helper.

That means the canonical read seam for the current market slice is already:

```text
market_id + normalized context
-> compile_market_for_inference(...)
-> CURRENT_MODEL_QUERY_BACKEND.query_marginals(...)
-> resolved base marginals
```

### 2. Normalized ProbabilityEdit validation already consumes that slice

`backend/server.py::normalize_probability_edit_payload(...)` currently:

1. normalizes `context`
2. normalizes `target.probability`
3. resolves `base_marginals = resolve_probability_edit_base_marginals(market_id, context)`
4. runs `validate_structure_preserving_edit(..., marginals=base_marginals)`
5. dry-runs `apply_probability_target(..., marginals=base_marginals)`

So the normalized payload path already validates and previews against the inference-backed slice.

### 3. The unconditional preview/application path already reuses that seam

`backend/server.py::preview_unconditional_probability_edit(...)`:

- rejects non-empty context
- reads `previous_marginals = resolve_probability_edit_base_marginals(market_id, [])`
- applies the normalized target against that resolved slice
- returns `previousMarginals`, `newMarginals`, `impactScore`, and `assetDelta`

`backend/server.py::create_probability_edit_order(...)` then reuses that unconditional preview for the accepted empty-context path. If no preview is supplied, it recomputes via `preview_unconditional_probability_edit(...)`, so the accepted unconditional market mutation still flows through the same inference-backed base-slice helper.

## What This Means For The Task

The production seam described by the task is already implemented:

- unconditional `ProbabilityEdit` base-slice reads go through the exact-inference adapter
- normalized validation uses the resolved slice
- unconditional preview uses the resolved slice
- accepted unconditional application reuses that preview and mutates only `MARKETS[market_id]["marginals"]`

So this task does not look blocked on a missing production code path. The remaining gap is mostly explicit regression coverage for the empty-context adapter route.

## Residual Risk

Two follow-on notes are worth keeping separate from the core `T549` seam:

- There is already a contextual adapter regression test, but I did not find a matching empty-context test that stubs `CURRENT_MODEL_QUERY_BACKEND` and proves unconditional preview/order reads come from the adapter.
- `compile_market_for_inference(...)` snapshots `conditional_marginals` too, so an unrelated malformed conditional slice can still poison an unconditional adapter read and surface `500 internal_error`. That is an adapter-hardening issue noted elsewhere in fleet metadata, not a reason to move this task back out of the inference seam.

## Plan

1. Treat the main task as already satisfied in production code.
2. If follow-up implementation is still expected on this branch, add a narrow empty-context regression that stubs `CURRENT_MODEL_QUERY_BACKEND.query_marginals(...)` and proves:
   - unconditional preview reads the adapter-backed slice
   - accepted empty-context orders record that same slice in `previousMarginals`
   - the backend uses empty-context query semantics rather than direct market-state reads
3. Keep the malformed-unrelated-conditional hardening as a separate adapter task so `T549` stays focused on the unconditional application seam.

## Verification

- `python3 -m unittest discover -s tests -p 'test_bayes_market_inference_module.py'` -> `Ran 21 tests` / `OK`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'` -> `Ran 142 tests` / `OK`
