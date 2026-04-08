# T539 — Bayes MVP Launch Gate Acceptance Criteria

Generated: 2026-02-26 UTC  
Depends on: T538 scope matrix, blueprint acceptance section

## Purpose

Define the **release gate** for Bayes MVP so launch decisions are binary and evidence-driven.

Decision outputs:
- **GO**: all critical gates pass, no unresolved critical risks
- **NO-GO**: any critical gate fails or has missing evidence

---

## Gate Model

Gates are split into:
- **Critical gates** (must pass)
- **Advisory gates** (should pass; can launch with explicit waiver)

MVP launch requires:
1. All critical gates = PASS
2. Advisory failures documented with owner + due date
3. Evidence links captured in release record

---

## Critical Gates

## G1 — Deterministic Replay Gate (Critical)

**Objective:** Event log + snapshot replay must produce identical state hash.

**Pass criteria:**
- Deterministic replay tests pass in CI.
- At least one seeded scenario proves `replay_hash == live_hash`.
- Hash mismatch handling emits explicit failure and blocks release.

**Primary tasks:** T544, T545, T563, T564, T565

**Evidence required:**
- CI run URL/artifact for replay tests
- Hash comparison output from seeded scenario

---

## G2 — Solvency Gate (Critical)

**Objective:** No accepted command can make user min-assets negative.

**Pass criteria:**
- Property tests show no solvency invariant violations.
- Runtime rejects out-of-bounds edits/trades with explicit reason.
- Risk endpoint reflects current min-asset state consistently.

**Primary tasks:** T556, T557, T558, T559, T561, T585

**Evidence required:**
- Property/invariant test output
- Rejection-path example payload + response

---

## G3 — API Contract Gate (Critical)

**Objective:** MVP REST + WS surfaces are complete and contract-stable.

**Pass criteria:**
- Required REST endpoints available and tested:
  - `/v1/markets`, `/v1/markets/{id}`
  - `/v1/markets/{id}/orders/probability-edit`
  - `/v1/markets/{id}/orders/event-trade`
  - `/v1/markets/{id}/engine-stats`
  - `/v1/accounts/{id}/risk`
- WS channels emit monotonic `seq` and include `timestamp`, `approxFlag`.
- Contract tests pass for success and error paths.

**Primary tasks:** T568, T569, T570, T571, T572, T573

**Evidence required:**
- API contract test report
- WS stream sample with ordered sequence proof

---

## G4 — Deploy/Public Route Gate (Critical)

**Objective:** MVP is externally reachable and healthy on target domain.

**Pass criteria:**
- `https://bayes.futarchy.ai/healthz` returns `200` and Bayes service JSON.
- No Access-login redirect for public health endpoint.
- Service managed by systemd with restart policy and documented rollback.

**Primary tasks:** T578, T579, T580, T581

**Evidence required:**
- Probe output (`scripts/bayes_public_route_probe.sh`)
- `systemctl --user status bayes-market.service` output
- Rollback command verification note

---

## G5 — Security/Abuse Gate (Critical)

**Objective:** Write paths are protected before public usage.

**Pass criteria:**
- Authz enforced for write endpoints.
- Rate limiting/abuse controls enabled for inference-heavy routes.
- Unauthorized and throttled behavior covered by tests.

**Primary tasks:** T582, T583

**Evidence required:**
- Security test outputs (unauthorized + throttling cases)
- Config snippet proving controls enabled in runtime

---

## Advisory Gates

## A1 — Inference Correctness Coverage
- Exact inference tests vs brute-force tiny nets pass.  
- Task linkage: T548, T584.

## A2 — UI Operability
- Simple + conditional edit flows usable end-to-end with risk preview.  
- Task linkage: T574, T575.

## A3 — Performance/SLO Readiness
- Latency telemetry available and baseline measured for Tier A/B/C.  
- Task linkage: T567, T587.

## A4 — Approximation UX Transparency
- Approx mode badges and convergence metadata visible in UI when relevant.  
- Task linkage: T552, T555, T577.

---

## Release Checklist (Fill at Decision Time)

- [ ] G1 Deterministic Replay = PASS
- [ ] G2 Solvency = PASS
- [ ] G3 API Contracts = PASS
- [ ] G4 Deploy/Public Route = PASS
- [ ] G5 Security/Abuse = PASS
- [ ] Advisory gate results recorded (A1–A4)
- [ ] Open risks listed with owner/date
- [ ] Final decision recorded (GO / NO-GO)

---

## Evidence Record Template

```md
## Bayes MVP Launch Decision — <date>

- Decision: GO | NO-GO
- Decision owner:
- Reviewers:

### Critical gates
- G1: PASS/FAIL — <link>
- G2: PASS/FAIL — <link>
- G3: PASS/FAIL — <link>
- G4: PASS/FAIL — <link>
- G5: PASS/FAIL — <link>

### Advisory gates
- A1: PASS/FAIL — <link>
- A2: PASS/FAIL — <link>
- A3: PASS/FAIL — <link>
- A4: PASS/FAIL — <link>

### Risks/waivers
- <risk, owner, mitigation date>
```

---

## NO-GO Conditions (Automatic)

Launch is automatically blocked if any of the following occur:
- Replay hash mismatch in deterministic tests
- Any solvency invariant failure
- Public health endpoint unavailable or Access-gated
- Missing authz/rate-limit controls on write paths
- Missing evidence for any critical gate
