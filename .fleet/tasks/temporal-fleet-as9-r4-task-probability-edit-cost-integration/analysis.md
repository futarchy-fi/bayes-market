# task-probability-edit-cost-integration

## Summary

`backend/lmsr.py` now provides the LMSR quote primitives and `ACCOUNT_RISK[*]["lmsrState"]` already records additive score deltas, but the `ProbabilityEdit` acceptance path in `backend/server.py` still prices edits with the legacy KL helper.

This task should replace that remaining scalar-cost seam with the new LMSR primitives while keeping the existing external contract stable:

- keep `impactScore` as the field name on orders, previews, rejections, and responses
- keep terminal command/event emission and replay behavior unchanged
- keep idempotency conflict/replay semantics unchanged
- keep unconditional and accepted conditional edits flowing through the same response and risk-sync plumbing

## What Exists Today

- `_preview_probability_target_distribution(...)` already delegates the probability transition itself to `lmsr.rescale_probability_edit(...)`.
- `preview_unconditional_probability_edit(...)` still computes `impactScore` as `kl_divergence(previous_marginals, updated_marginals)`.
- `create_probability_edit_order(...)` reuses that preview for unconditional edits, but accepted conditional edits still fall back to `kl_divergence(...)` because `preview` is `None`.
- `sync_account_risk_state(order)` debits `order["impactScore"]` from overall and per-market `minAsset`, and `build_terminal_acceptance_response(...)` publishes `pricing.cost = order["impactScore"]`.
- Because of that wiring, changing how `order["impactScore"]` is computed is enough to thread the new math through:
  - account-risk updates
  - acceptance events
  - HTTP acceptance payloads
  - rejection preview payloads for unconditional edits

So the integration cut is narrow: replace the scalar quote source, not the surrounding command/event/read-model framework.

## Recommended Integration Cut

Add one shared helper in `backend/server.py` that produces the canonical quote inputs used everywhere else. A shape like this is sufficient:

- resolve the base marginals with `resolve_probability_edit_base_marginals(market_id, context)`
- compute the updated marginals with the existing structure-preserving path (`apply_probability_target(...)` / `_preview_probability_target_distribution(...)`)
- compute scalar LMSR cost with `lmsr.lmsr_expected_edit_cost(previous, updated, market["liquidity"])`
- round that scalar once with `round_risk_value(...)`
- return:
  - `previousMarginals`
  - `newMarginals`
  - `impactScore`

That helper should then be used in exactly two places:

1. `preview_unconditional_probability_edit(...)`
   - keep the empty-context guard
   - swap out the KL computation for the shared LMSR quote
   - continue returning the same preview shape, including `assetDelta.impactScore`

2. `create_probability_edit_order(...)`
   - unconditional path: keep accepting an optional precomputed preview so the acceptance path still avoids recomputing after the rejection check
   - conditional path: compute the same shared LMSR quote before mutating `CONDITIONAL_MARGINALS`
   - set `order["impactScore"]` from the shared quote in both branches

This keeps unconditional preview and accepted-order pricing on one formula and removes the current unconditional/conditional split where the two branches happen to store the same field name but derive it differently.

## Why This Cut Is Correct

### 1. It fixes both required paths without reopening unrelated behavior

The task description calls out:

- KL-based preview
- order-cost path
- unconditional edits
- accepted conditional edits

Those all converge on `preview_unconditional_probability_edit(...)` and `create_probability_edit_order(...)`. `sync_account_risk_state(...)`, `build_terminal_acceptance_response(...)`, `build_terminal_rejection_response(...)`, and idempotency handling already consume the quoted scalar indirectly.

### 2. It preserves the compatibility boundary already frozen by the docs

`docs/t556-scope-and-compatibility-boundary-freeze.md` already freezes:

- `market.liquidity` as the LMSR `b` parameter
- stable HTTP/event/read-model field names
- internal math replacement without public envelope redesign

This task fits that boundary exactly: internal scalar pricing changes, public response keys do not.

### 3. It prevents preview/order drift

If preview and order creation each keep their own formula, they will drift again. A shared quote helper makes the unconditional rejection preview and accepted order payload derive from the same canonical marginal transition and the same liquidity input.

## Implementation Notes

- Compute LMSR cost from the same canonical marginals that will be stored on the order, not from a different intermediate representation. That keeps replay/debug recomputation aligned with `order["previousMarginals"]` and `order["newMarginals"]`.
- Keep mutation ordering unchanged:
  - idempotency replay/conflict check first
  - command materialization next
  - active-market gate next
  - unconditional solvency preview next
  - only then mutate `MARKETS` or `CONDITIONAL_MARGINALS`
- Do not change `sync_probability_edit_lmsr_state(...)`. It already derives per-outcome LMSR score deltas from stored marginals plus `market["liquidity"]` and does not depend on the old KL helper.
- There is no need to rename `impactScore` even though the meaning changes from KL divergence to liquidity-weighted LMSR expected cost. The task explicitly asks to preserve current response field names.

## Regression Surface

The main fallout is in tests that still define `impactScore` as KL:

- `tests/test_bayes_market_api.py`
  - `test_unconditional_probability_edit_property_accepted_order_impact_matches_kl_divergence`
  - `test_invariant_probability_edit_matches_bruteforce_reference_on_tiny_nets`
  - `test_invariant_repeated_probability_edits_match_bruteforce_reference_on_same_slice`
- any acceptance-event assertions that implicitly equate `pricing.cost` with KL through `order["impactScore"]`

Tests that derive expectations through `preview_unconditional_probability_edit(...)` should mostly survive once that helper switches to LMSR, because they already compare response fields to preview fields rather than hard-coding KL.

## Recommended Test Plan

1. Update the KL-pinned API/property tests to compare against LMSR cost instead.
   - Prefer using `server.lmsr.lmsr_expected_edit_cost(...)` plus `server.round_risk_value(...)`, or the new shared quote helper if it is kept test-visible.

2. Keep the existing replay/idempotency tests intact.
   - The task must not change:
     - conflict detection
     - rejection replay
     - accepted replay
     - event ids / command ids on replayed outcomes

3. Add focused integration coverage for accepted conditional edits.
   - Prove `order["impactScore"]` on a conditional acceptance equals LMSR cost computed from that slice's `previousMarginals` and `newMarginals`, not from the old KL helper.
   - Assert the same scalar flows into:
     - account-risk debit
     - acceptance event `pricing.cost`
     - the returned order payload

4. Keep the current journal and read-model assertions.
   - Sequence numbers, hash chaining, emitted event types, `meta.idempotencyKeyEcho`, and `GET /v1/accounts/{id}/risk` field names should remain unchanged.

## Risks And Decisions To Lock

- `lmsr.lmsr_expected_edit_cost(...)` requires strictly positive input probabilities. The current active market state and probability-edit normalization appear to preserve that invariant, but the server integration should fail loudly and predictably if a future caller supplies zero-mass marginals.
- Rounding should happen once at the server boundary via `round_risk_value(...)`. Do not round inside the pure LMSR helper and then round again in the order path.
- `kl_divergence(...)` may still remain in the file temporarily if other tests or code paths reference it, but it should no longer define `ProbabilityEdit` preview or accepted-order pricing after this task lands.

## Expected Outcome

After this task:

- unconditional preview cost uses LMSR
- accepted unconditional order cost uses the same LMSR quote
- accepted conditional order cost also uses LMSR
- `impactScore`, `pricing.cost`, `assetDelta`, idempotency replay, and terminal command/event emission all keep their current shapes
- the only semantic change is that the scalar cost behind those existing fields now comes from `market.liquidity`-backed LMSR math instead of KL
