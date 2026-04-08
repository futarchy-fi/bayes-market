# T551 Core Structure-Preserving Validator Analysis

## Summary

The requested `T551` scope is already present in the current checkout.

`backend/server.py` contains a dedicated `validate_structure_preserving_edit(...)` function, it is called from normalized `ProbabilityEdit` payload handling before command/order mutation, and the existing tests cover the main acceptance and rejection paths described by this task.

So the practical conclusion for this branch is:

- the core validator logic is implemented
- the integration point into payload normalization is implemented
- direct and HTTP-surface regressions are implemented

This analysis therefore documents the current behavior and the plan I would preserve if follow-up adjustments are needed.

## Scope Fit Against The Task

The task asks for a validator that rejects malformed normalized edits with `400 invalid_structure_preserving_edit` when any of the following fail:

- target outcome membership
- normalized context references
- base-marginal completeness
- finite numeric values
- non-negative probabilities
- unit-sum mass
- safe renormalization for binary and multi-outcome edits

The current implementation matches that scope:

### 1. Target outcome membership

`validate_structure_preserving_edit(...)` rejects `target.outcomeId` values not present in the edited market's outcome set.

### 2. Normalized context references

The validator iterates the already-normalized `context` array and revalidates each assignment against the canonical market registry via `_resolve_market_outcome_reference(...)`, rejecting:

- unknown `context.variableId`
- `context.outcomeId` values not valid for the referenced market

### 3. Base-marginal completeness and numeric validity

`_validated_market_marginals(...)` enforces that the base slice:

- is a dictionary
- has exactly one value for each market outcome
- contains only finite numeric values
- contains no negative probabilities
- sums to `1.0` within tolerance

That helper is used by `validate_structure_preserving_edit(...)` for both unconditional market marginals and pre-existing conditional slices.

### 4. Safe renormalization

The validator checks that:

- when `target.probability < 1.0`, the non-target portion of the base slice still has positive mass
- the previewed updated distribution from `_preview_probability_target_distribution(...)` does not produce negative values

This covers both binary and multi-outcome edits because the preview helper rescales all non-target outcomes proportionally.

## Implementation Seam

The boundary frozen by `docs/t551-structure-preserving-validator-boundary-freeze.md` is respected by the current code:

1. `normalize_probability_edit_payload(...)` validates raw payload shape and normalizes the target/context.
2. `resolve_probability_edit_base_marginals(...)` selects the unconditional market slice or an existing contextual slice.
3. `validate_structure_preserving_edit(...)` validates the normalized edit against that selected base slice.
4. Only after that does `apply_probability_target(...)` run for generic probability-application checks and previewing.
5. Command materialization, market-active checks, solvency, order persistence, and event emission happen later in the route.

That means `invalid_structure_preserving_edit` remains a pre-mutation error family tied specifically to normalized structure-preservation failures.

## Evidence In Tests

The current suite already exercises the main T551 behaviors:

- direct validator acceptance for binary and three-outcome markets
- rejection of unknown target outcomes
- rejection of invalid context references
- rejection of malformed base marginals
  - negative values
  - missing outcomes
  - extra outcomes
  - non-unit totals
- rejection when an existing malformed conditional slice is reused during payload normalization
- HTTP surfacing of `400 invalid_structure_preserving_edit` with no orders/events written

Verification run on this branch:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'` -> `Ran 128 tests ... OK`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_formula_schema.py'` -> `Ran 7 tests ... OK`

## Residual Gaps / Risks

I did not find a meaningful implementation gap against the task description itself.

The only minor follow-up opportunity is test granularity: there is explicit code coverage for finite numeric validation and safe renormalization, but I did not see a direct regression test that injects a non-finite base marginal such as `nan` or `inf`. That is a coverage refinement, not a missing implementation seam.

## Plan

If this task had still required code work, the correct implementation order would be:

1. Keep `_validated_market_marginals(...)` as the single helper for exact outcome-set, finite-number, non-negative, and unit-sum validation.
2. Keep `validate_structure_preserving_edit(...)` focused on normalized semantic checks only:
   - target outcome membership
   - normalized context references
   - base-slice validation
   - renormalization safety
3. Keep base-slice selection outside the validator in `resolve_probability_edit_base_marginals(...)`.
4. Keep route wiring in `normalize_probability_edit_payload(...)` so all failures happen before command/order/event side effects.
5. If desired, add one narrow regression test for non-finite base marginals to harden the task's "finite numeric values" requirement.

## Conclusion

On this branch, `T551` core validator behavior is already implemented and aligned with the frozen boundary and the task description. The actionable result of this analysis is that no new production code appears necessary for the core-validator slice; only optional test tightening remains.
