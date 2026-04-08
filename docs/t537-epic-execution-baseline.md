# T537 Epic Execution Baseline — Bayes BN Market

_Generated: 2026-02-26 04:45 UTC_

This umbrella task is executed via linked BAYES follow-ups (T538–T587).

## Snapshot

- Total linked follow-ups: **50**
- Status counts: **pending=50**
- Assignees: **analyst=6**, **coder=44**

## Execution Waves

### 1) Scope + contracts
- T538 [pending] (analyst): Convert blueprint into implementation scope matrix (MVP vs v2 vs research)
- T539 [pending] (analyst): Define acceptance criteria for MVP launch gate
- T540 [pending] (coder): Write BN variable/outcome schema contract
- T541 [pending] (coder): Write CPT storage/update contract
- T542 [pending] (coder): Define inference service interface (exact + approx modes)
- T543 [pending] (coder): Scaffold bayes-market codebase structure under apps/bayes-market
- T544 [pending] (analyst): Define event-sourcing schema (commands/events/snapshots)
- T545 [pending] (coder): Define deterministic replay hash strategy
- T546 [pending] (coder): Define ProbabilityEdit command schema (unconditional + conditional)
- T547 [pending] (coder): Define EventTrade formula schema (CNF payload + validation rules)

### 2) Inference + pricing engine core
- T548 [pending] (coder): Implement bounded-treewidth exact inference module skeleton
- T549 [pending] (coder): Implement soft-evidence application path for unconditional edits
- T550 [pending] (coder): Implement conditional soft-evidence path with context assignment
- T551 [pending] (coder): Implement structure-preserving edit validator
- T552 [pending] (coder): Implement approximation-flag pipeline for non-preserving trades
- T553 [pending] (coder): Implement junction-tree cache invalidation logic
- T554 [pending] (coder): Implement incremental compile hook contracts
- T555 [pending] (coder): Implement loopy-BP fallback loop with time budget
- T556 [pending] (coder): Implement per-user asset model transformation (Sx = b ln q(x))
- T557 [pending] (coder): Implement min-asset checker for unconditional edits
- T558 [pending] (coder): Implement conditional edit allowable range bounds
- T559 [pending] (coder): Implement Global Separator (GS) minimum-assets path
- T560 [pending] (analyst): Add DAC feasibility spike and decision memo
- T561 [pending] (coder): Implement risk rejection reasons and partial-size guidance
- T562 [pending] (coder): Build deterministic single-writer sequencer for one market shard
- T563 [pending] (coder): Implement append-only journal with hash-chain fields
- T564 [pending] (coder): Implement snapshot writer (probability state + assets state)
- T565 [pending] (coder): Implement snapshot restore + replay validation
- T566 [pending] (coder): Build market shard lifecycle manager
- T567 [pending] (coder): Add execution latency tier instrumentation (A/B/C tiers)

### 3) APIs + realtime + UI
- T568 [pending] (coder): Implement /v1/markets and /v1/markets/{id} for BN markets
- T569 [pending] (coder): Implement /orders/probability-edit endpoint
- T570 [pending] (coder): Implement /orders/event-trade endpoint
- T571 [pending] (coder): Implement /engine-stats endpoint (clique/runtime metrics)
- T572 [pending] (coder): Implement /accounts/{id}/risk endpoint
- T573 [pending] (coder): Implement WebSocket marginals/executions/portfolio channels
- T574 [pending] (coder): Build Simple Forecast UI panel (single-variable edit flow)
- T575 [pending] (coder): Build Advanced Conditional Edit UI panel
- T576 [pending] (coder): Build BN graph visualization panel with impact preview
- T577 [pending] (coder): Add approximation badge + convergence metadata in UI

### 4) Deployment + security + verification
- T578 [pending] (coder): Add systemd unit for bayes service on claw
- T579 [pending] (coder): Add deploy env template and runtime config file
- T580 [pending] (coder): Create public-route probe script for bayes.futarchy.ai
- T581 [pending] (analyst): Write DNS + Cloudflare tunnel routing runbook (public mode)
- T582 [pending] (coder): Add auth/rate-limit baseline for write endpoints
- T583 [pending] (coder): Add API abuse controls for inference-heavy routes
- T584 [pending] (coder): Add invariant test suite (inference correctness vs brute force on tiny nets)
- T585 [pending] (coder): Add solvency property tests (no negative state assets)
- T586 [pending] (coder): Add integration tests for edit->inference->asset update path
- T587 [pending] (analyst): Add load/simulation harness and launch checklist

## Orchestration Note

- T537 remains an umbrella tracker; feature delivery and deployment are intentionally decomposed into BAYES-* tasks.
- Completion for T537 should be judged by completion of linked follow-ups and bayes.futarchy.ai production readiness.
