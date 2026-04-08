# T551 Base Slice Integration Analysis

## Summary

The requested `T551` base-slice integration is already present in the current checkout.

`backend/server.py` already does the full sequence described by this task:

1. normalize the `ProbabilityEdit` payload into a canonical shape
2. resolve the base marginals from either current market state or an existing conditional slice
3. run `validate_structure_preserving_edit(...)` against that resolved base slice
4. do all command, order, event, and risk side effects only after normalization succeeds

So the main outcome of this branch analysis is:

- the production seam described by the task is implemented
- the context key used for conditional lookup is derived from normalized context assignments
- the validator is invoked early enough to prevent pre-validation side effects

No production gap is obvious from the checked-in code. The remaining work, if any, is limited to optional hardening around future callers and test granularity.

## Scope Fit Against The Task

The task asks for this behavior:

- resolve the correct base marginals from current market state or an existing `CONDITIONAL_MARGINALS` slice
- do that resolution via normalized context keys
- invoke the structure-preserving validator from `ProbabilityEdit` payload normalization
- ensure this happens before command, order, or event side effects

The current code matches that shape.

### 1. Base slice selection already exists

`resolve_probability_edit_base_marginals(market_id, context)` implements the slice selection boundary:

- if `context == []`, it returns a deep copy of `MARKETS[market_id]["marginals"]`
- otherwise it computes `context_key = context_state_key(context)`
- it then reads `CONDITIONAL_MARGINALS[market_id][context_key]` when present
- if no conditional slice exists for that key, it falls back to the market marginals

That is exactly the unconditional/conditional split this task describes.

### 2. The conditional lookup key is based on normalized context

`normalize_probability_edit_payload(...)` calls:

- `normalize_context_assignments(...)`

That helper:

- trims `variableId` and `outcomeId`
- rejects malformed entries
- rejects self-reference
- deduplicates by `variableId`
- rejects conflicting duplicate assignments
- returns assignments sorted by `variableId`

After that, `normalize_probability_edit_payload(...)` passes the normalized `context` list into `resolve_probability_edit_base_marginals(...)`.

That means the lookup key is built from canonicalized assignments, not raw request order.

The same normalized payload is later persisted and reused by `create_probability_edit_order(...)`, so the write-side key generation for `CONDITIONAL_MARGINALS` is aligned with the read-side key generation.

### 3. The validator is already wired into payload normalization

`normalize_probability_edit_payload(...)` currently performs this order:

1. payload object validation
2. `variableId` contract check
3. `target` shape validation
4. context normalization
5. probability normalization
6. base-marginal resolution
7. `validate_structure_preserving_edit(market, normalized_payload, marginals=base_marginals)`
8. `apply_probability_target(...)`

This is the exact integration seam described by the task title and description.

### 4. Side effects still happen after normalization

`handle_probability_edit(...)` calls `normalize_probability_edit_payload(...)` before:

- idempotency replay/conflict handling
- command materialization
- active-market rejection
- unconditional solvency preview/rejection
- order creation
- account-risk updates
- terminal event emission

So any `invalid_structure_preserving_edit` failure triggered by the resolved base slice occurs before command/order/event side effects, which is the key boundary this task wants.

## Evidence In The Current Tests

The current suite already covers the relevant integration behavior.

Direct normalization coverage:

- malformed unconditional market marginals are rejected by the structure-preserving validator
- an existing malformed conditional slice is reused during normalization and rejected
- missing outcome mass in a conditional slice is rejected
- non-finite values in a conditional slice are rejected

HTTP coverage:

- malformed unconditional marginals surface as `400 invalid_structure_preserving_edit`
- malformed existing conditional slices surface as `400 invalid_structure_preserving_edit`
- these failures leave `ORDERS` and `EVENTS` untouched

This makes the base-slice integration seam both implemented and regression-covered.

## Residual Risk

I do not see a missing production feature relative to the task description.

The one small design caveat is that `context_state_key(...)` itself is a pure serializer, not a normalizer. The current production path is safe because all internal read/write call sites feed it normalized context arrays. If a future caller ever passes unsorted raw context directly into `context_state_key(...)`, conditional-slice lookup could miss an existing slice written under canonical ordering.

That is not a current bug in the checked-in `ProbabilityEdit` pipeline, but it is the only realistic hardening opportunity I found around this seam.

## Plan

My implementation plan for this task would be:

1. Keep `normalize_probability_edit_payload(...)` as the single place where normalized context is produced before base-slice selection.
2. Keep `resolve_probability_edit_base_marginals(...)` as the selector for unconditional marginals vs. existing `CONDITIONAL_MARGINALS` slices with fallback to market marginals.
3. Keep `validate_structure_preserving_edit(...)` invoked immediately after base-slice resolution and before any command/order/event/risk work.
4. Preserve the current read/write alignment where conditional slices are keyed from the normalized payload context.
5. Optionally harden `context_state_key(...)` or add a narrow regression test proving order-insensitive lookup if future changes introduce new direct callers.

Given the current branch state, steps 1 through 4 are already satisfied in production code. Only step 5 is optional hardening, not required task completion.

## Verification

Verified on this branch with:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'` -> `Ran 130 tests ... OK`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_formula_schema.py'` -> `Ran 7 tests ... OK`

## Conclusion

The requested base-slice integration for `T551` is already implemented on this branch. The analysis outcome is therefore not a code-change plan for a missing seam, but confirmation that the existing `ProbabilityEdit` normalization path already resolves unconditional vs. conditional base slices through normalized context, invokes the validator before side effects, and is covered by direct and HTTP-level tests.
