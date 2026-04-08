# T549 Unconditional Effects Analysis

## Summary

The requested behavior is already implemented in the current checkout.

Accepted unconditional `ProbabilityEdit` commands are already threaded through all of the surfaces named in this task:

- terminal `CommandAccepted` event payload
- acceptance pricing payload
- replay-state hash
- account-risk read model
- account LMSR ledger slices

So this task is best understood as a verification seam over existing code, not as a missing production integration.

## Current Implementation Evidence

### 1. The unconditional acceptance path already carries the previewed edit forward

`backend/server.py::handle_probability_edit(...)` does the unconditional flow only when `normalized_payload["context"] == []`:

1. build canonical command
2. call `preview_unconditional_probability_edit(...)`
3. reject pre-acceptance on negative `afterMinAsset`
4. call `create_probability_edit_order(command, preview=preview)`
5. call `sync_account_risk_state(order)`
6. call `build_terminal_acceptance_response(command, order, asset_delta, scope_key)`

That means the same accepted unconditional transition is already reused across market mutation, account-risk mutation, and event emission.

### 2. The terminal event already publishes the accepted unconditional edit

`backend/server.py::build_terminal_acceptance_response(...)` emits `CommandAccepted` with:

- `effects.marginalDelta`
- `effects.assetDelta`
- `pricing.cost`
- `pricing.fee`
- `replayStateHash`

For unconditional edits, `marginalDelta` omits `context`, which matches the empty-context contract, and `pricing.cost` is `order["impactScore"]`.

So the accepted unconditional edit is already present in the existing audit event rather than being trapped only in the order object.

### 3. The replay-state hash already reflects the accepted unconditional market mutation

`backend/server.py::market_replay_state_hash(...)` hashes:

- `MARKETS[market_id]`
- `CONDITIONAL_MARGINALS.get(market_id, {})`

The empty-context branch of `create_probability_edit_order(...)` mutates `MARKETS[market_id]["marginals"]` and leaves conditional slices alone.

Because `build_terminal_acceptance_response(...)` computes `replayStateHash` after that mutation, the event already carries a hash of the post-acceptance unconditional market state.

### 4. The account-risk read model already consumes accepted unconditional edits

`backend/server.py::sync_account_risk_state(...)` already applies every accepted `ProbabilityEdit` order to the account-risk read model by:

- debiting `account["minAsset"]`
- updating per-market `minAsset`, `capacityConsumed`, `utilization`, and `commandCount`
- stamping `updatedAt`, `lastOrderId`, and `lastCommandId`

That is exactly the read-model threading requested in the task description.

### 5. The LMSR ledger slice integration already runs on accepted unconditional edits

Inside `sync_account_risk_state(...)`, `ProbabilityEdit` orders call `sync_probability_edit_lmsr_state(account, order)`.

That helper already:

- derives the slice key from `marketId` plus `context`
- computes `scoreByOutcome` from `order["previousMarginals"]` and `order["newMarginals"]`
- creates or updates the ledger slice
- increments `commandCount`
- records `lastOrderId` and `lastCommandId`

For unconditional edits the context is `[]`, so the accepted edit is already accumulated into the empty-context LMSR ledger slice.

## Coverage Status

The existing tests already pin the main seams this task names:

- accepted unconditional success updates market state and terminal event effects
- accepted unconditional orders persist `previousMarginals`, `newMarginals`, and `impactScore`
- account-risk read model updates after unconditional probability edits
- unconditional acceptance populates the LMSR ledger slice
- idempotent replay does not double-apply account-risk or LMSR state
- HTTP happy-path coverage checks event payload, replay hash, market read, and account-risk read

## Likely Remaining Work

I do not see a production-code gap for this task in the current branch.

If any follow-up is still desired, the narrowest useful work would be regression-hardening only:

1. add or tighten assertions that unconditional acceptance surfaces all of the expected fields together in one end-to-end test
2. avoid refactoring `handle_probability_edit(...)`, `sync_account_risk_state(...)`, or `build_terminal_acceptance_response(...)` because those seams already line up cleanly with the task boundary
3. leave broader invariant expansion to the downstream `t549-unconditional-coverage` task, which already exists in the decomposition

## Verification

Ran:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'`

Result:

- `Ran 146 tests in 5.027s`
- `OK`
