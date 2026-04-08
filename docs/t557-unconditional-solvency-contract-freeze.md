# T557 Unconditional Solvency Contract Freeze

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-efi-r1-bayes-t557-freeze-unconditional-solvency-contract`

## Question

For the current stub backend in `apps/bayes-market/backend/server.py`, what exact pre-acceptance solvency rule should govern `POST /v1/markets/{id}/orders/probability-edit` when `context == []`, and what rejection payload must the route emit when that rule fails?

## Decision

Freeze `T557` as an **empty-context-only** pre-acceptance guard that uses the same placeholder account-risk model already present in `server.py`.

That means:

- `T557` applies only when the normalized `ProbabilityEdit` payload has `context == []`
- the solvency preview uses the current `ACCOUNT_RISK` snapshot, `ACCOUNT_RISK_LIMIT`, and the order's computed `impactScore`
- rejection occurs before `create_probability_edit_order(...)` and before any market or account-risk mutation
- non-empty `context` requests are explicitly out of scope for this task and stay deferred to `T558`

This freeze does **not** claim the stub model is the final Bayes asset engine. It only freezes the contract that the current placeholder backend must expose until `T556`/`T559` replace the math.

## Existing Stub Behavior That Defines The Seam

The current backend already exposes the pieces needed for a deterministic pre-check:

- `ACCOUNT_RISK_LIMIT = 100.0`
- `ACCOUNT_RISK` stores per-account `riskLimit`, `minAsset`, and per-market consumed capacity
- `create_probability_edit_order(...)` computes `impactScore` as `kl_divergence(previous_marginals, updated_marginals)`
- `sync_account_risk_state(order)` subtracts that `impactScore` from the account's `minAsset` after acceptance
- `build_terminal_rejection_response(...)` already emits terminal `CommandRejected` events and replayable rejection responses

So `T557` does not need a new rejection framework. It needs the same math to run as a preview before acceptance side effects.

## Exact Pre-Acceptance Rule For `context == []`

For normalized `ProbabilityEdit` requests with an empty `context` array, the backend must evaluate solvency in this order:

1. Validate the request and normalize the payload.
2. Apply idempotency replay/conflict handling exactly as it works today.
3. Materialize the canonical command envelope exactly as it works today.
4. Enforce the existing active-market gate exactly as it works today.
5. If `normalized_payload["context"] == []`, compute an unconditional solvency preview before order creation.
6. Reject if the previewed `afterMinAsset` is negative.
7. Only if the preview passes, proceed to `create_probability_edit_order(...)`, `sync_account_risk_state(order)`, and `build_terminal_acceptance_response(...)`.

The preview math must be:

```text
previousMarginals = deepcopy(MARKETS[market_id]["marginals"])
updatedMarginals = apply_probability_target(market, target.outcomeId, target.probability, previousMarginals)
impactScore = kl_divergence(previousMarginals, updatedMarginals)

account = ACCOUNT_RISK.get(account_id)
if account is None:
    riskLimit = round_risk_value(ACCOUNT_RISK_LIMIT)
    beforeMinAsset = round_risk_value(ACCOUNT_RISK_LIMIT)
else:
    riskLimit = round_risk_value(float(account["riskLimit"]))
    beforeMinAsset = round_risk_value(float(account["minAsset"]))

