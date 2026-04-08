# T563 Journal Read Surface Freeze

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-z0o-r1-bayes-t563-audit-journal-read-surface`

## Question

Does `apps/bayes-market/backend/server.py` already emit per-market `seq`, `prevEventHash`, and `eventHash`, and if so, what exact HTTP response contract should be frozen for `GET /v1/markets/{id}/events`?

## Findings

### 1. The journal write-path already exists in the restored backend

The current backend already materializes canonical Bayes commands and terminal Bayes events in memory:

- `COMMANDS`, `EVENTS`, `MARKET_EVENT_SEQUENCES`, `LAST_EVENT_HASHES`, and `GENESIS_EVENT_HASH` are defined as process state in [`apps/bayes-market/backend/server.py`](../backend/server.py).
- `emit_terminal_event(...)` in [`apps/bayes-market/backend/server.py`](../backend/server.py) assigns:
  - `seq = MARKET_EVENT_SEQUENCES.get(market_id, 0) + 1`
  - `prevEventHash = LAST_EVENT_HASHES.get(market_id, GENESIS_EVENT_HASH)`
  - `eventHash = canonical_json_hash(event)`
- The same function then updates the per-market chain head:
  - `MARKET_EVENT_SEQUENCES[market_id] = seq`
  - `LAST_EVENT_HASHES[market_id] = event["eventHash"]`
  - `EVENTS[eventId] = deepcopy(event)`

That means the current write path already emits the three fields this task is concerned with:

- `seq`
- `prevEventHash`
- `eventHash`

and it does so per market, not globally.

### 2. The read endpoint is the missing piece

The current router and service index expose:

- `GET /v1/markets`
- `GET /v1/markets/{id}`
- `POST /v1/markets/{id}/orders/probability-edit`
- `GET /v1/accounts/{id}/risk`

There is no current branch in `route_request(...)` for `GET /v1/markets/{id}/events`, and [`apps/bayes-market/backend/server.py`](../backend/server.py) does not advertise that route from `service_index_payload()`.

### 3. The existing tests only partially prove the journal shape

[`tests/test_bayes_market_api.py`](../../../tests/test_bayes_market_api.py) already proves that a successful ProbabilityEdit write emits a Bayes event and that the first event on a market has `seq == 1`.

What is not yet frozen in tests is the read-side contract:

- fresh-market response shape
- event ordering
- chain-head fields
- pagination fields
- page semantics when the market has more events than the requested `limit`

## Verified Runtime Behavior

A local runtime probe against the current `server.py` confirmed:

- two writes to `m1` produce `seq` values `1`, then `2`
- the first `m1` event uses `prevEventHash = GENESIS_EVENT_HASH`
- the second `m1` event uses `prevEventHash = first.eventHash`
- a first write to `m2` starts at `seq = 1` and also uses `GENESIS_EVENT_HASH`
- `LAST_EVENT_HASHES` and `MARKET_EVENT_SEQUENCES` track `m1` and `m2` independently

This matches the intended per-market shard semantics from [`apps/bayes-market/docs/t544-event-sourcing-contract.md`](t544-event-sourcing-contract.md).

## Frozen Read Contract

Freeze the read endpoint as:

- `GET /v1/markets/{id}/events`

### Query parameters

- `fromSeq` optional, integer, inclusive lower bound, default `1`
- `limit` optional, integer, default `100`, max `100`

Validation rules:

- `fromSeq` must be an integer `>= 1`
- `limit` must be an integer `>= 1` and `<= 100`
- unknown `market_id` returns `404 market_not_found`
- non-`GET` methods on this resource return `405 method_not_allowed`
- malformed `fromSeq` or `limit` returns `400 invalid_query`

### Ordering rules

- `events` are always sorted by `seq` ascending
- `fromSeq` is inclusive
- pagination is sequence-based, not opaque-cursor-based
- `chain` always describes the current market head, not just the returned page tail

### Event item contract

Each returned item must be the canonical stored Bayes event envelope, preserving the current write-path shape:

```json
{
  "schemaVersion": "bayes-event/v1",
  "eventId": "evt_01J...",
  "marketId": "m1",
  "seq": 1,
  "commandId": "cmd_01J...",
  "eventType": "CommandAccepted",
  "emittedAt": "2026-04-05T00:00:00Z",
  "approxFlag": false,
  "payload": {},
  "prevEventHash": "sha256:...",
  "eventHash": "sha256:..."
}
```

No event fields should be renamed or wrapped on the read surface.

### Response envelope

Freeze the success response shape as:

```json
{
  "marketId": "m1",
  "events": [],
  "chain": {
    "genesisHash": "sha256:...",
    "headSeq": 0,
    "headHash": "sha256:..."
  },
  "pagination": {
    "fromSeq": 1,
    "limit": 100,
    "returned": 0,
    "nextFromSeq": null
  },
  "meta": {
    "timestamp": "2026-04-05T00:00:00Z"
  }
}
```

### Chain fields

- `chain.genesisHash`
  - always equals `GENESIS_EVENT_HASH`
- `chain.headSeq`
  - `0` for a market with no events
  - otherwise the value in `MARKET_EVENT_SEQUENCES[market_id]`
- `chain.headHash`
  - `GENESIS_EVENT_HASH` for a market with no events
  - otherwise the value in `LAST_EVENT_HASHES[market_id]`

This gives callers a stable head even when the returned page is empty or partial.

### Pagination fields

- `pagination.fromSeq`
  - the inclusive request lower bound after defaults are applied
- `pagination.limit`
  - the effective page size after defaults are applied
- `pagination.returned`
  - `len(events)` in the current response page
- `pagination.nextFromSeq`
  - `null` when there is no later page
  - otherwise the next unread sequence number

`nextFromSeq` is computed from the current page tail, not from opaque state. If the last returned event has `seq = 25`, the next page starts at `26`.

## Fresh Market Example

For an existing market that has emitted no terminal events yet:

```json
{
  "marketId": "m1",
  "events": [],
  "chain": {
    "genesisHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "headSeq": 0,
    "headHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  "pagination": {
    "fromSeq": 1,
    "limit": 100,
    "returned": 0,
    "nextFromSeq": null
  },
  "meta": {
    "timestamp": "2026-04-05T00:00:00Z"
  }
}
```

Key point: empty journal is not the same as unknown market. Existing market + zero events must still return `200` with a verifiable genesis head.

## Populated Market Example

For a market with two stored terminal events and a default request of `GET /v1/markets/m1/events`:

```json
{
  "marketId": "m1",
  "events": [
    {
      "schemaVersion": "bayes-event/v1",
      "eventId": "evt_20260405_000001",
      "marketId": "m1",
      "seq": 1,
      "commandId": "cmd_20260405_000001",
      "eventType": "CommandAccepted",
      "emittedAt": "2026-04-05T00:00:00Z",
      "approxFlag": false,
      "payload": {},
      "prevEventHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "eventHash": "sha256:a97af3508182ba3e18b5fbb0b6138a7998d785bdcad33ef1b0c86af1f839341e"
    },
    {
      "schemaVersion": "bayes-event/v1",
      "eventId": "evt_20260405_000002",
      "marketId": "m1",
      "seq": 2,
      "commandId": "cmd_20260405_000002",
      "eventType": "CommandAccepted",
      "emittedAt": "2026-04-05T00:00:01Z",
      "approxFlag": false,
      "payload": {},
      "prevEventHash": "sha256:a97af3508182ba3e18b5fbb0b6138a7998d785bdcad33ef1b0c86af1f839341e",
      "eventHash": "sha256:ee3df7eadae1c5f7a66e5380dbece1a226bc83b797d6a207eadee472b0d6360c"
    }
  ],
  "chain": {
    "genesisHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "headSeq": 2,
    "headHash": "sha256:ee3df7eadae1c5f7a66e5380dbece1a226bc83b797d6a207eadee472b0d6360c"
  },
  "pagination": {
    "fromSeq": 1,
    "limit": 100,
    "returned": 2,
    "nextFromSeq": null
  },
  "meta": {
    "timestamp": "2026-04-05T00:00:01Z"
  }
}
```

The important invariant is:

- `events[n].prevEventHash == events[n-1].eventHash`
- `chain.headSeq == events[-1].seq` when the page reaches the market head
- `chain.headHash == events[-1].eventHash` when the page reaches the market head

## Paginated Example

For `GET /v1/markets/m1/events?fromSeq=1&limit=1` against the same two-event market:

```json
{
  "marketId": "m1",
  "events": [
    {
      "seq": 1,
      "prevEventHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "eventHash": "sha256:a97af3508182ba3e18b5fbb0b6138a7998d785bdcad33ef1b0c86af1f839341e"
    }
  ],
  "chain": {
    "genesisHash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "headSeq": 2,
    "headHash": "sha256:ee3df7eadae1c5f7a66e5380dbece1a226bc83b797d6a207eadee472b0d6360c"
  },
  "pagination": {
    "fromSeq": 1,
    "limit": 1,
    "returned": 1,
    "nextFromSeq": 2
  },
  "meta": {
    "timestamp": "2026-04-05T00:00:01Z"
  }
}
```

This freezes one important distinction:

- `pagination.nextFromSeq` points to the next unread event
- `chain.headSeq` and `chain.headHash` point to the current market head

They are intentionally not the same field.

## Bottom Line

The existing Bayes backend already writes a per-market append-only hash chain with `seq`, `prevEventHash`, and `eventHash`. The task that remains is strictly read-side: expose that existing chain through `GET /v1/markets/{id}/events` with canonical event envelopes, market-head metadata, and simple sequence-based pagination.
