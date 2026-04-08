# T556 Scope And Compatibility Boundary Freeze

Date: 2026-04-08
Branch: `ff/Ttemporal-fleet-as9-r1-analysis-scope-and-contract`

## Question

Freeze three decisions for T556:

1. Resolve the wording gap between the task title shorthand ("LMSR cost function") and the epic wording (`Implement per-user asset model transformation (Sx = b ln q(x))`).
2. Confirm whether the existing HTTP, event, and risk envelopes stay stable while the asset math is migrated.
3. Lock the source of the LMSR liquidity parameter `b`.

## Findings

### 1. The epic already places T556 on the risk/solvency path, not on the public API surface

The current planning docs consistently place T556 inside the internal solvency engine work:

- `docs/t537-epic-execution-baseline.md` defines T556 as `Implement per-user asset model transformation (Sx = b ln q(x))`.
- `docs/t538-scope-matrix.md` groups T556 with T557, T558, T559, and T561 under `Risk/solvency`.
- `docs/t539-mvp-launch-gate.md` puts T556 under the solvency gate whose acceptance criterion is that no accepted command can make user min-assets negative.

That grouping matters. It means T556 is not the task that owns public request/response redesign, event-version changes, or a new market schema. It owns the internal asset-model replacement that later solvency checks depend on.

### 2. "LMSR cost function" and "per-user asset model transformation" describe the same seam from different sides

The title wording focuses on the mechanism: an LMSR-style cost/asset model with liquidity parameter `b`.

The epic wording focuses on the state representation that mechanism produces: a per-user asset transformation `Sx = b ln q(x)`.

Those are not competing scopes. They are two views of the same internal migration:

- the engine side introduces LMSR-backed cost/asset math
- the state side uses that math to transform and maintain the user's asset state

The safe interpretation is therefore:

- T556 owns the internal math/state transition layer
- T557 owns the unconditional pre-acceptance guard
- T558 owns conditional admissible-range logic
- T559 owns the GS minimum-assets path
- T561 owns rejection-reason and guidance policy

So T556 should supply the asset primitives those tasks consume, not absorb their public-contract work.

### 3. The checked-in server already has stable public envelopes that the migration should preserve

The current branch already exposes and tests a coherent compatibility boundary:

- ProbabilityEdit HTTP requests use the thin market-scoped REST body, not a client-supplied `bayes-command/v1` envelope.
- Accepted ProbabilityEdit writes return `201` with an order/result response model.
- Unconditional solvency failures return `409` with `error/result/meta` and `min_asset_violation`.
- Terminal events are persisted and read back as `bayes-event/v1` envelopes with `CommandAccepted` or `CommandRejected`.
- `GET /v1/accounts/{id}/risk` exposes a stable read model with `minAssets` and `capacityIndicators`.

Evidence in the live checkout:

- `backend/server.py`
  - `build_terminal_acceptance_response(...)`
  - `build_terminal_rejection_response(...)`
  - `emit_terminal_event(...)`
  - `get_account_risk(...)`
- `tests/test_bayes_market_api.py`
  - market-scoped ProbabilityEdit HTTP coverage
  - journal-chain coverage
  - read-after-write risk coverage
  - unconditional solvency rejection coverage

Verification run on this branch:

```bash
python3 -m unittest discover -s tests
```

Result:

```text
Ran 135 tests in 4.382s

OK
```

So the migration boundary is already test-anchored. T556 should change the internal asset math behind these surfaces, not redefine the surfaces.

### 4. The current placeholder solvency seam is intentionally temporary and points directly at T556/T559

`docs/t557-unconditional-solvency-contract-freeze.md` is explicit that the current placeholder account-risk model is not the final asset engine and is only frozen until `T556`/`T559` replace the math.

That document already freezes an important compatibility principle:

- the pre-acceptance rejection boundary is stable
- the public rejection code and payload shape are stable
- the current implementation seam is temporary

