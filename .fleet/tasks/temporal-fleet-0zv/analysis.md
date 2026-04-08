# bayes-T551-implement-edit-validator

## Assessment

`T551` is effectively implemented in the current checkout even though the umbrella tracker still lists it as pending in `docs/t537-epic-execution-baseline.md`.

The concrete implementation lives in `backend/server.py`:

- `validate_structure_preserving_edit(...)` is the core validator.
- `resolve_probability_edit_base_marginals(...)` chooses the unconditional market marginals or an existing conditional slice.
- `normalize_probability_edit_payload(...)` runs the validator before command materialization or any state mutation.

The test suite already exercises this seam directly and through the public HTTP route.

## Task Boundary

For this repository, `T551` is the structure-preserving gate for normalized `ProbabilityEdit` payloads.

It owns:

- validating that `target.outcomeId` exists on the edited market
- validating that each normalized `context` assignment references a known market variable/outcome
- validating the base marginals used for the edit
  - exactly one probability for each market outcome
  - finite numeric values
  - non-negative values
  - unit-sum distribution
- validating that the requested target probability can be applied without producing a negative renormalized distribution

It does not own:

- raw request-shape and primitive-field validation such as missing `accountId`, wrong `target.kind`, or non-numeric `target.probability`
- idempotency replay/conflict handling
- command/event materialization
- active-market gating
- solvency / min-asset rejection logic from `T557` and `T558`

That boundary is visible in the current route order:

1. `handle_probability_edit(...)` validates top-level request metadata.
2. `normalize_probability_edit_payload(...)` performs payload normalization plus `T551` structure-preserving validation.
3. Only after that does the route materialize a canonical command, apply active-market / solvency gates, and create an order.

So `T551` failures are plain `400 invalid_structure_preserving_edit` API errors, not terminal rejection events.

## Evidence In Code

### 1. Core validator

`backend/server.py` defines `validate_structure_preserving_edit(...)` at lines 902-976.

That function:

- rejects unknown target outcomes with `invalid_structure_preserving_edit`
- rejects unknown or invalid normalized context assignments with `invalid_structure_preserving_edit`
- runs `_validated_market_marginals(...)` against the supplied marginals or the market's current marginals
- checks that non-target mass remains renormalizable
- previews the updated distribution and rejects negative outputs

This is the exact structure-preserving seam described by the task title.

### 2. Conditional-slice integration

`resolve_probability_edit_base_marginals(...)` at lines 1197-1207 selects the correct base distribution:

- empty `context` -> current market marginals
- non-empty `context` -> existing `CONDITIONAL_MARGINALS[market_id][context_key]` when present, otherwise fallback to current market marginals

`normalize_probability_edit_payload(...)` at lines 1377-1433 wires that base slice into `validate_structure_preserving_edit(...)` before any command/order mutation.

This is important because `T551` is not only about unconditional edits. It also protects previously stored conditional slices from being edited when that slice is already malformed.

### 3. No mutation before validation

`handle_probability_edit(...)` calls `normalize_probability_edit_payload(...)` before:

- idempotency replay binding
- `materialize_probability_edit_command(...)`
- `create_probability_edit_order(...)`
- event emission

That means a `T551` failure exits before command/order/event creation. This matches the current tests that assert empty `ORDERS` and `EVENTS` after validator failures.

## Evidence In Tests

The current test suite already maps cleanly onto the task decomposition:

- direct validator acceptance/rejection coverage in `tests/test_bayes_market_api.py:842-973`
- conditional-slice validation coverage in `tests/test_bayes_market_api.py:975-1022`
- HTTP-surface regression coverage in `tests/test_bayes_market_api.py:3500-3540`
- end-to-end brute-force invariant coverage for accepted edits in `tests/test_bayes_market_api.py:2376-2444`

Those tests prove both sides of the seam:

- valid edits are still accepted and produce the expected renormalized marginals
- structurally invalid base distributions are rejected before any write-side effects

## Verification

I ran:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_formula_schema.py'`

Results:

- `tests/test_bayes_market_api.py`: 128 tests, all passing
- `tests/test_bayes_market_formula_schema.py`: 7 tests, all passing

## Decomposition Rationale

Because the code is already present on this branch, the DAG should be read as the natural implementation slices of `T551`, not as proof that all child nodes remain unstarted.

The key slices are:

1. freeze the validator boundary and error taxonomy
2. implement the core structure-preserving checks
3. wire those checks to both unconditional and conditional base slices before mutation
4. cover direct validator behavior, HTTP surfacing, and acceptance invariants with tests
