# T560 — DAC Feasibility Spike & Decision Memo

Generated: 2026-02-26 UTC  
Task: T560 (BAYES-23)

## Executive Summary

**Recommendation:** **Defer full Dynamic Asset Cluster (DAC) implementation to post-MVP (V2), keep Global Separator (GS) as MVP baseline.**

Why:
- GS is sufficient to enforce the MVP solvency invariant with lower implementation and operational risk.
- DAC can materially improve performance for heavy portfolios, but introduces significant complexity in cluster lifecycle, cache invalidation, and replay determinism guarantees.
- The Bayes MVP launch gate is primarily blocked by deterministic replay, solvency correctness, API completeness, and deploy/security hardening; DAC is not required to pass those gates.

Decision status: **Adopt GS now, time-box DAC spike continuation with clear revisit triggers.**

---

## Context

From the blueprint:
- Solvency invariant is mandatory (no negative state-contingent assets after accepted commands).
- GS is listed as production baseline.
- DAC is listed as an advanced option for heavy users.

T538 scope matrix classifies DAC under **Research** and requires a decision memo before implementation commitment.

---

## What DAC means in this context

For this system, DAC = dynamically partitioning each user’s asset/risk representation into clusters aligned with the BN/JT structure and active positions, so risk checks can run over smaller relevant subgraphs instead of broad global separators.

Expected benefit:
- Lower per-command risk-check cost for concentrated portfolios.

Expected cost:
- Complex cluster split/merge/rebuild behavior under structural edits and evolving positions.

---

## Option Analysis

## Option A — GS-only (MVP baseline)

### Pros
- Simpler, deterministic implementation path.
- Easier to prove replay equivalence and hash stability.
- Lower operational complexity and fewer edge cases.
- Better fit for current launch-gate priorities.

### Cons
- Potentially higher latency/cost for very large or highly fragmented portfolios.
- Less headroom before needing optimization.

### Risk profile
- **Low implementation risk**
- **Low determinism risk**
- **Medium scalability risk** (manageable for MVP volumes)

---

## Option B — Full DAC in MVP

### Pros
- Better theoretical scaling for heavy users and dense markets.
- Earlier optimization investment may avoid future rewrites.

### Cons
- High implementation complexity (cluster lifecycle logic).
- Harder replay determinism and reproducibility guarantees.
- Larger test matrix and debugging burden.
- Increased schedule risk against MVP gate milestones.

### Risk profile
- **High implementation risk**
- **High determinism risk**
- **Lower long-term scalability risk** if done correctly

---

## Option C — Hybrid (GS default + DAC opt-in path later)

### Pros
- Preserves MVP reliability while creating controlled path for DAC rollout.
- Allows real telemetry to drive optimization scope.

### Cons
- Requires explicit compatibility rules between GS and DAC modes.
- Two-path maintenance burden once DAC ships.

### Risk profile
- **Low near-term risk**, **medium long-term complexity**

---

## Feasibility Assessment (current phase)

### Technical feasibility
- DAC is feasible, but not cheaply feasible within MVP risk envelope.
- Critical unknowns remain around deterministic cluster evolution under command replay.

### Delivery feasibility
- Implementing DAC now is likely to pull resources from critical gates (replay/solvency/API/deploy/security).

### Verification feasibility
- Strong correctness requires extensive property tests and replay proofs across cluster reconfiguration scenarios; this is substantial work not currently budgeted for MVP.

---

## Determinism & Replay Tradeoffs

DAC directly affects replay-critical surfaces:
- cluster assignment order
- tie-breaking rules for split/merge
- cache invalidation timing
- canonical serialization of cluster state

If these are not fully deterministic and version-pinned, replay hash mismatch risk increases materially.

GS avoids most of this by using a more stable, globally-scoped representation.

---

## Performance Tradeoffs

Expected behavior by stage:
- **MVP traffic:** GS likely acceptable with bounded market size and command rate.
- **Growth phase:** GS may show p95 degradation for high-degree markets / high-position users.
- **Scale phase:** DAC likely needed for predictable latency at upper load tiers.

Therefore DAC is best treated as **evidence-triggered optimization**, not day-0 requirement.

---

## Security & Operational Tradeoffs

DAC introduces additional failure modes:
- inconsistent cluster state after partial failures
- harder incident triage due to dynamic topology
- more subtle bugs that may evade simple invariants

For MVP, minimizing moving parts improves auditability and incident response.

---

## Recommendation

## Decision

1. **MVP:** Ship with **GS-only** solvency path.
2. **V2/Research:** Keep DAC as a controlled follow-on project.
3. **No launch gating on DAC** for MVP.

## Rationale

This maximizes probability of passing launch-critical gates while preserving a clear optimization path once real load data exists.

---

## Revisit Triggers (when to escalate DAC)

Escalate DAC from research to implementation when any condition persists over agreed observation window:

- Risk-check latency exceeds target (e.g., p95 above Tier B threshold) on production-like load.
- GS memory/cpu overhead exceeds predefined budget for top-N heavy users.
- Command rejection/timeout rates attributable to risk-check runtime become material.

---

## Proposed Next Steps

1. Keep T559/T561 GS path as authoritative MVP implementation.
2. Add instrumentation tags for risk-check cost by:
   - user portfolio size
   - affected separators
   - command type
3. Produce DAC design RFC before coding with:
   - deterministic cluster lifecycle rules
   - canonical ordering/tie-break strategy
   - replay-hash impact analysis
   - migration and rollback plan
4. Time-box DAC prototype after MVP gate completion.

---

## Acceptance Checkpoints for this memo (T560)

- [x] DAC vs GS options compared with explicit tradeoffs
- [x] Determinism/replay implications called out
- [x] Clear recommendation with reasoning
- [x] Trigger criteria for future DAC escalation defined
- [x] Actionable next steps for roadmap integration

---

## Final Call

**Proceed with GS for MVP. Keep DAC in research/V2 until telemetry justifies complexity and deterministic design is fully specified.**
