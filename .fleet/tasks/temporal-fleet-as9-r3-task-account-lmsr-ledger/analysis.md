# task-account-lmsr-ledger

## Summary

`backend/lmsr.py` now exposes deterministic LMSR quote primitives, but `backend/server.py` still persists account state as a scalar compatibility model in `ACCOUNT_RISK`. This task should extend storage so each accepted `ProbabilityEdit` records additive LMSR state keyed by market plus normalized context while preserving the existing `minAsset` and `capacityIndicators` read model until later GS work replaces the scalar projection.

## What Exists Today

- `ensure_account_risk_state(...)` initializes only:
  - `accountId`
  - `riskLimit`
  - `minAsset`
  - `updatedAt`
  - `markets`
- `sync_account_risk_state(order)` debits `order["impactScore"]` from overall and per-market `minAsset`.
- `get_account_risk(...)` serializes only those scalar fields.
- `create_probability_edit_order(...)` already stores enough deterministic inputs to build an LMSR ledger entry later:
  - `marketId`
  - `payload.variableId`
  - `payload.context`
  - `previousMarginals`
  - `newMarginals`
  - `filledAt`
  - `commandId`
  - `id`
- `backend/lmsr.py` can already derive:
  - `score_delta = b * ln(updated / previous)`
  - scalar LMSR cost from the same marginals and `market["liquidity"]`
- Tests are tightly coupled to raw `ACCOUNT_RISK` shape. Several rejection/replay cases assert exact dict equality for seeded accounts, so any additive internal fields must be initialized deterministically everywhere.

## Recommended Storage Boundary

Keep the existing account root fields as compatibility/read-model state, but add a dedicated internal LMSR block. A safe shape is:

```python
{
    "accountId": "acct_123",
    "riskLimit": 100.0,
    "minAsset": 97.5,
    "updatedAt": "2026-04-08T00:00:00Z",
    "markets": {...},
    "lmsrState": {
        "version": "lmsr-ledger-v1",
        "riskReadModel": "scalar-min-asset-v1",
        "slices": {
            "m1|": {
                "marketId": "m1",
                "variableId": "eth_price_gt_3000_mar15",
                "context": [],
                "contextKey": "",
                "liquidity": 100000.0,
                "scoreByOutcome": {
                    "yes": 123.4,
                    "no": -45.6,
                },
                "commandCount": 1,
                "updatedAt": "2026-04-08T00:00:00Z",
                "lastOrderId": "ord_1",
                "lastCommandId": "cmd_1",
            }
        },
    },
}
```

Important details:

- Key slices by `marketId + normalized context_state_key(context)` so unconditional and each conditional book are isolated.
- Persist cumulative `scoreByOutcome`, not just the last delta. The deltas are additive and replay-stable, which is what later GS work needs.
- Keep `riskLimit`, `minAsset`, and per-market `markets[...]` as explicit compatibility projection fields for now; do not force `/v1/accounts/{id}/risk` to read from LMSR state yet.
- Add a small versioned metadata block such as `version` and `riskReadModel` so later GS work can switch the scalar projection source without another ambiguous storage migration.

## Why This Task Can Land Before Cost Integration

This task does not need to wait for `order["impactScore"]` to become LMSR-backed.

`create_probability_edit_order(...)` already stores `previousMarginals` and `newMarginals`, and the repo already has `backend/lmsr.py`. The ledger path can therefore derive `scoreByOutcome` from the order's actual marginal transition and `market["liquidity"]` while the existing scalar read model continues to use the legacy `impactScore` placeholder until `task-probability-edit-cost-integration` lands.

That separation is useful because it lets the repo start persisting deterministic LMSR account state now without reopening the current HTTP/event contract or prematurely changing rejection math.

## Implementation Plan

1. Add account-state builder helpers in `backend/server.py` so default accounts and test seed accounts initialize the new LMSR block consistently.
2. Add a deterministic ledger-bucket helper keyed by `marketId` and normalized `context_state_key(context)`.
3. Teach `sync_account_risk_state(...)` or a split helper it calls to:
   - keep updating legacy scalar `minAsset` and `markets` fields exactly as today
   - for `ProbabilityEdit` orders, compute `scoreByOutcome` from `order["previousMarginals"]`, `order["newMarginals"]`, and `MARKETS[market_id]["liquidity"]`
   - accumulate that delta into the correct LMSR slice
   - stamp `updatedAt`, `commandCount`, `lastOrderId`, and `lastCommandId`
4. Leave `get_account_risk(...)` shape unchanged; it should continue to project the legacy scalar fields until T559.
5. Ensure rejected submissions and idempotent replays do not create or double-apply LMSR ledger entries.

## Test Plan

- Update seed helpers in `tests/test_bayes_market_api.py` to build the enriched account shape instead of hand-writing the old dict.
- Add focused unit/integration assertions that accepted unconditional edits create one LMSR slice with cumulative `scoreByOutcome`.
- Add the same coverage for conditional edits, proving slice keys use normalized context and do not collapse into the unconditional book.
- Add replay tests that repeated idempotent acceptance does not double-count the LMSR slice.
- Keep existing `/v1/accounts/{id}/risk`, rejection, and terminal-event assertions intact.

## Risks And Open Questions

- Direct test equality against raw `ACCOUNT_RISK` means the new fields must be present in every seeded/baseline account shape, or those tests will fail noisily.
- The ledger update must use `order` data, not current market state, otherwise replay or later market mutations could make the persisted LMSR state non-deterministic.
- `lmsr_score_delta(...)` requires strictly positive probabilities. Current active-market marginals and `ProbabilityEdit` validation appear to satisfy that, but the ledger helper should still fail loudly if a future caller passes zero-mass inputs.
- `EventTrade` does not participate in this ledger. The task should keep that separation explicit instead of creating a partial mixed-mode asset store.
