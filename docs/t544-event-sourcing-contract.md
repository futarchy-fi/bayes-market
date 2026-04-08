# T544 — Bayes Event-Sourcing Contract (commands / events / snapshots)

Status: draft v1 (canonical)  
Scope: deterministic replay contract for Bayes MVP

## 1) Purpose

Define strict wire/storage contracts for:

- command envelope (ingress intent)
- event envelope (accepted/rejected outcomes)
- snapshot envelope (state checkpoints)

These contracts are designed so replay from `snapshot + ordered events` is deterministic and auditable.

---

## 2) Contract IDs

- Command envelope: `bayes-command/v1`
- Event envelope: `bayes-event/v1`
- Snapshot envelope: `bayes-snapshot/v1`
- Replay hash profile: `bayes-replay-hash/v1`

All persisted records MUST carry `schemaVersion` equal to one of these IDs.

---

## 3) Command Envelope (`bayes-command/v1`)

```json
{
  "schemaVersion": "bayes-command/v1",
  "commandId": "cmd_01J...",
  "marketId": "market_demo_001",
  "accountId": "acct_abc",
  "commandType": "ProbabilityEdit",
  "idempotencyKey": "optional-client-key",
  "submittedAt": "2026-02-26T00:00:00Z",
  "payload": {},
  "meta": {
    "source": "api",
    "ipHash": "sha256:...",
    "userAgent": "..."
  }
}
```

### Required fields

- `schemaVersion`
- `commandId` (globally unique)
- `marketId`
- `accountId`
- `commandType` (`ProbabilityEdit | EventTrade | AdminOp`)
- `submittedAt` (ISO-8601 UTC)
- `payload` (command-specific object)

### Command payload variants

## 3.1 `ProbabilityEdit`

```json
{
  "variableId": "ai_policy_passes_2027",
  "target": { "kind": "marginal", "outcomeId": "yes", "probability": 0.63 },
  "context": []
}
```

- `context` holds conditional assignments (empty for unconditional edits).

## 3.2 `EventTrade`

```json
{
  "formula": [
    [
      { "variableId": "m1", "outcomeId": "yes", "negated": false }
    ]
  ],
  "size": 12.5,
  "side": "buy"
}
```

- Canonical payload shape is nested-array CNF: `list[list[{variableId,outcomeId,negated}]]`.
- This document freezes the materialized command payload as stored/returned by the current server, so `formula[*][*].variableId` is the public market id (for example `m1`), not the internal `market["variableId"]`.
- During shared validation, the server temporarily translates those market ids to internal variable ids, validates outcomes/structure, then restores market ids before persisting the command payload.
- Structurally invalid formulas fail validation with `400 invalid_event_formula`.
- Structurally valid but currently unsupported non-atomic CNF remains schema-valid and is rejected later with `501 event_trade_inference_unavailable`.
- Current executable subset is exactly one clause containing one non-negated literal.
- The older `{"kind":"CNF","expr":"..."}` representation is obsolete for the live checkout.

## 3.3 `AdminOp`

Reserved for deterministic operator actions (e.g., market freeze) and must be explicitly whitelisted.

---

## 4) Event Envelope (`bayes-event/v1`)

Every sequenced command emits exactly one terminal event:

- `CommandAccepted`
- `CommandRejected`

Optional intermediate engine events may be emitted but must not replace the terminal event.

```json
{
  "schemaVersion": "bayes-event/v1",
  "eventId": "evt_01J...",
  "marketId": "market_demo_001",
  "seq": 1042,
  "commandId": "cmd_01J...",
  "eventType": "CommandAccepted",
  "emittedAt": "2026-02-26T00:00:01Z",
  "approxFlag": false,
  "payload": {},
  "prevEventHash": "sha256:...",
  "eventHash": "sha256:..."
}
```

### Required fields

- `schemaVersion`
- `eventId` (globally unique)
- `marketId`
- `seq` (strictly increasing integer per market shard)
- `commandId`
- `eventType`
- `emittedAt` (ISO-8601 UTC)
- `payload`
- `prevEventHash`
- `eventHash`

### `CommandAccepted` payload

