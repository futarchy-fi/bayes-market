# T1737 ProbabilityEdit HTTP Contract Freeze

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-d6g-r4-bayes-t1737-freeze-http-command-boundary`

## Question

For `POST /v1/markets/{id}/orders/probability-edit`, should the public HTTP route accept the full canonical `bayes-command/v1` envelope, or should it accept a thinner REST body and let the server construct the canonical command envelope internally?

## Decision

Freeze the public HTTP contract as a **thin REST body**, not the full `bayes-command/v1` envelope.

`bayes-command/v1` remains the canonical ingest and persistence contract, but it should be materialized **behind** the HTTP boundary by the route handler before the command reaches the sequencer/journal layer.

At the public boundary, the request body is the ProbabilityEdit payload plus route-local request metadata:

- required `accountId`
- optional `idempotencyKey`
- `variableId`
- `target`
- `context`

## Why This Is The Right Boundary

### 1. The restored route already behaves like a thin REST endpoint

The current restored handler validates the ProbabilityEdit payload fields, requires a top-level `accountId`, accepts an optional top-level `idempotencyKey`, and still does not read `schemaVersion`, `commandId`, `marketId`, `commandType`, or `submittedAt` from the request body.

Evidence:

- [`apps/bayes-market/backend/server.py`](../backend/server.py) validates `variableId`, `target`, and `context` from the request payload and derives command metadata internally.
- [`apps/bayes-market/backend/server.py`](../backend/server.py) requires `accountId`, accepts optional `idempotencyKey`, and generates `commandId` and `submittedAt` server-side.
- [`tests/test_bayes_market_api.py`](../../../tests/test_bayes_market_api.py) sends only `accountId`, optional `idempotencyKey`, `variableId`, `target`, and `context`.

### 2. The canonical Bayes command envelope is broader than the HTTP payload

The event-sourcing contract defines `bayes-command/v1` as the canonical command envelope with metadata required for deterministic ingest and replay: `schemaVersion`, `commandId`, `marketId`, `accountId`, `commandType`, `submittedAt`, and `payload`.

Evidence:

- [`apps/bayes-market/docs/t544-event-sourcing-contract.md`](t544-event-sourcing-contract.md) defines the envelope.
- [`apps/bayes-market/docs/t544-event-sourcing-contract.md`](t544-event-sourcing-contract.md) lists the required fields.
- [`apps/bayes-market/docs/t544-event-sourcing-contract.md`](t544-event-sourcing-contract.md) defines the ProbabilityEdit payload as the `payload` sub-object, not as the whole envelope.

### 3. The planning docs separate payload schemas from persistence contracts

The Bayes planning docs describe command work in two layers:

- payload schemas for ProbabilityEdit/EventTrade
- event-sourcing persistence contracts for commands/events/snapshots

That split is consistent with a thin HTTP payload that is wrapped into `bayes-command/v1` internally.

Evidence:

- [`apps/bayes-market/docs/t538-scope-matrix.md`](t538-scope-matrix.md) calls out "ProbabilityEdit and EventTrade payload schemas".
- [`apps/bayes-market/docs/t538-scope-matrix.md`](t538-scope-matrix.md) separately calls out the event-sourced journal/snapshot/replay contract.
- [`apps/bayes-market/docs/t537-epic-execution-baseline.md`](t537-epic-execution-baseline.md) splits T544 from T546.

### 4. The branch history shows the full-envelope HTTP route was superseded

`task/T569` required the full `bayes-command/v1` envelope on the HTTP route, including body `marketId` matching the path. The later `task/T1736` alignment removed that requirement and changed the route to accept the thinner payload body that is restored on this branch.

That makes `task/T1736`, not `task/T569`, the last explicit decision point for the public HTTP boundary.

More precisely:

- `task/T569` treated the HTTP request as the canonical command envelope and rejected requests missing `schemaVersion`, `commandId`, `marketId`, `accountId`, `commandType`, `submittedAt`, or `payload`.
- `task/T1736` switched the public route to a market-scoped body, reading `marketId` from the path and `payload` fields directly from the JSON body.
- the restored stub on this branch keeps the T1736 thin-body boundary and tightens `accountId` from a T1736 defaulted field to an explicitly required client-supplied field.

### 5. The response contract is REST submission state, not the canonical envelope

The restored route returns `201` with `{order, meta}` where `order` is an execution-facing submission record. It does not return the raw `bayes-command/v1` envelope.

Evidence:

- [`apps/bayes-market/backend/server.py`](../backend/server.py) builds an `order` object containing execution details such as `previousMarginals`, `newMarginals`, `impactScore`, `createdAt`, and `filledAt`.
- [`apps/bayes-market/backend/server.py`](../backend/server.py) wraps that order in `{"order": ..., "meta": ...}`.
- [`tests/test_bayes_market_api.py`](../../../tests/test_bayes_market_api.py) asserts `payload["order"]`, `payload["meta"]`, `payload["order"]["commandId"]`, `payload["order"]["submittedAt"]`, and `payload["meta"]["idempotencyKeyEcho"]`.

## Frozen Field Ownership

| Field | Public HTTP request | Internal `bayes-command/v1` | Freeze |
|---|---|---|---|
| `marketId` | Not supplied in JSON body | Server sets from `/v1/markets/{id}` path segment | **Server-generated** |
| `accountId` | Required top-level JSON field on this route | Copied into envelope `accountId` | **Client-supplied** for this MVP route |
| `commandId` | Not accepted from client | Server generates at accept time | **Server-generated** |
| `submittedAt` | Not accepted from client | Server stamps at accept time | **Server-generated** |
| `idempotencyKey` | Optional top-level JSON field | Copied into envelope if present | **Client-supplied when present** |
| `commandType` | Not supplied in JSON body | Server sets to `ProbabilityEdit` from the route | **Server-generated** |
| `schemaVersion` | Not supplied in JSON body | Server sets to `bayes-command/v1` | **Server-generated** |

## Expected Request Shape

The frozen HTTP request body should be:

```json
{
  "accountId": "acct_abc",
  "idempotencyKey": "optional-client-key",
  "variableId": "eth_price_gt_3000_mar15",
  "target": { "kind": "marginal", "outcomeId": "yes", "probability": 0.8 },
  "context": []
}
```

The server should translate that into an internal command envelope shaped like:

```json
{
  "schemaVersion": "bayes-command/v1",
  "commandId": "cmd_01J...",
  "marketId": "m1",
  "accountId": "acct_abc",
  "commandType": "ProbabilityEdit",
  "idempotencyKey": "optional-client-key",
  "submittedAt": "2026-04-05T00:00:00Z",
  "payload": {
    "variableId": "eth_price_gt_3000_mar15",
    "target": { "kind": "marginal", "outcomeId": "yes", "probability": 0.8 },
    "context": []
  }
}
```

## Expected Response Shape

Keep the current REST-style submission response shape: top-level `201` with `{order, meta}`, not a raw `bayes-command/v1` document.

The `order` object is the route response model and may include execution-facing fields beyond the canonical command envelope. On the restored stub, those fields are already part of the response contract:

```json
{
  "order": {
    "id": "ord_...",
    "type": "ProbabilityEdit",
    "marketId": "m1",
    "accountId": "acct_abc",
    "status": "filled",
    "payload": {
      "variableId": "eth_price_gt_3000_mar15",
      "target": { "kind": "marginal", "outcomeId": "yes", "probability": 0.8 },
      "context": []
    },
    "previousMarginals": { "yes": 0.65, "no": 0.35 },
    "newMarginals": { "yes": 0.8, "no": 0.2 },
    "impactScore": 0.068148,
    "commandId": "cmd_01J...",
    "submittedAt": "2026-04-05T00:00:00Z",
    "createdAt": "2026-04-05T00:00:00Z",
    "filledAt": "2026-04-05T00:00:00Z",
    "idempotencyKey": "optional-client-key"
  },
  "meta": {
    "timestamp": "2026-04-05T00:00:00Z",
    "idempotencyKeyEcho": "optional-client-key"
  }
}
```

Freeze points:

- Keep `201` with `{order, meta}` rather than returning the raw `bayes-command/v1` envelope.
- Do not make clients send command metadata just to get it echoed back.
- Surface server-generated `commandId` and `submittedAt` in the response so clients can correlate retries and downstream audit records.
- Keep `order.marketId` and `order.accountId` as echoed submission attributes in the response resource rather than as top-level canonical-envelope fields.
- If an idempotency key is supplied, echo it back in `meta.idempotencyKeyEcho`, matching the wider API convention in [`docs/ops/futarchy-web-redo/meta6/unified-endpoint-contract-spec.md`](../../../docs/ops/futarchy-web-redo/meta6/unified-endpoint-contract-spec.md).

## Why Not Revert To The Full Envelope At The HTTP Boundary

Reviving the `task/T569` full-envelope request shape would be the wrong freeze for this branch because:

1. It conflicts with the restored source and tests that currently define the route.
2. It duplicates path-scoped `marketId` in the body and reintroduces an avoidable mismatch class.
3. It exposes internal sequencing metadata (`schemaVersion`, `commandId`, `submittedAt`, `commandType`) as public request requirements even though the route already fixes or can derive them.
4. It collapses the distinction between the public REST surface and the canonical ingest contract that T544/T538 already separate.

## Current Stub Gap

The restored stub is only a **partial** implementation of the frozen contract:

- It already uses the thin request body shape.
- It now requires `accountId`, echoes optional `idempotencyKey`, and returns server-generated `commandId` and `submittedAt`.
- It still rejects any non-empty `context` instead of validating and normalizing conditional edits.
- It still does **not** materialize or persist a full internal `bayes-command/v1` envelope behind the HTTP boundary.
- It still does **not** implement idempotent retry handling or explicit terminal rejection/result semantics.

That gap is acceptable for this analysis task, but it should be treated as a follow-up implementation delta rather than as evidence that the public route should revert to the full canonical envelope.
