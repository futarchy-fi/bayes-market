# T551 Structure-Preserving ProbabilityEdit Validator Boundary Freeze

Date: 2026-04-08
Branch: `ff/Ttemporal-fleet-0zv-r1-t551-boundary`

## Question

For the current Bayes stub backend, where exactly does the `ProbabilityEdit` structure-preserving validator sit in the request pipeline, and what does it own versus the surrounding normalization, command, solvency, and mutation layers?

## Decision

Freeze `T551` as a **pure, pre-mutation validator over normalized ProbabilityEdit state**.

Its boundary is:

- it runs only after the route has already resolved the target market and canonicalized the payload into a normalized `ProbabilityEdit` shape
- it receives the already-selected base marginal slice for that normalized context
- it returns only success or `400 invalid_structure_preserving_edit`
- it performs no command persistence, order creation, market mutation, conditional-slice mutation, or account-risk mutation

So `T551` owns only **normalized market/context/base-marginal preservation checks**. It does **not** own generic payload validation, HTTP metadata validation, command materialization, active-market gating, or solvency.

## Frozen Pipeline Boundary

The checked-in `ProbabilityEdit` flow is:

1. `handle_probability_edit(...)` validates route-local request metadata:
   - required `accountId`
   - optional `idempotencyKey`
2. `normalize_probability_edit_payload(...)` validates and canonicalizes the payload:
   - request body must be an object
   - `variableId` must match the addressed market variable
   - `target` must be an object with `kind == "marginal"`
   - `target.outcomeId` and `target.probability` must be present
   - `context` shape is normalized, trimmed, deduplicated, sorted, and conflict-checked
   - `target.probability` is normalized to `float`
3. `resolve_probability_edit_base_marginals(...)` chooses the base slice:
   - unconditional edits use `market["marginals"]`
   - contextual edits use the existing `CONDITIONAL_MARGINALS[market_id][context_key]` slice when present
   - otherwise they fall back to the market marginals
4. `validate_structure_preserving_edit(...)` runs on:
   - resolved `market`
   - `normalized_payload`
   - resolved base marginals
5. `apply_probability_target(...)` still runs before the normalized payload is returned, but that is outside the `T551` validator boundary.
6. Only after normalization finishes does the route continue to:
   - idempotency replay/conflict handling
   - `materialize_probability_edit_command(...)`
   - active-market rejection
   - unconditional solvency preview/rejection
   - `create_probability_edit_order(...)`
   - `sync_account_risk_state(order)`

This freezes `T551` as a seam **inside** the normalization path but **after** canonicalization has already happened.

## What T551 Owns

`validate_structure_preserving_edit(...)` owns these checks and emits `400 invalid_structure_preserving_edit` when they fail:

- the normalized `target.outcomeId` must belong to the target market
- each normalized context assignment must still resolve to a known market variable and valid outcome
- the selected base marginal slice must match the target market outcome set exactly
- the selected base marginal slice must contain finite numeric values
- the selected base marginal slice must be non-negative and sum to `1.0`
- if `target.probability < 1.0`, the non-target portion of the selected base slice must leave positive mass to renormalize
- the previewed updated marginals must not go negative after applying the normalized target

Conceptually, this is not generic request validation. It is a semantic check that the **already-normalized edit** can preserve a valid marginal distribution on the **already-selected base slice**.

## What T551 Does Not Own

The surrounding layers keep these responsibilities:

### Normalization / generic payload contract

These stay under `invalid_body` or `invalid_probability_edit`, not `invalid_structure_preserving_edit`:

- `accountId` and `idempotencyKey`
- request-body object shape
- `variableId` matching the market path
- `target` object existence
- `target.kind`
- presence of `target.outcomeId`
- presence of `target.probability`
- `context` being an array of objects
- trimming/sorting/deduping context assignments
- rejecting conflicting duplicate context assignments
- rejecting self-referential context assignments
- normalizing `target.probability` to a numeric float
- generic probability/application rules such as `0 < probability < 1`

That last point matters: the current code still calls `apply_probability_target(...)` after `validate_structure_preserving_edit(...)`, and that helper keeps the generic `invalid_probability_edit` contract for probability-range/application failures.

### Base-slice selection

`T551` validates the chosen base marginals; it does not decide which slice to use.

`resolve_probability_edit_base_marginals(...)` owns:

- unconditional versus contextual slice selection
- fallback from a missing contextual slice to the market marginals

So the validator boundary starts only once the candidate base slice already exists.

### Command / route / solvency / mutation

These remain outside `T551`:

- idempotency replay and conflict handling
- `materialize_probability_edit_command(...)` and `COMMANDS` persistence
- `market_not_active` rejection
- unconditional solvency preview and `min_asset_violation`
- `create_probability_edit_order(...)`
- `ORDERS` persistence
- `MARKETS[market_id]["marginals"]` mutation
- `CONDITIONAL_MARGINALS` mutation
- `ACCOUNT_RISK` mutation
- terminal event emission

## Why This Boundary Matches The Checked-In Code

### 1. The validator already declares itself normalized and side-effect free

`validate_structure_preserving_edit(...)` is documented as validating an "already-normalized probability edit without mutating state". Its parameters are `market`, `normalized_payload`, and optional `marginals`, not the raw HTTP body or account/command metadata.

### 2. The call site proves it runs before any command or order persistence

`handle_probability_edit(...)` calls `normalize_probability_edit_payload(...)` before `materialize_probability_edit_command(...)`.

Inside that normalization helper, the route:

- constructs `normalized_payload`
- resolves `base_marginals`
- calls `validate_structure_preserving_edit(...)`

So any `invalid_structure_preserving_edit` failure happens before command persistence, before order creation, and before downstream mutation.

### 3. The optional `marginals` parameter shows the validator is about slice preservation, not request parsing

The validator can check either:

- the market's unconditional marginals, or
- an existing contextual marginal slice

That is the exact structure-preserving seam for `T551`: validate whether the selected slice is a coherent probability distribution that can absorb the normalized edit without breaking market structure.

### 4. Tests already separate this error class from normalization and solvency

The checked-in tests distinguish:

- `invalid_probability_edit` for request/payload normalization failures
- `invalid_structure_preserving_edit` for malformed base marginals or normalized slice-preservation failures
- `409 min_asset_violation` for later unconditional solvency rejection

The structure-preserving tests also assert that these failures occur with no orders or events created, matching the pre-mutation boundary.

## Frozen Error Partition

Use this partition going forward:

| Layer | Error family | Meaning |
|---|---|---|
| HTTP/body/payload normalization | `invalid_body`, `invalid_probability_edit` | Raw request or generic payload/application contract failure |
| `T551` structure-preserving validator | `invalid_structure_preserving_edit` | Normalized edit cannot preserve a valid distribution on the selected base slice |
| Route-local domain gates after command materialization | `market_not_active`, `min_asset_violation` | Canonical command is well-formed but rejected by later business rules |

This is the clean boundary that preserves the intent of `T551` without letting it absorb generic validation or solvency work that belongs to other tasks.

## Sources

- `backend/server.py`
- `tests/test_bayes_market_api.py`
- `docs/t544-event-sourcing-contract.md`
- `docs/t557-unconditional-solvency-contract-freeze.md`