This is strong evidence that T556 is supposed to replace the underlying asset computation without reopening the surrounding HTTP/event/risk contracts.

### 5. `market.liquidity` is the only existing market-level parameter that fits LMSR `b` without widening the contract

In the checked-in backend:

- every market record already carries numeric `liquidity`
- `GET /v1/markets` includes `liquidity` in the summary shape
- `GET /v1/markets/{id}` returns the full market object, which also includes `liquidity`
- there is no parallel `b`, `lmsrB`, `costFunction`, or `liquidityParameter` field anywhere in the current market schema

At the same time, the current ProbabilityEdit placeholder math does not consume `market.liquidity`; it uses KL-divergence-based `impactScore` and account-level min-asset bookkeeping.

That makes the migration choice straightforward:

- if T556 needs a per-market LMSR depth parameter, the stable in-tree slot for it is `market.liquidity`
- adding a second parameter field would be a public schema expansion with no current need
- renaming `liquidity` to `b` would be a breaking read-contract change

So the compatibility-safe decision is to freeze:

```text
market.liquidity == LMSR b
```

internally, while keeping the public field name and JSON placement unchanged.

### 6. The external read models should remain summaries even if the internal asset state becomes richer

The epic wording implies a richer per-user asset representation than the current placeholder scalar capacity model.

But the current public read surfaces do not expose a full per-state asset vector. They expose summaries:

- acceptance events publish `assetDelta` entries with `beforeMinAsset` and `afterMinAsset`
- rejection responses publish preview scalars such as `beforeMinAsset`, `impactScore`, and `afterMinAsset`
- the account risk endpoint publishes `minAssets.overall`, per-market `minAsset`, and `capacityIndicators`

That summary boundary should remain intact during T556. A richer internal asset representation is compatible with the current public contracts as long as the server still projects it back to the same scalar min-asset summaries.

## Freeze Decision

Freeze T556 as an internal asset-engine migration with a strict compatibility boundary:

### 1. Scope

T556 is the task that replaces the placeholder asset/cost math with the LMSR-backed per-user asset transformation described in the epic.

It should be read as:

- implementing the internal asset representation and update rule
- providing the math used by later solvency checks and previews
- keeping the surrounding public API/event/read-model contracts stable

It should not be read as:

- a public HTTP contract rewrite
- an event-schema version bump
- a risk-endpoint redesign
- an EventTrade formula-contract rewrite
- a new market-schema expansion for a separate `b` field

### 2. Compatibility Boundary

During the T556 migration, keep these surfaces stable:

- `POST /v1/markets/{id}/orders/probability-edit` request shape
- ProbabilityEdit acceptance status/result envelope
- ProbabilityEdit rejection status/code/result envelope
- `bayes-event/v1` terminal event envelope shape and event types
- `CommandRejected.reasonCode = "min_asset_violation"` for the existing unconditional solvency path
- `GET /v1/accounts/{id}/risk` response envelope and key names
- market list/detail field names, including `liquidity`

Internal formulas, stored asset state, and how min-asset summaries are derived may change behind that boundary.

### 3. LMSR Parameter Freeze

Freeze `market.liquidity` as the LMSR liquidity parameter `b`.

Implementation consequence:

- T556 should read `market.liquidity` as the internal `b` input
- T556 should not introduce a second market parameter carrying the same meaning
- T556 should not rename the public field from `liquidity` to `b`

## Consequence

This resolves the wording gap as follows:

- the task-title shorthand "LMSR cost function" names the internal mechanism
- the epic wording "per-user asset model transformation" names the state model produced by that mechanism

For implementation planning, treat T556 as the internal math/state foundation for the solvency stack, with no public envelope changes required.

That keeps T556 aligned with:

- T557/T558/T559/T561 as follow-on solvency contracts
- the existing market-scoped HTTP boundary
- the frozen event/journal surfaces
- the current account-risk read model
- the already-published `market.liquidity` field as the single LMSR depth knob
