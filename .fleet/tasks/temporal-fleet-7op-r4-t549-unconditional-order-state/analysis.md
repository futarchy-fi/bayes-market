# T549 Unconditional Order State Analysis

## Summary

The requested behavior is already implemented in the current checkout.

Accepted `ProbabilityEdit` orders already persist:

- `previousMarginals`
- `newMarginals`
- `impactScore`

And the only path that mutates `MARKETS[marketId]["marginals"]` is the accepted empty-context path.

So this task looks less like missing production logic and more like a request to pin the seam explicitly and, if needed, tighten regression coverage around the stored order state.

## Current Implementation Evidence

### 1. The unconditional preview already materializes the full transition

`backend/server.py::preview_unconditional_probability_edit(...)` already does the unconditional work for `context == []`:

- resolves `previousMarginals` from `resolve_probability_edit_base_marginals(market_id, [])`
- computes `newMarginals` with `apply_probability_target(...)`
- computes `impactScore` with `kl_divergence(previous_marginals, updated_marginals)`
- returns that transition together with the min-asset preview

This helper is the canonical empty-context transition builder.

### 2. The acceptance route only uses that preview on the empty-context path

`backend/server.py::handle_probability_edit(...)` only calls `preview_unconditional_probability_edit(...)` when `normalized_payload["context"]` is empty.

That same branch also owns the unconditional solvency gate:

- preview unconditional transition
- reject on `min_asset_violation` if `afterMinAsset < 0`
- otherwise proceed to order creation

For non-empty context, the route skips that preview/gate entirely and goes straight to order creation.

### 3. Order persistence already includes the accepted edit state

`backend/server.py::create_probability_edit_order(...)` already writes the accepted edit transition into the order object before persisting it into `ORDERS`:

- `order["previousMarginals"]`
- `order["newMarginals"]`
- `order["impactScore"]`

On the empty-context path it reuses the supplied unconditional preview:

- `previousMarginals = deepcopy(preview["previousMarginals"])`
- `updated_marginals = deepcopy(preview["newMarginals"])`
- `impactScore = round_risk_value(float(preview["impactScore"]))`

Then it persists the order with `ORDERS[order["id"]] = deepcopy(order)`.

That means the accepted unconditional edit state is already materialized both in the response order and in the in-memory order store.

### 4. `MARKETS[marketId]["marginals"]` is only mutated on accepted empty-context edits

The branch split inside `create_probability_edit_order(...)` is already the desired ownership seam:

- if `context` is non-empty:
  - resolve/apply against the contextual slice
  - write `CONDITIONAL_MARGINALS[market_id][context_key]`
  - leave `MARKETS[market_id]["marginals"]` unchanged
- if `context` is empty:
  - reuse the unconditional preview
  - write `MARKETS[market_id]["marginals"] = deepcopy(updated_marginals)`

That matches the task statement exactly.

## Test Coverage Status

The existing tests already pin most of the behavior:

- accepted unconditional orders expose `previousMarginals`, `newMarginals`, and `impactScore`
- unconditional preview and accepted order reuse the same transition
- contextual edits update `CONDITIONAL_MARGINALS` while keeping `MARKETS[market_id]["marginals"]` unchanged
- unconditional edits update `MARKETS[market_id]["marginals"]`

What I did not find is a direct assertion that the persisted `ORDERS[order_id]` entry itself carries the same `previousMarginals`, `newMarginals`, and `impactScore` as the acceptance response for the unconditional path.

That is the narrowest remaining regression-hardening opportunity.

## Plan

1. Treat the core production behavior as already satisfied.
2. If follow-up implementation is still required on this branch, keep it narrow and test-focused:
   - add a direct assertion that `server.ORDERS[payload["order"]["id"]]` matches the accepted unconditional order's `previousMarginals`, `newMarginals`, and `impactScore`
   - keep the contextual-path assertion that `MARKETS[market_id]["marginals"]` does not move when `context` is non-empty
   - keep the unconditional-path assertion that `MARKETS[market_id]["marginals"]` does move to `order["newMarginals"]`
3. Avoid broad refactors in `handle_probability_edit(...)` or `create_probability_edit_order(...)`, because the current split already cleanly matches the T549/T550/T557 boundaries.

## Verification

- `python3 -m unittest discover -s tests -p 'test_bayes_market_lmsr.py'` -> `Ran 11 tests` / `OK`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'` -> `Ran 145 tests` / `OK`
