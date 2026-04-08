# T549 Unconditional Soft-Evidence Ownership Boundary Freeze

Date: 2026-04-08
Branch: `ff/Ttemporal-fleet-7op-r1-t549-boundary`

## Question

Confirm the ownership boundary around `T549` in the checked-in `ProbabilityEdit` pipeline:

- `T549` owns only the empty-context soft-evidence application path
- `T550` owns contextual slice mutation
- `T551` owns structure-preserving validation
- `T557` owns the unconditional min-asset gate
- `T544` and `T1737` own the command/event envelopes

## Decision

Freeze `T549` as the **empty-context-only soft-evidence application seam**.

In the live checkout, that seam is:

- computing the unconditional `previousMarginals -> newMarginals` transition for `context == []`
- reusing that preview on acceptance
- mutating only `MARKETS[market_id]["marginals"]` on the accepted empty-context path

`T549` does **not** own:

- contextual slice mutation in `CONDITIONAL_MARGINALS`
- structure-preserving validation or context canonicalization
- unconditional solvency rejection
- canonical command or terminal event envelope materialization

## Frozen Ownership Map

| Task | Owned seam | Live evidence |
|---|---|---|
| `T549` | Empty-context soft-evidence application | `preview_unconditional_probability_edit(...)`; empty-context branch of `create_probability_edit_order(...)` |
| `T550` | Non-empty-context slice mutation | contextual branch of `create_probability_edit_order(...)` writing `CONDITIONAL_MARGINALS[market_id][context_key]` |
| `T551` | Structure-preserving validation over normalized state | `validate_structure_preserving_edit(...)` called from `normalize_probability_edit_payload(...)` before command/order mutation |
| `T557` | Empty-context min-asset pre-acceptance gate | `handle_probability_edit(...)` rejects with `min_asset_violation` only when `normalized_payload["context"] == []` |
| `T544` | Canonical `bayes-command/v1` and `bayes-event/v1` envelopes | `materialize_probability_edit_command(...)`, `emit_terminal_event(...)`, `build_terminal_*_response(...)` |
| `T1737` | Thin REST request/response boundary for the endpoint | `handle_probability_edit(...)` accepts route-local REST fields and constructs the canonical command internally |

## Why T549 Stops At The Empty-Context Application Seam

The checked-in backend separates unconditional and contextual write paths inside `create_probability_edit_order(...)`:

- when `context` is non-empty, the route computes updated marginals for that contextual slice and stores them under `CONDITIONAL_MARGINALS`
- when `context` is empty, the route reuses the unconditional preview and mutates only `MARKETS[market_id]["marginals"]`

That is the cleanest ownership seam available in the code. The unconditional branch is a distinct path with distinct side effects, and those side effects are limited to the market's top-level marginals.

The helper that defines the unconditional path is `preview_unconditional_probability_edit(...)`. It:

- rejects any non-empty context up front
- reads the unconditional base marginals with `resolve_probability_edit_base_marginals(market_id, [])`
- applies the probability target to that empty-context slice
- computes the resulting `impactScore`

Tests already pin that helper as side-effect free: it previews the unconditional edit without mutating market state, conditional slices, orders, or account risk.

On acceptance, the empty-context branch of `create_probability_edit_order(...)` reuses exactly that preview and writes the resulting distribution back to `MARKETS[market_id]["marginals"]`.

That is the `T549` seam:

```text
empty context
-> unconditional base marginals
-> apply soft evidence
-> accepted unconditional market marginal mutation
```

No contextual slice write is part of that seam.

## Why Contextual Mutation Belongs To T550

The non-empty-context branch is materially different:

- it computes `context_key = context_state_key(context)`
- it resolves the context-conditioned base slice
- it applies the target against that contextual base slice
- it writes the result to `CONDITIONAL_MARGINALS[market_id][context_key]`
- it leaves `MARKETS[market_id]["marginals"]` unchanged

The tests confirm this split repeatedly:

- a contextual edit updates `CONDITIONAL_MARGINALS` while leaving unconditional market marginals unchanged
- contextual edits still succeed even when the counterfactual unconditional preview would fail the `min_asset_violation` rule
- repeated contextual edits are validated against the same contextual slice and stored back into that contextual slot

That is not a variant of the unconditional path. It is a different mutation target with different routing semantics, so it belongs to `T550`, not `T549`.

## Why T551 Stops Earlier

`normalize_probability_edit_payload(...)` resolves the candidate base marginals and then calls `validate_structure_preserving_edit(...)` before any command persistence or order creation.

That validator owns only normalized-distribution coherence:

- outcome membership
- context reference validity
- exact market-outcome coverage
- finite, non-negative, unit-sum mass
- renormalization feasibility

It does not mutate `MARKETS` or `CONDITIONAL_MARGINALS`, emit events, or perform solvency rejection.

So `T551` is upstream of both `T549` and `T550`. It validates the slice they would use; it does not own either mutation path.

## Why T557 Stops At The Empty-Context Gate

`handle_probability_edit(...)` materializes the canonical command first, then runs an unconditional solvency preview only when `normalized_payload["context"]` is empty.

If that preview shows `afterMinAsset < 0`, the route returns `409 min_asset_violation` via `build_terminal_rejection_response(...)` before order creation.

That means `T557` owns:

- the empty-context pre-acceptance reject decision
- the `min_asset_violation` reason code and details
- the side-effect boundary for unconditional rejection

`T557` does not own the unconditional probability-shift math itself. It consumes the unconditional preview to decide whether the command may proceed.

One implementation nuance is worth freezing explicitly: `preview_unconditional_probability_edit(...)` currently returns both the soft-evidence preview and an `assetDelta` preview. That does not make `T549` the owner of the solvency policy. The policy decision still lives in `handle_probability_edit(...)`, where the route interprets that preview and emits the rejection.

## Why T544 And T1737 Own The Envelopes

The public endpoint does not accept a raw canonical command envelope. `handle_probability_edit(...)` accepts the thin REST body defined by the route contract:

- `accountId`
- optional `idempotencyKey`
- `variableId`
- `target`
- `context`

The canonical envelope is constructed later by `materialize_probability_edit_command(...)`, which fills:

- `schemaVersion`
- `commandId`
- `marketId`
- `accountId`
- `commandType`
- `submittedAt`
- `payload`

Likewise, terminal acceptance and rejection envelopes are emitted by:

- `emit_terminal_event(...)`
- `build_terminal_rejection_response(...)`
- `build_terminal_acceptance_response(...)`

That is exactly the split frozen by the existing contract docs:

- `T1737` owns the thin HTTP boundary
- `T544` owns the canonical command/event contract behind that boundary

So `T549` should not absorb ownership of `commandId`, `submittedAt`, `schemaVersion`, event payload structure, or the HTTP `{order, result, meta}` response envelope.

## Consequence

The checked-in pipeline supports the requested boundary exactly:

- `T549` is the empty-context application path
- `T550` is the contextual mutation path
- `T551` is the pre-mutation structure validator
- `T557` is the unconditional min-asset gate
- `T544` and `T1737` own the canonical/public envelopes

The only notable coupling is that the unconditional preview helper currently packages both application and risk-preview data. That is an implementation convenience, not a transfer of task ownership.

## Sources

- `backend/server.py`
- `tests/test_bayes_market_api.py`
- `docs/t544-event-sourcing-contract.md`
- `docs/t1737-probability-edit-http-contract-freeze.md`
- `docs/t551-structure-preserving-validator-boundary-freeze.md`
- `docs/t557-unconditional-solvency-contract-freeze.md`
- `docs/t537-epic-execution-baseline.md`
