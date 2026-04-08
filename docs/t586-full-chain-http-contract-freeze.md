# T586 Full-Chain HTTP Contract Freeze

Date: 2026-04-05
Branch: `ff/Ttemporal-fleet-cy8-r1-bayes-t586-freeze-full-chain-http-contract`

## Question

Before extending the full-chain integration coverage in `tests/test_bayes_market_api.py`, what HTTP contract is already frozen for:

- accepted `POST /v1/markets/{id}/orders/probability-edit`
- unconditional solvency rejections on the same route

This checkpoint exists to stop a test-only task from silently rewriting the live server contract.

## Findings

### 1. Accepted ProbabilityEdit submissions already return `201`, not `200`

The route implementation hard-codes `201` at the acceptance boundary.

Evidence:

- `build_terminal_acceptance_response(...)` in `apps/bayes-market/backend/server.py` records terminal outcomes with status `201` and returns `(response, 201)`.
- The HTTP integration suite asserts `201` for the market-scoped route, idempotent replay, zero-headroom acceptance, and read-after-write risk flow in `tests/test_bayes_market_api.py`.
- The earlier HTTP freeze memo `apps/bayes-market/docs/t1737-probability-edit-http-contract-freeze.md` already froze the response shape as top-level `201` with `{order, meta}`.

This is not an incidental test expectation. It is the explicit server response contract.

### 2. Unconditional solvency failures are terminal domain rejections with `409`, not request-validation `400`

The unconditional solvency branch runs only after the request body has already passed structural validation and has been normalized into a canonical ProbabilityEdit command. The server then previews the edit and rejects it only if `afterMinAsset < 0`.

Evidence:

- `handle_probability_edit(...)` in `apps/bayes-market/backend/server.py` raises `400 invalid_probability_edit` only for malformed request fields such as missing `accountId` or bad `target.probability`.
- The same handler calls `build_terminal_rejection_response(...)` with `code="min_asset_violation"` and `status=409` when the previewed unconditional edit would drive `afterMinAsset` negative.
- `build_terminal_rejection_response(...)` emits a `CommandRejected` event, mirrors the symbolic code into both `error.code` and `result.reasonCode`, and records a replayable terminal outcome.

That behavior makes the current `409` meaningful: the command is well-formed, but the server refuses to accept it as a valid state transition.

### 3. `min_asset_violation` is the canonical rejection code already shared by code, tests, and event-contract docs

There is no in-tree evidence for `insufficient_min_asset`.

Evidence:

- `apps/bayes-market/backend/server.py` uses `code="min_asset_violation"` for unconditional solvency failures.
- `tests/test_bayes_market_api.py` asserts `error.code == "min_asset_violation"` and, on direct route coverage, `result.reasonCode == "min_asset_violation"`.
- `apps/bayes-market/docs/t544-event-sourcing-contract.md` freezes the `CommandRejected` payload example with `"reasonCode": "min_asset_violation"`.
- Repo-wide search found no Bayes contract source using `insufficient_min_asset`.

Renaming the rejection code would therefore be a real contract change across the HTTP layer, event payloads, and existing tests.

### 4. The current full-chain test surface already depends on the existing contract

The integration file already covers the edit -> risk-state update path and the unconditional solvency rejection path under the current HTTP contract.

Evidence:

- `tests/test_bayes_market_api.py` asserts `201` for successful HTTP ProbabilityEdit submissions and then reads `GET /v1/accounts/{id}/risk` to verify the asset update.
- The same file asserts `409` plus `min_asset_violation` for unconditional solvency failure and verifies that market state, account state, orders, and replay metadata remain unchanged except for the recorded terminal rejection.

Appending new assertions under T586 should extend this surface, not contradict it.

### 5. Reproducible branch runtime matches the frozen contract

Verification run:

```bash
python3 -m unittest discover -s tests -p 'test_bayes_market_api.py'
```

Result: `Ran 62 tests ... OK`

That suite includes the HTTP integration and solvency property coverage described above, so the checked-in runtime agrees with the source-level contract.

### 6. There is no local deployed Bayes listener on `127.0.0.1:3200` in this worktree session

On this host, `127.0.0.1:3200` is currently a Node listener and `GET /healthz` returns `404 {"error":"Not found"}`. The existing public probe script also checks only `/healthz`, not the ProbabilityEdit POST contract.

Implication:

- this checkpoint is frozen from checked-in server code plus reproducible test runtime
- it is not a claim that this specific local host is currently serving Bayes on `:3200`

## Freeze Decision For T586

Until there is an explicit server-contract rewrite task, the safe assertions for `tests/test_bayes_market_api.py` are:

- accepted ProbabilityEdit HTTP writes return `201`
- unconditional solvency failures return `409`
- unconditional solvency failures use `error.code == "min_asset_violation"`
- terminal rejection metadata also keeps `result.reasonCode == "min_asset_violation"`
- `400` remains reserved for malformed request/query validation, not for a structurally valid command that fails solvency checks

## Consequence

The mismatch is between the current task brief wording and the actual Bayes HTTP contract already encoded in source, tests, and contract docs.

For this branch, treat `200` and `400/insufficient_min_asset` as out-of-contract expectations. If those semantics are desired, they should be introduced only through a separate server-contract change that updates:

- `apps/bayes-market/backend/server.py`
- existing HTTP/property tests in `tests/test_bayes_market_api.py`
- event-contract docs in `apps/bayes-market/docs/t544-event-sourcing-contract.md`
- HTTP freeze docs in `apps/bayes-market/docs/t1737-probability-edit-http-contract-freeze.md`

That keeps T586 as a test-coverage task instead of turning it into an unplanned API rewrite.
