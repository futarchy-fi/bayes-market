# T538 — BAYES-01 Scope Matrix (MVP vs V2 vs Research)

Generated: 2026-02-26 UTC  
Task: T538 (follow-up of T537)

## Purpose

Translate the canonical blueprint (`docs/design/bayes-bn-combinatorial-market-blueprint.md`) into an implementation scope matrix that is execution-ready for the current task graph.

This matrix is a planning contract:
- **MVP** = required to claim initial launch gate readiness for `bayes.futarchy.ai`
- **V2** = important expansion after MVP stability
- **Research** = unresolved/high-uncertainty tracks that need decision memos before commitment

---

## Scope Matrix

| Capability Area | Blueprint Capability | Bucket | Why This Bucket | Primary Linked Tasks | Exit/Acceptance Checkpoint |
|---|---|---|---|---|---|
| Platform baseline | Public health endpoint + service baseline | MVP | Needed for deployability and operational visibility from day 1 | T543, T578, T579, T580, T581 | `https://bayes.futarchy.ai/healthz` returns 200 + expected JSON; service managed by systemd runbook |
| State model | Discrete BN state + variable/outcome schema | MVP | Foundation for all market/inference behavior | T540 | Schema contract versioned and consumed by backend without shape drift |
| Command contracts | ProbabilityEdit and EventTrade payload schemas | MVP | Required for deterministic command ingestion | T546, T547 | Command validation errors are deterministic and documented |
| Persistence model | Event-sourced journal + snapshots + replay hash | MVP | Core product guarantee is deterministic replayability | T544, T545, T563, T564, T565 | Snapshot+replay reproduces same state hash for seeded scenario suite |
| Execution model | Single-writer sequencer per market shard | MVP | Needed to prevent non-deterministic race behavior | T562, T566 | Total order is enforced; concurrent command simulation shows no divergent state |
| Inference (exact path) | Exact inference for bounded treewidth | MVP | Required for trustworthy baseline probabilities | T548, T553, T554 | Exact mode passes correctness checks on bounded graphs |
| Edit pipeline | Unconditional + conditional soft-evidence edits | MVP | Minimal tradable/editable primitive set for launch | T549, T550, T551 | Edit command updates marginals deterministically with audit trail |
| Risk/solvency | Min-asset invariant enforcement | MVP | Non-negativity invariant is non-negotiable for launch safety | T556, T557, T558, T559, T561 | No accepted command yields negative state-contingent assets |
| API surface | REST for markets, orders, engine stats, account risk | MVP | Required to support frontend and observability | T568, T569, T570, T571, T572 | Endpoint contract tests pass; error semantics stable |
| Realtime surface | WebSocket marginals/executions/portfolio streams | MVP | Needed for responsive UX and execution trace visibility | T573 | Stream payloads include seq/timestamp/approxFlag and are monotonic by seq |
| UI baseline | Simple forecast + advanced conditional panel + risk preview | MVP | Minimum user-operable interaction model | T574, T575 | User can submit both edit types and see risk/cost preview before submit |
| Security controls | Authz + rate limits + abuse baseline for write paths | MVP | Prevents immediate abuse/overload in public exposure | T582, T583 | Unauthorized writes rejected; rate-limit behavior documented and test-covered |
| Verification | Invariant/property/integration test suite | MVP | Needed to trust engine behavior before launch gate | T584, T585, T586 | Test suite green in CI; failures are actionable and categorized |
| Ops readiness | Load/simulation harness + launch checklist | MVP | Required for launch/no-launch decision quality | T587, T539 | Launch checklist complete with measured SLO and risk evidence |
| Formula/event expressivity | Richer formula trade support beyond constrained set | V2 | High utility, but complexity/risk can be deferred | (future after T547/T570) | Expanded formula subset accepted with deterministic validation and bounded latency |
| Approximate inference | Time-bounded loopy BP fallback telemetry hardening | V2 | Valuable for scale/coverage; MVP can constrain to exact-eligible paths | T552, T555, T577 | Approx mode triggers are explicit; convergence/runtime telemetry visible in UI/API |
| UX explainability | Graph impact/explainability and deeper transparency layers | V2 | Improves trust and usability but not required for baseline correctness | T576, T577 | Users can inspect dependency impact and approximation confidence context |
| Throughput optimization | Incremental compile and cache strategy hardening | V2 | Performance-oriented; correctness comes first | T553, T554, T567 | Tier A/B/C SLOs met at target load profile |
| Portfolio scalability | Dynamic Asset Cluster (DAC) model | Research | Explicitly uncertain tradeoff vs GS complexity and benefits | T560 | Decision memo approved: adopt/defer DAC with quantified complexity/benefit |
| Market mechanism evolution | Broader combinatorial pricing guarantees under unrestricted formulas | Research | Known hard area; needs formal approach before commitment | (future spike) | Research artifact with algorithmic options, risks, and acceptance boundaries |
| Governance automation | Monthly/yearly governance automation | Research | Blueprint marks this out-of-scope for initial MVP | (future) | Governance automation ADR accepted with policy/operational model |
| Decentralized matching | On-chain/decentralized matching architecture | Research | Blueprint explicitly out-of-scope for MVP | (future) | Architecture proposal approved with trust/security/perf tradeoff analysis |

---

## MVP Acceptance Checkpoints (Gate-Oriented)

MVP is considered implementation-complete only when all checkpoints pass:

1. **Determinism checkpoint**
   - Event log + snapshot replay reproduces identical state hash.
2. **Solvency checkpoint**
   - Min-asset invariant enforced for all accepted edits/trades.
3. **Inference checkpoint**
   - Exact bounded-treewidth path passes correctness tests.
4. **API checkpoint**
   - Required REST + WebSocket contracts are available and stable.
5. **UI checkpoint**
   - Simple + conditional edit workflows function with risk preview.
6. **Security checkpoint**
   - Authz and abuse controls active on write-heavy endpoints.
7. **Ops checkpoint**
   - Public `bayes.futarchy.ai/healthz` reachable without Access redirect.
8. **Verification checkpoint**
   - Invariant, property, and integration suites green in CI.

If any checkpoint fails, MVP remains **not launch-ready**.

---

## Phase Boundaries (Execution Rules)

- Work labeled **MVP** can block launch and should be prioritized in active sprinting.
- Work labeled **V2** must not expand MVP scope unless a formal launch-risk rationale is recorded.
- Work labeled **Research** must produce a decision memo before implementation tasks are spawned.

---

## Recommended Next Artifacts

- T539 should consume this matrix to define a binary launch gate checklist.
- T560 should use this matrix’s DAC row as the required decision framing.
- Any new Bayes tasks should include one explicit tag in evidence: `MVP`, `V2`, or `Research`.
