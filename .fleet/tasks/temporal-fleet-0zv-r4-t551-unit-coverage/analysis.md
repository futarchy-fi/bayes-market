# T551 Unit Coverage Analysis

## Summary

This looks like a test-only task.

The production seam for `T551` is already in place in `backend/server.py`, and the current unit suite already covers most of the validator and normalization cases named in the task. The likely remaining work is to tighten symmetry in `tests/test_bayes_market_api.py`, not to change runtime behavior.

## Current Implementation Boundary

The relevant production path is already split the right way:

- `_validated_market_marginals(...)` enforces exact outcome-set coverage, finite numeric values, non-negative probabilities, and unit-sum totals.
- `validate_structure_preserving_edit(...)` validates a normalized payload against the selected base slice:
  - `target.outcomeId` must belong to the edited market
  - each `context` assignment must reference a known market variable and valid outcome
  - the chosen base marginals must be a valid distribution
  - the edit must still preview to a non-negative distribution
- `resolve_probability_edit_base_marginals(...)` selects either the unconditional market marginals or an existing contextual slice.
- `normalize_probability_edit_payload(...)` normalizes the payload, resolves the base slice, runs the structure-preserving validator, and only then previews the edit.

That means malformed conditional slices reused during normalization should fail through the same `_validated_market_marginals(...)` path as malformed unconditional market marginals.

## Existing Coverage

The current `tests/test_bayes_market_api.py` file already covers most of the requested surface:

- accepted direct validator cases for binary and three-outcome edits
- direct validator rejection for:
  - unknown target outcome
  - unknown context variable
  - malformed marginals with negative mass
  - missing outcome mass
  - extra outcome mass
  - non-unit totals
  - non-finite values
- normalization-time rejection when an existing conditional slice is reused and is:
  - negative / malformed
  - missing outcome mass
  - non-finite
- canonical conditional-slice lookup for reordered context assignments

The underlying implementation also already supports the missing permutations because unconditional and conditional slice validation both flow through `_validated_market_marginals(...)`.

## Likely Gaps Against The Task Wording

The current suite is close, but there are still a few coverage holes if we want exact parity with the task description:

1. There is no direct `validate_structure_preserving_edit(...)` test for a known `context.variableId` paired with an invalid `context.outcomeId`.
2. Conditional-slice reuse during `normalize_probability_edit_payload(...)` is only covered for negative/missing/non-finite slices.
3. There is no normalization-time regression that proves reused conditional slices also fail when they:
   - contain an extra outcome key
   - sum to something other than `1.0`

Those are the most plausible additions for this branch.

## Planned Test Changes

I would keep the work confined to `tests/test_bayes_market_api.py` and add:

1. A direct validator test for invalid `context.outcomeId` on a known referenced variable.
2. A normalization test where `CONDITIONAL_MARGINALS["m2"][context_key]` includes an extra outcome key and `normalize_probability_edit_payload(...)` returns `400 invalid_structure_preserving_edit`.
3. A normalization test where the reused conditional slice has a non-unit total and `normalize_probability_edit_payload(...)` returns `400 invalid_structure_preserving_edit`.
4. The same no-side-effects assertions already used in the current normalization tests (`ORDERS == {}` and `EVENTS == {}`).

## Expected Production Impact

I do not expect production code changes to be necessary.

The current implementation already routes both unconditional and reused conditional slices through `_validated_market_marginals(...)`, so these tests should pass once added. If any fail, that would indicate an unexpected gap in how the normalization path selects or validates reused conditional slices.

## Verification Baseline

Current branch state passes:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_formula_schema.py'`
