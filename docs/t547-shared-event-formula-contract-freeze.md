# T547 Shared Event Formula Contract Freeze

Date: 2026-04-08
Branch: `ff/Ttemporal-fleet-fhj-r1-bayes-t547-freeze-shared-event-formula-contract`

## Question

For the live checkout in `apps/bayes-market/backend/server.py`, what EventTrade formula shape and identifier semantics are canonical now, and where is the boundary between:

- structurally invalid formula payloads
- valid CNF payloads that are not yet executable by the atomic EventTrade path

## Decision

Freeze the live contract as a two-layer seam:

1. The shared EventTrade formula schema is the CNF-shaped nested array form:

```json
[
  [
    { "variableId": "btc_etf_approval_week", "outcomeId": "yes", "negated": false },
    { "variableId": "fed_rate_cut_mar_2026", "outcomeId": "no", "negated": true }
  ],
  [
    { "variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes", "negated": false }
  ]
]
```

In Python terms, that is:

```text
list[list[{variableId,outcomeId,negated}]]
```

This shared representation uses market **variable ids**, not market ids.

2. The internal/shared validator resolves each literal `variableId` against `market["variableId"]` and keeps structural failures under `invalid_event_formula`.

3. The public `POST /v1/markets/{id}/orders/event-trade` API is a route-local adapter on top of that shared validator:
   - the public payload accepts market ids in `formula[*][*].variableId`
   - the route translates those market ids to internal variable ids for validation
   - after normalization it restores market ids into the EventTrade payload/order surface

4. Broader CNF that is valid under the shared schema remains outside the current atomic EventTrade execution subset. Multi-clause CNF, multi-literal clauses, and negated literals are currently schema-valid but execution-rejected with `501 event_trade_inference_unavailable`, not `400 invalid_event_formula`.

## Current Live Contract

### 1. Shared CNF shape

`normalize_event_formula(...)` freezes the canonical shared formula representation as:

- outer array = conjunction of clauses
- each clause = non-empty array of literals
- each literal = object with:
  - required `variableId: string`
  - required `outcomeId: string`
  - optional `negated: boolean` defaulting to `false`

The current validator also freezes these limits and normalization rules:

- maximum `16` clauses
- maximum `8` literals per clause
- `variableId` and `outcomeId` are trimmed
- `negated` must be boolean when present
- duplicate literals inside a clause are rejected after normalization
- literals within a clause are returned in sorted order

### 2. Shared identifier contract

Inside the shared validator, `variableId` means the market's canonical variable identifier, not the HTTP market id.

The resolution path is:

- `normalize_event_formula(...)`
- `_resolve_market_outcome_reference(...)`
- `find_market_by_variable_id(...)`

That means these are shared-schema failures:

- unknown variable id
- unknown outcome for the referenced variable
- missing `variableId`
- missing `outcomeId`
- malformed clause/literal structure

These failures remain:

```text
status = 400
error.code = "invalid_event_formula"
```

### 3. Public EventTrade identifier adapter

The live EventTrade route deliberately does **not** expose the shared variable-id contract directly.

`normalize_event_trade_formula(...)` adds a route-local compatibility layer:

- `validate_event_trade_formula_market_ids(...)` first requires each present string literal `variableId` to match a known market id
- `translate_event_trade_formula_for_validation(...)` swaps each known market id to the corresponding internal variable id
- `normalize_event_formula(...)` performs shared CNF validation
- `restore_event_trade_formula_market_ids(...)` converts the normalized result back to market ids
- shared-validation failures that carry a `variableId` in `error.details` are translated back to the public market id before the route re-raises them

As a result:

- shared/internal formula handling is variable-id keyed
- public EventTrade HTTP requests and accepted order payloads are market-id keyed
- structurally malformed payloads still fall through to the shared validator and stay `400 invalid_event_formula`
- sending an internal variable id like `eth_price_gt_3000_mar15` to the public EventTrade route is rejected before translation because it is not a known market id

This is why the accepted EventTrade test asserts:

```json
[[{"variableId":"m1","outcomeId":"yes","negated":false}]]
```

instead of the internal variable id `eth_price_gt_3000_mar15`.

### 4. Error-code boundary

For the live checkout, the boundary is:

- malformed formula structure or bad literal identifiers => `400 invalid_event_formula`
- bad public outcome ids also remain `400 invalid_event_formula`; the route preserves the public market id in `error.details.variableId` after shared validation fails
- route-specific EventTrade payload issues such as bad `size`, bad `side`, or formula literal not matching the target path market => `400 invalid_event_trade`
- structurally valid but currently unsupported CNF execution shapes => `501 event_trade_inference_unavailable`

The important freeze for this task is that valid-but-broader CNF does **not** collapse back into `invalid_event_formula`.

### 5. Atomic execution subset

`require_atomic_event_trade_formula(...)` defines the current executable subset as:

```text
single clause
single literal
negated == false
```

Supported-shape marker:

```text
supportedShape = "single_clause_single_literal_non_negated"
```

Anything outside that subset is currently rejected at execution time with:

```text
status = 501
error.code = "event_trade_inference_unavailable"
```

This includes:

- one clause with multiple literals
- multiple clauses
- any negated literal

Those shapes remain valid under the shared CNF schema and validation contract. They are only outside the current atomic EventTrade execution subset.

## Evidence In The Live Checkout

- `apps/bayes-market/backend/server.py`
  - `normalize_event_formula(...)` defines the shared nested-array CNF validator and variable-id resolution.
  - `normalize_event_trade_formula(...)` introduces the market-id adapter only for the public EventTrade route.
  - `require_atomic_event_trade_formula(...)` enforces the temporary execution subset with `501 event_trade_inference_unavailable`.
- `tests/test_bayes_market_api.py`
  - shared formula tests cover malformed shape, missing fields, unknown variable ids, unknown outcomes, duplicate literals, caps, and `negated` typing under `invalid_event_formula`
  - EventTrade tests cover market-id request literals, accepted payload restoration to market ids, `invalid_event_trade` for route-market mismatch, and `501` for broader-but-valid CNF

## Consequence

For the live checkout, the canonical EventTrade formula contract is no longer the older `{"kind":"CNF","expr":"..."}` example in `t544-event-sourcing-contract.md`.

The implementation-true freeze is:

- shared CNF contract: nested arrays of literal objects keyed by variable id
- public EventTrade HTTP contract: same nested-array shape, but keyed by market id through a route-local translation layer
- broader CNF remains schema-valid and reserved for future execution work rather than being treated as malformed input