afterMinAsset = round_risk_value(beforeMinAsset - impactScore)
reject iff afterMinAsset < 0
```

Equivalent rejection test:

```text
reject iff impactScore > beforeMinAsset
```

Equivalent acceptance boundary:

```text
accept iff afterMinAsset >= 0
```

## What The Placeholder Model Means In Practice

This freezes the current stub's risk semantics, not the final MVP engine:

- A brand-new account starts with `beforeMinAsset = ACCOUNT_RISK_LIMIT = 100.0`.
- The placeholder model treats `impactScore` as the capacity consumed by the edit.
- `impactScore` is the same six-decimal KL-divergence value already written into accepted orders.
- Account capacity is monotonic in the stub: every accepted edit consumes capacity, and the stub does not implement any replenishment path.
- The pre-check must use the account-level `minAsset` snapshot, not a new per-state or GS computation.

Per-market risk records remain part of the read model, but they are not the reject criterion for `T557`. The reject criterion is the previewed **overall** `beforeMinAsset -> afterMinAsset` transition at the account level.

## Boundary At Zero

The rejection floor is **negative**, not zero.

So:

- `afterMinAsset < 0` => reject
- `afterMinAsset == 0` => accept

That matches the Bayes solvency invariant already stated in the planning docs and event contract: accepted commands must not produce negative state-contingent assets.

One stub-specific nuance remains:

- `build_capacity_indicators(...)` labels `min_asset <= 0` as `"breached"`

So an accepted boundary case with `afterMinAsset == 0` would still surface a `"breached"` capacity status on the read model. That read-model label does not change the `T557` acceptance threshold.

## Required Rejection Contract

When the empty-context preview fails, the route must emit the same terminal rejection envelope already used for `market_not_active`, but with the solvency-specific values reserved by `t544-event-sourcing-contract.md`.

### HTTP response

- status: `409`
- `error.code`: `"min_asset_violation"`
- `error.message`: `"Edit would produce negative state-contingent assets"`
- `result.status`: `"rejected"`
- `result.eventType`: `"CommandRejected"`
- `result.reasonCode`: `"min_asset_violation"`
- `result.reason`: `"Edit would produce negative state-contingent assets"`
- `result.retryHint`: `"reduce probability target"`

### `CommandRejected` event payload

The terminal event payload must be:

```json
{
  "reasonCode": "min_asset_violation",
  "reason": "Edit would produce negative state-contingent assets",
  "retryHint": "reduce probability target"
}
```

### `error.details` fields that must be emitted

The HTTP error payload must carry these deterministic preview fields in `error.details`:

- `accountId`
- `marketId`
- `commandId`
- `riskLimit`
- `beforeMinAsset`
- `impactScore`
- `afterMinAsset`

Frozen shape:

```json
{
  "accountId": "acct_abc",
  "marketId": "m1",
  "commandId": "cmd_01J...",
  "riskLimit": 100.0,
  "beforeMinAsset": 0.031245,
  "impactScore": 0.058577,
  "afterMinAsset": -0.027332
}
```

Why this field set:

- `accountId`, `marketId`, and `commandId` match the current terminal rejection detail style.
- `riskLimit` makes the placeholder model explicit instead of hiding the fixed `ACCOUNT_RISK_LIMIT` assumption.
- `beforeMinAsset`, `impactScore`, and `afterMinAsset` are the complete deterministic preview needed to explain and test the rejection.

No additional contextual-bound fields should be emitted in `T557`, because non-empty-context admissible range logic is not frozen here.

## Required Side-Effect Boundary

On a `min_asset_violation` rejection for `context == []`, the request must remain pre-acceptance with respect to market and account-risk state.

The rejection may still:

- persist the canonical command
- emit one terminal `CommandRejected` event
- persist the terminal outcome
- bind the idempotency key for replay, if present

The rejection must not:

- mutate `MARKETS[market_id]["marginals"]`
- create an order in `ORDERS`
- mutate `ACCOUNT_RISK`
- create or mutate conditional marginals

That is the exact meaning of "pre-acceptance" for this stub route.

## Explicit Deferment To `T558`

`T557` must not invent a conditional solvency policy.

For any normalized `ProbabilityEdit` with non-empty `context`:

- do not apply the unconditional `beforeMinAsset - impactScore` gate as if it were authoritative for conditional bounds
- do not emit `min_asset_violation` based on this unconditional placeholder rule
- leave admissible-range and bound computation for contextual edits to `T558`

Reason:

- the current backend stores conditional edits in `CONDITIONAL_MARGINALS`
- `T558` is the task that owns conditional edit allowable range bounds
- reusing the unconditional placeholder rule for contextual edits would silently collapse two different contracts into one and overclaim correctness

## Current Stub Gap

`server.py` does **not** implement this rejection yet.

Today the route still:

- creates the order first
- mutates marginals
- subtracts `impactScore` from account risk after acceptance
- accepts both empty-context and non-empty-context edits through the same risk-blind path

This document freezes the contract that `T557` should implement next; it does not claim the branch already enforces it.
