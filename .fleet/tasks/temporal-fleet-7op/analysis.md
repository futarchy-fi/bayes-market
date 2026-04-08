# bayes-T549-implement-soft-evidence

## Scope Decision

T549 is the empty-context ProbabilityEdit application path:

- resolve the unconditional base marginal slice for the addressed market
- apply deterministic soft-evidence rescaling to the requested outcome
- persist the accepted unconditional result into market/order state
- surface the resulting `previousMarginals`, `newMarginals`, and `impactScore` through the existing audit trail

Adjacent work is already split elsewhere in this checkout:

- `T548`: inference module seam and compile/query contracts
- `T550`: contextual/conditional soft-evidence path and `CONDITIONAL_MARGINALS` ownership
- `T551`: pure structure-preserving validation over normalized payload + selected base slice
- `T557`: unconditional min-asset rejection contract
- `T544` / `T1737`: canonical command/event and HTTP route envelopes

## Current Implementation Evidence

The checked-in code already contains the logical T549 slice.

### Inference-backed base marginals

- `backend/inference/current_model.py` compiles the current market snapshot plus any stored conditional slices into a singleton exact artifact.
- `CURRENT_MODEL_QUERY_BACKEND.query_marginals(...)` returns unconditional marginals when `context` is empty.
- `backend/server.py::resolve_probability_edit_base_marginals(...)` routes unconditional edits through that inference adapter.

### Soft-evidence math

- `backend/lmsr.py::rescale_probability_edit(...)` performs the actual probability-edit rescaling.
- `backend/server.py::_preview_probability_target_distribution(...)` and `apply_probability_target(...)` wrap that helper in route-facing validation/error semantics.
- The unconditional path computes `impactScore` as `kl_divergence(previousMarginals, newMarginals)`.

### Empty-context mutation path

`backend/server.py::handle_probability_edit(...)` currently drives unconditional requests through:

1. `normalize_probability_edit_payload(...)`
2. `resolve_probability_edit_base_marginals(market_id, [])`
3. `validate_structure_preserving_edit(...)`
4. `materialize_probability_edit_command(...)`
5. `preview_unconditional_probability_edit(...)`
6. `create_probability_edit_order(...)`
7. `sync_account_risk_state(order)`
8. `build_terminal_acceptance_response(...)`

For empty context specifically:

- `preview_unconditional_probability_edit(...)` snapshots `previousMarginals`, computes `newMarginals`, and prepares the provisional asset delta.
- `create_probability_edit_order(...)` mutates `MARKETS[market_id]["marginals"]`.
- Non-empty context takes a different branch and writes to `CONDITIONAL_MARGINALS[...]`, so that mutation path belongs to T550 rather than T549.

### Audit/read-model integration

- The accepted order records `previousMarginals`, `newMarginals`, `impactScore`, `commandId`, and timestamps.
- `sync_account_risk_state(...)` threads the accepted edit into the account-risk read model and LMSR ledger slices.
- `build_terminal_acceptance_response(...)` emits the terminal event with `marginalDelta`, `assetDelta`, pricing, and replay-state hash.

## What The DAG Should Represent

Because the branch already contains the T549 behavior, the child DAG should be read as a seam decomposition of the existing implementation, not as proof that every node is still missing.

The clean T549-owned packages are:

1. choosing the unconditional base slice
2. applying the soft-evidence rescale deterministically
3. mutating unconditional market/order state on acceptance
4. threading the accepted result into existing audit/read models
5. locking the behavior with regression and invariant coverage

## Verification

Validated against the checked-in test suite:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_*.py'`
- Result: `Ran 181 tests in 5.019s` / `OK`

Relevant coverage already exercises:

- unconditional success and market mutation
- unconditional account-risk/read-model updates
- unconditional min-asset rejection and idempotent replay
- property tests across multiple markets/outcomes
- brute-force invariant agreement for repeated probability edits
