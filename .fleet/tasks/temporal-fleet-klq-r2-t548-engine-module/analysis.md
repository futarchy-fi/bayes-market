# t548-engine-module

## Goal

- Move exact-engine identity/config and internal inference contracts out of `backend/server.py`.
- Create a dedicated `backend/inference` package that later T548 follow-ups can implement against.
- Preserve the current HTTP surface and the engine-stats/test contracts while extracting a real module seam.

## Current state

- `backend/server.py` still owns all engine-facing constants (`ENGINE_MODE`, `ENGINE_BACKEND`, `ENGINE_VERSION`, `ENGINE_PRECISION`, `ENGINE_COMPILE_TYPE`, `ENGINE_INFERENCE_SAMPLE_LIMIT`).
- The same file also owns the inference-adjacent helpers for engine stats and compile snapshots: `inference_stats_payload(...)`, `ensure_market_engine_state(...)`, `build_market_cliques(...)`, `estimate_market_engine_memory_bytes(...)`, `refresh_market_compile_snapshot(...)`, `record_market_engine_request(...)`, and `get_market_engine_stats(...)`.
- Current "compile" behavior is synthetic. It derives `compile_id`, clique summaries, and memory estimates from `MARKETS` plus `CONDITIONAL_MARGINALS`; there is no standalone compile artifact or query backend yet.
- Probability-edit and EventTrade paths still read state directly from server-owned structures instead of depending on an inference module boundary.
- `ApiError` is currently the only exception layer. There is no engine-specific exception hierarchy to distinguish compile/query failures from HTTP contract failures.

## Constraints that shape the extraction

- Tests load `backend/server.py` via `importlib.util.spec_from_file_location(...)`, not through a package import. Relative imports from `server.py` into a new package would be fragile.
- Existing API tests freeze the literal engine identity values and the exact engine-stats response shape, including zeroed empty-state behavior and compile metadata for accepted edits.
- The live model on this branch is still an independent-product baseline plus stored conditional slices. This task should not invent a general CPT-backed Bayes net contract that adjacent tasks do not yet provide.
- `backend/formula_schema.py` owns EventTrade formula normalization and the current `event_trade_inference_unavailable` contract boundary. New engine exceptions should remain internal and get translated by the server instead of leaking directly into public error payloads.

## Scope boundary for this child task

- In scope:
  - create the `backend/inference` package scaffold
  - move engine config into a dedicated module/type
  - define compile/query result contracts and engine interfaces
  - define engine-specific exceptions
  - update `backend/server.py` to consume those new definitions with no behavior change
- Out of scope:
  - implementing the real compile artifact (`t548-compile-artifact`)
  - implementing exact query execution (`t548-query-backend`)
  - broad server rewiring beyond the minimum package extraction (`t548-server-adapter`)
  - changing the frozen HTTP payloads, route behavior, or formula-execution subset

## Proposed package shape

- `backend/inference/__init__.py`
  - stable exports used by `server.py`
- `backend/inference/config.py`
  - `EngineConfig` frozen dataclass
  - `DEFAULT_ENGINE_CONFIG` for the current exact junction-tree identity
- `backend/inference/contracts.py`
  - compile/query contracts and interfaces
- `backend/inference/errors.py`
  - engine exception hierarchy

## Recommended contracts

- `EngineConfig`
  - fields: `mode`, `backend`, `version`, `precision`, `compile_type`, `inference_sample_limit`
- `CliqueSummary`
  - fields matching current engine-stats clique entries: `id`, `nodes`, `size`, `states`
- `CompileResult`
  - fields needed by the current engine-stats payload and later compile-artifact work: `compile_id`, `compile_type`, `source_state_hash`, `cliques`, `compile_time_ms`, `memory_bytes`, `last_updated`
- `MarginalQueryResult`
  - baseline result for exact marginal lookup, with marginals plus runtime/cache metadata
- `AtomicEventQueryResult`
  - baseline result for atomic EventTrade pricing/probability lookup, with runtime/cache metadata
- `InferenceCompiler` / `InferenceQueryBackend` protocols
  - narrow interfaces that later subtasks can implement without forcing `server.py` to own inference semantics

The important point is to define types that match current server needs and near-term follow-up tasks, not a speculative full BN engine surface.

## Import and integration strategy

- Do not rely on `from .inference ...` inside `backend/server.py`; that is likely to break when tests load `server.py` as a standalone module.
- Prefer an import strategy that still works when `server.py` is loaded by file path:
  - either absolute imports from `backend.inference...` with package-compatible layout
  - or a small sibling-path loader pattern consistent with the existing `formula_schema.py` import approach
- Replace direct engine literal reads in `server.py` with `DEFAULT_ENGINE_CONFIG` access.
- Keep `MARKET_ENGINE_STATS`, `inference_stats_payload(...)`, and the current synthetic compile helpers in `server.py` for now. Moving those implementations is better handled by `t548-compile-artifact` and `t548-server-adapter`.

## Concrete implementation plan

1. Add the `backend/inference` package and export surface.
2. Move the engine identity constants into `EngineConfig` and add a single default exact-engine instance.
3. Add compile/query dataclasses plus narrow compiler/query protocols.
4. Add an engine exception hierarchy such as:
   - `InferenceError`
   - `InferenceCompileError`
   - `InferenceQueryError`
   - `InferenceUnsupportedQueryError`
5. Update `backend/server.py` to import and use the new config/types/exceptions while keeping behavior byte-for-byte compatible.
6. Add minimal tests for the new package surface if needed, then run the existing Bayes test suite to confirm the extraction is behavior-preserving.

## Risks and decisions to preserve

- Over-extracting current helper logic into the new package would blur task ownership with `t548-compile-artifact` and `t548-server-adapter`.
- Under-extracting and moving only constants would fail to create a useful seam for the next subtasks.
- Contract names should reflect the current exact-engine skeleton, not imply that a full generic junction-tree implementation already exists.
- Engine exceptions should stay internal. The server remains responsible for mapping them onto existing HTTP contract errors.

## Verification after implementation

- `python3 -m unittest discover -s tests -p 'test_bayes_market*.py'`
- If package-specific tests are added, keep them focused on:
  - default engine config values
  - contract object construction/immutability
  - import compatibility from `backend/server.py`
