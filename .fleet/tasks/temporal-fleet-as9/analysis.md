# bayes-T556-implement-lmsr-cost-function

## Summary

The repo already exposes the full `ProbabilityEdit` HTTP flow, but the pricing/risk math is still a stub. `backend/server.py` computes edit cost as `kl_divergence(previous_marginals, updated_marginals)`, debits a scalar `minAsset`, and exposes that scalar through accepted events, rejection details, and `GET /v1/accounts/{id}/risk`.

`T556` is therefore not a one-line math swap. It is the seam where the backend needs to stop treating `impactScore` as a placeholder KL debit and start using a real liquidity-aware LMSR cost path. The safe implementation boundary is: keep the current HTTP/event envelopes stable, use existing market liquidity as the LMSR `b` parameter, and introduce deterministic LMSR primitives/state that later solvency tasks (`T557`, `T558`, `T559`, `T561`) can consume.

## What Exists Today

- All pricing/risk logic lives in `backend/server.py`; there is no separate market-maker or asset-model module yet.
- Markets already carry a `liquidity` field, but nothing in the backend uses it. That is the obvious source for LMSR `b`.
- `preview_unconditional_probability_edit(...)` computes:
  - new marginals via `apply_probability_target(...)`
  - `impactScore` via `kl_divergence(...)`
  - asset preview via `beforeMinAsset - impactScore`
- `sync_account_risk_state(...)` persists only scalar headroom:
  - account-level `riskLimit` / `minAsset`
  - per-market `minAsset`, `capacityConsumed`, `utilization`, `commandCount`
- `handle_probability_edit(...)` only pre-checks empty-context edits. Conditional edits still skip the pre-acceptance solvency gate and then debit the same scalar risk state after acceptance.
- The current contracts already freeze the existing response surface around:
  - `order.impactScore`
  - accepted-event `pricing.cost`
  - `assetDelta.beforeMinAsset` / `afterMinAsset`
  - `min_asset_violation` rejection details
  - `/v1/accounts/{id}/risk` min-asset/capacity fields

## Why This Task Has Real Blast Radius

The current placeholder math is coupled across code, docs, and tests:

- `backend/server.py:543-631` owns scalar risk storage and read-model derivation.
- `backend/server.py:1285-1310` owns unconditional preview math.
- `backend/server.py:1314-1374` persists `order["impactScore"]`.
- `backend/server.py:1741-1828` wires the preview into acceptance/rejection behavior.
- `tests/test_bayes_market_api.py` contains heavy direct coupling:
  - `impactScore` appears 60 times
  - `minAsset` appears 43 times
  - `preview_unconditional_probability_edit(...)` is called directly in 17 places

That means a pure helper replacement is insufficient. Any LMSR implementation will need to update the preview path, accepted-order pricing field, account risk mutation path, and a large body of tests that currently encode the placeholder scalar model.

## Scope Boundary To Preserve

There is one important scope ambiguity:

- the epic baseline names `T556` as `Implement per-user asset model transformation (Sx = b ln q(x))`
- this task is titled `implement-lmsr-cost-function`

The codebase does not currently contain the full formal `q(x)` representation, so the safest interpretation is:

1. implement real LMSR pricing/cost primitives now
2. thread those primitives through the edit flow
3. introduce deterministic account-side LMSR state/compatibility hooks
4. do **not** invent GS or DAC logic inside this task

That keeps `T556` upstream of later solvency work instead of collapsing `T557`, `T558`, `T559`, and `T560` into one branch.

## Recommended Implementation Boundary

- Preserve current public envelopes unless a separate contract task says otherwise.
  - Keep `order.impactScore` as the response field name if possible, even if the internal math changes.
  - Keep accepted-event `pricing.cost` and `assetDelta` shape stable.
  - Keep `GET /v1/accounts/{id}/risk` shape stable, even if its values become derived from a richer internal state.
- Use `market["liquidity"]` as the authoritative LMSR `b` parameter.
- Extract LMSR math into a dedicated backend module instead of making `server.py` absorb more pricing logic.
- Leave GS minimum-asset evaluation to `T559` and DAC decisions to `T560`.

## Concrete Seams For Child Tasks

### 1. Pricing primitives

Current code still treats the edit path as:

- transform marginals
- compute KL divergence
- reuse that scalar everywhere as cost/risk debit

This should move into pure LMSR helpers that are testable without the HTTP route.

### 2. Account-side state

`ACCOUNT_RISK` currently stores only scalar headroom. That is enough for the current stub rejection, but not enough for a real per-user LMSR-backed asset model. `T556` should add the deterministic account-side state container that later min-asset tasks will read from, instead of forcing `T559` to reconstruct it from legacy response fields.

### 3. ProbabilityEdit integration

The integration cut is centered on:

- `preview_unconditional_probability_edit(...)`
- `create_probability_edit_order(...)`
- `sync_account_risk_state(...)`
- `handle_probability_edit(...)`

These functions currently assume one scalar cost/headroom number. They are the place where LMSR-derived values need to replace placeholder KL-derived values while keeping idempotency and event sequencing intact.

### 4. Regression coverage

The tests are tightly coupled to the existing placeholder math and helper names. Any implementation that changes pricing without refreshing the tests will leave the repo in a misleading state.

## Risks And Open Questions

- There is no in-tree blueprint or formal `q(x)` state schema, so the account-state shape must be pinned down before route rewiring starts.
- Conditional edits currently mutate the same scalar risk state on acceptance even though their admissible-range logic is deferred to `T558`. `T556` has to decide whether accepted conditional edits also update the new LMSR-backed account state now, or whether a temporary compatibility bridge is needed.
- If the task is interpreted narrowly as “cost function only,” the implementation should still leave behind reusable state/primitives so later solvency tasks do not have to undo another stopgap.

## Recommended Child-Task Shape

The right DAG for this branch is:

1. freeze scope/compatibility boundaries first
2. define deterministic LMSR-backed account state shape
3. add pure LMSR pricing helpers
4. wire them through `ProbabilityEdit`
5. refresh the regression suite that currently encodes placeholder KL/min-asset assumptions
