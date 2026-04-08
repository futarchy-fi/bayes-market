# T587 — Load/Simulation Harness + Launch Readiness Checklist

Generated: 2026-02-26 UTC  
Task: T587 (BAYES-50)

## Purpose

Provide a reproducible load/simulation harness and a launch-readiness checklist that can be attached to Bayes MVP GO/NO-GO decisions.

This checklist complements `t539-mvp-launch-gate.md` by adding measured runtime evidence.

---

## Harness

Script:
- `apps/bayes-market/scripts/t587_load_harness.py`

Output artifact (default):
- `apps/bayes-market/docs/artifacts/t587-load-harness-latest.json`

## What it measures

Per endpoint:
- request count
- success/error counts and success rate
- status-code distribution
- latency: min/p50/p95/p99/max/mean
- achieved requests/sec
- sample errors

---

## Quick run commands

## 1) Local service baseline

```bash
curl -sS http://127.0.0.1:3205/healthz
python3 apps/bayes-market/scripts/t587_load_harness.py \
  --base-url http://127.0.0.1:3205 \
  --endpoints /healthz,/ \
  --requests 200 \
  --concurrency 20
```

## 2) Public route evidence + light load

```bash
bash scripts/bayes_public_route_probe.sh
```

Only continue with the public load run when the probe reports `PUBLIC_STATUS=PASS`:

```bash
python3 apps/bayes-market/scripts/t587_load_harness.py \
  --base-url https://bayes.futarchy.ai \
  --endpoints /healthz \
  --requests 100 \
  --concurrency 10
```

---

## Suggested MVP thresholds (initial)

These are starting targets for MVP and can be tightened after real traffic data:

- success rate >= **99.0%**
- `/healthz` p95 <= **250ms**
- `/healthz` p99 <= **500ms**
- zero sustained 5xx bursts under baseline load profile

If thresholds are missed:
- classify as GO-with-risk or NO-GO depending on severity and critical gate interactions.

---

## Launch Readiness Checklist (T587)

## A) Service + route
- [ ] `bayes-market.service` active and stable (`systemctl --user status`)
- [ ] local health endpoint returns 200 JSON
- [ ] probe script reports `LOCAL_STATUS=PASS`
- [ ] public probe status recorded (`PUBLIC_STATUS=PASS` or `WARN` with follow-up owner)
- [ ] only run the public load harness when `PUBLIC_STATUS=PASS`

## B) Harness evidence
- [ ] harness run completed and artifact saved to docs/artifacts
- [ ] success rate meets threshold
- [ ] p95/p99 latency within threshold
- [ ] error sample reviewed and categorized

## C) Gate alignment with T539
- [ ] deterministic replay gate evidence linked
- [ ] solvency gate evidence linked
- [ ] API contract gate evidence linked
- [ ] deploy/public route gate evidence linked
- [ ] security/abuse gate evidence linked

## D) Decision package
- [ ] open risks documented with owner + due date
- [ ] explicit GO/NO-GO recommendation recorded
- [ ] evidence links attached in release record

---

## Evidence record template

```md
## T587 Load/Simulation Evidence — <date>

### Harness config
- base_url:
- endpoints:
- requests_per_endpoint:
- concurrency:

### Results summary
- success_rate:
- p95_ms:
- p99_ms:
- status_counts:

### Artifacts
- JSON report: apps/bayes-market/docs/artifacts/t587-load-harness-latest.json
- public probe output:
- public probe status:

### Risk notes
- <risk / owner / mitigation date>

### Recommendation
- GO | NO-GO
- rationale:
```

---

## Notes

- This harness is intentionally HTTP-level and lightweight for repeatable gate checks.
- `LOCAL_STATUS=PASS` proves the repo-owned Bayes runtime is healthy on `127.0.0.1:3205`.
- `PUBLIC_STATUS=WARN` means the external edge path still needs follow-up and should block
  claiming the final public-route gate in `t539-mvp-launch-gate.md`.
- Deeper engine-level simulation (order mix, formula complexity, adversarial portfolios) should be added in follow-up performance tasks once MVP endpoints are fully implemented.
