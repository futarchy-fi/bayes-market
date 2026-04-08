# T549 Soft-Evidence Rescale Analysis

## Summary

The requested unconditional ProbabilityEdit math is already implemented in the current checkout.

For empty-context edits, the code already:

- reads the unconditional base slice through `resolve_probability_edit_base_marginals(...)`
- rescales the targeted outcome to the requested probability
- deterministically renormalizes the remaining outcomes
- computes `impactScore` from the resulting `previousMarginals -> newMarginals` transition
- reuses that preview on the accepted unconditional path

So this task reads as a decomposition of the live seam, not a currently missing production feature.

## Current Implementation Evidence

### 1. Deterministic rescaling already exists in the pure math helper

`backend/lmsr.py::rescale_probability_edit(...)` already performs the exact soft-evidence transform described by the task:

- validates a unit-sum distribution and target probability
- sets the addressed outcome to the requested target probability
- rescales every non-target outcome proportionally to its previous mass
- falls back to equal redistribution when the previous non-target mass is zero
- fixes floating-point drift by assigning the residual to the final non-target outcome

That is already the deterministic unconditional rescaling rule.

### 2. The server path already uses that helper for unconditional ProbabilityEdit preview/application

`backend/server.py::_preview_probability_target_distribution(...)` calls `lmsr.rescale_probability_edit(...)` and rounds the resulting distribution into route-facing output order.

`backend/server.py::apply_probability_target(...)` wraps that helper in API validation/error semantics.

`backend/server.py::preview_unconditional_probability_edit(...)` then:

- rejects non-empty context
- resolves `previousMarginals` through `resolve_probability_edit_base_marginals(market_id, [])`
- computes `newMarginals` via `apply_probability_target(...)`
- computes `impactScore`
- returns the preview plus `assetDelta`

### 3. The accepted unconditional order path already reuses that preview

In `backend/server.py::create_probability_edit_order(...)`, the empty-context branch:

- reuses `preview_unconditional_probability_edit(...)` when available
- copies `previousMarginals` and `newMarginals` from that preview
- mutates only `MARKETS[market_id]["marginals"]`
- writes `order["impactScore"]` from the same preview

That is the exact T549 seam expected by the parent DAG:

```text
empty context
-> resolve unconditional base marginals
-> apply deterministic soft-evidence rescale
-> compute impactScore
-> persist accepted unconditional market state
```

### 4. Existing tests already pin the core behavior

`tests/test_bayes_market_lmsr.py` already covers:

- exact target attainment in binary markets
- proportional preservation of non-target relative mass in multi-outcome markets
- deterministic equal redistribution when previous non-target mass is zero

`tests/test_bayes_market_api.py` already covers:

- unconditional preview shape and side-effect freedom
- three-outcome unconditional edits producing the expected renormalized marginals
- property/invariant checks that accepted orders persist the same transition they previewed
- `impactScore == kl_divergence(previousMarginals, newMarginals)` on accepted ProbabilityEdit orders

## Impact Score Note

The current checkout computes unconditional `impactScore` as `kl_divergence(previous_marginals, updated_marginals)` in `backend/server.py`.

That matches the current T549 seam and the existing tests. It is also consistent with the broader repo state, where the later LMSR cost migration work is tracked separately under the `as9` task family.

So for this branch, the important conclusion is:

- deterministic rescaling is already live
- the resulting scalar impact score is already derived from that rescaled distribution
- replacing the scalar formula with liquidity-weighted LMSR cost would be a different task, not unfinished T549 core math

## Residual Risk

The main residual risk is not missing production math; it is regression risk.

The implementation now depends on a small chain of helpers:

- `resolve_probability_edit_base_marginals(...)`
- `apply_probability_target(...)`
- `preview_unconditional_probability_edit(...)`
- empty-context branch of `create_probability_edit_order(...)`

If any future refactor bypasses that chain, unconditional edits could silently stop using the deterministic rescaling helper even though the current tests would likely catch most of it.

## Plan

1. Treat the task's production math as already satisfied in the current branch.
2. Preserve `backend/lmsr.py::rescale_probability_edit(...)` as the single deterministic rescaling primitive for unconditional ProbabilityEdit transitions.
3. Keep unconditional preview/order paths sourcing both `newMarginals` and `impactScore` from the same rescaled transition.
4. If follow-up implementation is still expected on this branch, spend it on regression hardening rather than new math:
   - add or tighten unconditional-path tests that explicitly prove preview and accepted order share the same rescaled marginals
   - keep multi-outcome proportional renormalization pinned
   - keep accepted-order `impactScore` aligned with the previewed transition

## Verification

- `python3 -m unittest discover -s tests -p 'test_bayes_market_lmsr.py'` -> `Ran 11 tests` / `OK`
- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'` -> `Ran 144 tests` / `OK`
