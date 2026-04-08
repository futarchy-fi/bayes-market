# task-lmsr-math-primitives

## Summary

`backend/server.py` currently owns both pieces of the ProbabilityEdit math seam:

- `_preview_probability_target_distribution(...)` computes the structure-preserving probability transition
- `kl_divergence(...)` computes the scalar `impactScore`

That makes the pricing path hard to test in isolation and keeps LMSR math coupled to HTTP/risk plumbing. This task should split out a pure LMSR math module first, without taking on the later route-integration and account-ledger work.

## What Exists Today

- `market["liquidity"]` already exists on every market, but the backend never uses it.
- Unconditional preview still computes cost as `kl_divergence(previous_marginals, updated_marginals)`.
- Conditional edits reuse the same scalar `impactScore` path after acceptance.
- The decomposition already separates this task from:
  - `task-account-lmsr-ledger`
  - `task-probability-edit-cost-integration`
  - `task-regression-coverage`

That separation matters: this task should introduce reusable math primitives, not rewrite the entire order flow.

## Recommended Boundary

Add a dedicated pure module, likely `backend/lmsr.py`, and move the probability-edit math there.

Recommended helper surface:

- `rescale_probability_edit(previous, outcome_id, target_probability) -> updated`
  - pure probability transition helper
  - preserves non-target relative mass, matching current route behavior
- `lmsr_score_delta(previous, updated, liquidity) -> dict[str, float]`
  - computes per-outcome log-score / asset transition
  - formula: `delta_i = b * ln(updated_i / previous_i)`
- `lmsr_expected_edit_cost(previous, updated, liquidity) -> float`
  - computes the scalar liquidity-aware edit cost
  - formula: `sum(updated_i * delta_i)`
  - equivalent to `b * KL(updated || previous)` when all probabilities are strictly positive
- `quote_probability_edit(previous, outcome_id, target_probability, liquidity) -> quote`
  - convenience wrapper returning `updated`, `score_delta`, and scalar cost in one pure call

This gives later tasks both of the things they need:

- a deterministic scalar price/cost number for route integration
- the richer per-outcome transition needed by the later LMSR-backed account-state work

## Why This Is The Right Cut

### 1. The probability transition is already pure, but trapped in `server.py`

`_preview_probability_target_distribution(...)` does not depend on HTTP, storage, events, or account state. It is already a math helper in disguise and should move first.

### 2. LMSR `b` is already frozen to `market.liquidity`

`docs/t556-scope-and-compatibility-boundary-freeze.md` already froze `market.liquidity` as the LMSR liquidity parameter. This task is the right place to make the math actually consume that parameter.

### 3. A pure module keeps follow-on tasks smaller

If route integration is done before the math is extracted, later tasks will still be forced to test pricing through `handle_probability_edit(...)`. That is the wrong dependency direction.

## Implementation Plan

1. Add `backend/lmsr.py` with pure validation and math helpers only.
2. Move the structure-preserving probability transition logic out of `server.py` into the new module.
3. Add dedicated unit tests in a new file such as `tests/test_bayes_market_lmsr.py`.
4. Keep `server.py` behavior effectively unchanged in this task, except for any minimal import/use needed to avoid duplicated transition logic.
5. Leave `preview_unconditional_probability_edit(...)`, `create_probability_edit_order(...)`, `sync_account_risk_state(...)`, and `handle_probability_edit(...)` semantically unchanged until `task-probability-edit-cost-integration`.

## Test Plan

Add pure unit coverage for:

- binary and multi-outcome probability-edit rescaling
- normalization and non-negative mass preservation
- exact target-outcome probability placement
- liquidity scaling: doubling `b` doubles scalar cost and per-outcome score deltas
- scalar identity: `lmsr_expected_edit_cost(...) == b * KL(updated || previous)`
- repeated edits on the same slice produce deterministic quotes
- invalid inputs: unknown outcome, non-finite liquidity, zero/negative probabilities where log terms would break

The existing API tests should stay mostly untouched in this task. They belong to the later integration/regression tasks once the route actually starts consuming the new helpers.

## Risks And Decisions To Lock Early

- The helpers should require strictly positive probabilities for the LMSR log-ratio path. Current route validation already keeps targets in `(0, 1)`, but the pure module should still defend itself.
- Floating-point drift needs a single rounding strategy. The pure helpers should return full-precision floats and let the HTTP/risk layer keep using `round_risk_value(...)`.
- The scalar helper should be treated as a derived LMSR quote, not as the final account-solvency rule. The account-ledger task still owns how that math becomes persisted min-asset state.

## Expected Outcome

After this task, the repo should have a small, testable LMSR math surface that:

- consumes `market.liquidity`
- can quote a probability edit without touching global state
- exposes both scalar and per-outcome transition math
- gives the later integration task a clean import instead of more `server.py`-local formulas
