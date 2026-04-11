# Fleet Backlog

## Priority 1: Test the infrastructure
- [x] **Codex sandbox and syntax fixed** — workspace-write sandbox, positional prompt argument, output truncation
- [x] **Fixed provider: Codex→Claude** — OPENAI_API_KEY not configured, switched default to Claude. claude-test-003 completed all 4 phases and auto-merged.
- [x] **Implement prompt fixed** — implement-test-001 achieved plan_adherence=1.0. Added directive step execution with verification. See LEARNINGS.md.
- [x] **All phase prompts now directive** — Applied "YOU MUST create" pattern to question/research/plan/validate prompts.
- [x] **Shell escaping fixed** — Prompt written to file, passed via stdin with --input-format text. Question phase now creates questions.json.
- [x] **Subsequent phases work but skip JSON artifacts** — debug-test-001 ran all 4 phases, created counter.py+tests (13 pass), validation.json correct. research.json/plan.json not created (agent explores then moves on). Code deliverables work; calibration artifacts optional.
- [~] **Test cgroup freeze end-to-end** — PARTIAL: cgroup-freeze-test-001 tested child spawn (4 children, 2 phases) but spawn happened at end-of-phase, not mid-phase. Actual freeze/thaw requires agent to output spawn_children while still executing.
- [x] **Test child spawn and merge** — Verified via T548-v2-fix: 3 children spawned sequentially, each merged, parent completed. See LEARNINGS.md.
- [ ] **Test progressive decomposition** — Implement 4-step protocol (deps → descs → validations → review), verify it catches garbage

## Priority 2: Real work (TaskCore BAYES tasks)
Pick ONE at a time. These test the system with real work:
- [x] T547 — BAYES-10: Define EventTrade formula schema — **DONE** (509 lines formula_schema.py, 203 lines tests, design doc at docs/t547-shared-event-formula-contract-freeze.md dated 2026-04-08)
- [x] T553 — BAYES-16: Implement junction-tree cache invalidation logic — **DONE** (T553-v2: 17m48s, rebased to frontend-scaffold, auto-merged, 363 tests pass)
- [x] T548 — BAYES-11: Implement bounded-treewidth exact inference module skeleton — **DONE** (T548-v2-fix: 32m, 3 child workflows with spawn_children=true, rebased to frontend-scaffold, auto-merged, 363 tests pass)

## Priority 3: Architecture gaps
- [ ] **Progressive decomposition prompts** — Update phase prompts to use 4-step decomposition protocol
- [ ] **Inject child results after thaw** — Parent needs context about what children did when it wakes up
- [ ] **Agent identity scheme** — Implement `role.context.index` naming everywhere (logs, attribution, metrics)
- [ ] **Parallel child execution** — Respect DAG dependencies, run independent children in parallel

## Priority 4: Polish when idle
- [ ] Clean up old worktrees: `git worktree list` and remove stale ones
- [ ] Review LEARNINGS.md, extract patterns into prompts or workflow code
- [ ] Check for stuck workflows: `temporal workflow list --query 'ExecutionStatus="Running"'` >30min same phase
- [ ] Compact any crew sessions approaching context limit

## Done
- [x] cgroup freeze/thaw for mid-phase decomposition (`v2-interruptible-cgroup-2026-04-10`)
- [x] Remove hardcoded `AUTO_DECOMPOSE_THRESHOLD=4`
- [x] Agent-driven decomposition via `spawn_children` in phase prompts
- [x] Workers run in systemd scopes (`systemd-run --user --scope`)
- [x] Split activities: `startInterruptiblePhase` / `resumeInterruptiblePhase`
- [x] Fix codex sandbox mode (`workspace-write` not `read-only`)
- [x] Fix codex prompt syntax (positional, not `-p`)
- [x] Fix Temporal payload size limit (truncate output to 100KB)
- [x] Fix implement prompt — directive step execution with verification, implement-test-001 delivered plan_adherence=1.0

## How to pick work
1. If a workflow is running → monitor it, don't start new work
2. If nothing running → pick from Priority 1 (test infra) until all checked
3. Then Priority 2 (real BAYES tasks)
4. If blocked → Priority 4 (polish)
5. Document everything in LEARNINGS.md