```json
{
  "effects": {
    "marginalDelta": [{ "variableId": "ai_policy_passes_2027", "before": 0.58, "after": 0.63 }],
    "assetDelta": [{ "accountId": "acct_abc", "beforeMinAsset": 3.20, "afterMinAsset": 2.91 }]
  },
  "pricing": { "cost": 1.74, "fee": 0.02 },
  "replayStateHash": "sha256:..."
}
```

### `CommandRejected` payload

```json
{
  "reasonCode": "min_asset_violation",
  "reason": "Edit would produce negative state-contingent assets",
  "retryHint": "reduce probability target"
}
```

---

## 5) Snapshot Envelope (`bayes-snapshot/v1`)

```json
{
  "schemaVersion": "bayes-snapshot/v1",
  "snapshotId": "snp_01J...",
  "marketId": "market_demo_001",
  "seq": 1000,
  "takenAt": "2026-02-26T00:10:00Z",
  "state": {
    "bnFactors": {},
    "marginals": {},
    "assets": {},
    "engineMode": "EXACT"
  },
  "stateHash": "sha256:...",
  "lastEventHash": "sha256:...",
  "replayHashProfile": "bayes-replay-hash/v1"
}
```

### Required fields

- `schemaVersion`
- `snapshotId`
- `marketId`
- `seq` (last included event sequence)
- `takenAt` (ISO-8601 UTC)
- `state`
- `stateHash`
- `lastEventHash`
- `replayHashProfile`

---

## 6) Determinism Rules (MUST)

1. **Single writer per market shard**: only sequencer assigns `seq`.
2. **Total ordering**: replay applies events strictly by `seq` ascending.
3. **Idempotent ingest**: duplicate `commandId` returns prior terminal event outcome.
4. **Terminal event guarantee**: each accepted command path emits exactly one terminal event record.
5. **Hash-chain integrity**:
   - `prevEventHash` equals previous event’s `eventHash` (same market).
   - `eventHash` computed from canonical JSON serialization under `bayes-replay-hash/v1`.
6. **Snapshot continuity**:
   - snapshot `lastEventHash` must match event at snapshot `seq`.
7. **No wall-clock dependence in transition logic**:
   - timestamps are metadata only; state transitions use command payload + prior state + deterministic config.

---

## 7) Versioning Policy

## 7.1 Backward-compatible changes (same v1)

Allowed:
- add optional fields
- add optional event payload subfields
- add non-breaking reason codes

Forbidden in v1:
- rename/remove required fields
- change required field types
- change hash canonicalization algorithm

## 7.2 Breaking changes

Any breaking change requires new contract ID:
- `bayes-command/v2`
- `bayes-event/v2`
- `bayes-snapshot/v2`

Migration rule:
- mixed-version replay in one stream is disallowed unless explicit converter is version-pinned and audited.

---

## 8) Canonical Serialization / Hash Profile (`bayes-replay-hash/v1`)

Hash inputs use canonical JSON:

- UTF-8 encoding
- lexicographically sorted object keys
- no insignificant whitespace
- numbers serialized in normalized decimal form
- hash algorithm: `sha256`
- encoded as `sha256:<hex>`

Objects hashed:
- event envelope minus `eventHash` field (for computing `eventHash`)
- snapshot `state` object (for `stateHash`)

---

## 9) Storage Index Requirements

Minimum DB indexes for replay and audit:

- events: `(marketId, seq)` unique
- events: `commandId` unique per market
- snapshots: `(marketId, seq)` unique
- snapshots: `snapshotId` unique

---

## 10) Acceptance Checkpoints for T544

- [ ] Command/event/snapshot envelopes documented with required fields
- [ ] Determinism rules explicitly listed (single-writer, total order, idempotency, hash-chain)
- [ ] Versioning policy defined (non-breaking vs breaking)
- [ ] Hash profile documented for replay reproducibility
- [ ] Storage index requirements specified for implementation handoff

---

## 11) Implementation handoff notes

This document is the contract reference for:
- T545 (deterministic replay hash strategy)
- T562/T563/T564/T565 (sequencer, journal, snapshot, replay)
- T568+ API contract tasks consuming command/event metadata
- T547/T570 EventTrade payload and route behavior; see `t547-shared-event-formula-contract-freeze.md` for the validator-specific freeze behind this persisted command shape

Any deviation from these contracts must be recorded with:
1) explicit rationale, 2) impacted tasks, 3) migration strategy, 4) new contract version if breaking.
