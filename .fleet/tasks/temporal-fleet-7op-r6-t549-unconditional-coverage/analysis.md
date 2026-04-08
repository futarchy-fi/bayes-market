# T549 Unconditional Coverage Analysis

## Summary

The unconditional `ProbabilityEdit` path is already implemented in the current checkout, and the test suite already covers most of the behaviors named in this task.

The safest reading of this branch is therefore:

- do not change `backend/server.py` behavior unless a gap is proven
- keep the work test-focused in `tests/test_bayes_market_api.py`
- tighten or reorganize coverage so the empty-context path is pinned explicitly as a deterministic seam under refactors

## Current Implementation Evidence

### 1. The unconditional path is already a distinct preview -> accept -> mutate flow

`backend/server.py` already isolates the empty-context path:

- `preview_unconditional_probability_edit(...)` requires `context == []`
- it reads unconditional base marginals via `resolve_probability_edit_base_marginals(market_id, [])`
- it applies the soft-evidence target and computes `impactScore`
- `handle_probability_edit(...)` uses that preview only for empty-context requests
- `create_probability_edit_order(...)` reuses the preview and mutates only `MARKETS[market_id]["marginals"]` on accepted empty-context submissions

That is the seam this task is trying to lock down.

### 2. The named regression behaviors already have direct coverage

The existing API suite already exercises the main unconditional cases:

- empty-context success:
  - `test_probability_edit_success_persists_unconditional_order_state`
  - `test_probability_edit_acceptance_threads_unconditional_effects_into_audit_and_read_models`
- idempotent replay:
  - `test_probability_edit_replays_same_idempotency_key`
  - `test_account_risk_replay_does_not_double_count_capacity`
  - `test_probability_edit_http_replay_preserves_order_risk_and_journal_state`
- market mutation:
  - unconditional acceptance mutates `MARKETS[market_id]["marginals"]`
  - conditional acceptance leaves unconditional market marginals unchanged and writes `CONDITIONAL_MARGINALS`
- brute-force / invariant agreement:
  - `test_invariant_probability_edit_matches_bruteforce_reference_on_tiny_nets`
  - `test_invariant_repeated_probability_edits_match_bruteforce_reference_on_same_slice`

### 3. Property coverage already stresses the unconditional guard and distribution invariants

The property block already checks:

- unconditional acceptance at non-negative headroom
- unconditional rejection at negative headroom without side effects
- zero-headroom acceptance and immediate follow-up rejection behavior
- preservation of valid marginal distributions
- `impactScore == kl_divergence(previousMarginals, newMarginals)` for accepted unconditional edits

So the branch does not appear to need new production logic to satisfy the task description.

## Coverage Gaps Worth Tightening

I do not see a missing backend feature here. The remaining opportunity is clarity and regression hardness.

The current gaps are mostly about how the coverage is distributed:

1. The unconditional path is covered across many tests, but not in one clearly named regression cluster tied to T549.
2. The brute-force invariant tests mix unconditional and contextual scenarios, so the unconditional guarantee is partly implicit rather than isolated.
3. The replay tests prove that idempotency works, but the most valuable invariant for this task is specifically "replay does not re-mutate unconditional market state or append journal state."

## Recommended Implementation Plan

1. Keep the change set test-only in `tests/test_bayes_market_api.py`.

2. Tighten the direct unconditional regression tests around one empty-context happy path:
   - assert preview/order/market alignment for `previousMarginals`, `newMarginals`, and `impactScore`
   - assert accepted empty-context writes land only in `MARKETS[market_id]["marginals"]`
   - assert `CONDITIONAL_MARGINALS` stays unchanged on that path

3. Strengthen the unconditional idempotent replay assertions:
   - snapshot market marginals, account risk, and event chain after first acceptance
   - replay the same idempotent empty-context request
   - assert no second order, no second event, no further market mutation, and unchanged risk/journal state

4. Make the unconditional market-mutation boundary more explicit:
   - preserve the existing conditional-vs-unconditional split assertions
   - if needed, add a focused regression that performs one unconditional edit and one conditional edit on the same market and proves only the unconditional edit changes top-level market marginals

5. Isolate unconditional brute-force agreement more explicitly:
   - either split the existing mixed invariant test into unconditional and contextual variants
   - or add a dedicated unconditional-only invariant test that compares accepted empty-context edits against the brute-force reference over repeated steps

6. Re-run the targeted suite:
   - `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'`

## Recommended Scope Guardrails

- Avoid changing `preview_unconditional_probability_edit(...)`, `handle_probability_edit(...)`, or `create_probability_edit_order(...)` unless a new failing test proves a real behavioral bug.
- Avoid broad renames or test-harness refactors; the main value here is pinning behavior, not reorganizing the entire suite.
- Keep contextual behavior in scope only where it sharpens the unconditional boundary.

## Verification Baseline

Ran:

- `python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'`

Result:

- `Ran 147 tests in 4.996s`
- `OK`
