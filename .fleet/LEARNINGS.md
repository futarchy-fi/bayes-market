# Fleet Learnings

Document what breaks and how you fixed it. This becomes institutional knowledge.

## Format
```
### [DATE] Issue title
**Symptom:** What you observed
**Root cause:** Why it happened  
**Fix:** What you did
**Prevention:** How to avoid in future
```

---

### [2026-04-11] epistemicExecutor delivers production code (T553, T548)

**Success:** Two complex BAYES tasks completed autonomously via epistemicExecutor workflows:
- T553 (cache invalidation): 12m39s, created cache.py + 21 tests, all pass
- T548 (junction tree skeleton): 13m13s, created junction_tree.py (440 lines) + 25 tests, all pass

**What worked:**
1. Directive prompts ("YOU MUST create") produce reliable code output even when JSON artifacts are skipped
2. Complex questions.json files show deep problem understanding (T548 had 7 design questions about graph contracts, treewidth bounds, protocol extensions)
3. Code follows existing patterns (thread-safe cache, proper contracts, comprehensive tests)
4. Total 388 tests pass after both deliveries

**Key insight:** Middle phase artifacts (research.json, plan.json) are nice-to-have for calibration, but the workflows reliably produce working code and tests. Focus on deliverable quality over artifact completeness.

---

### [2026-04-11] T553/T548 base-divergence bug — RESOLVED

**Issue:** T553 and T548 forked from futarchy-fleet instead of frontend-scaffold. Merge shows 12+ conflicts.

**Fix:** Re-fired both beads with `baseBranch: "frontend-scaffold"` in workflow input.

**Result:**
- T553-v2: Completed in 17m48s, cache_invalidation.py (2398 bytes), 5 tests, auto-merged
- T548-v2-fix: Completed in 32m with 3 child workflows (spawn_children=true), auto-merged

**Key insight:** The workflow input requires `repo` parameter for worktree creation: `{"taskId": "...", "repo": "/home/kelvin/bayes-market", "baseBranch": "frontend-scaffold", ...}`. Missing `repo` causes "cannot change to 'undefined'" error.

---

### [2026-04-11] Child workflow decomposition works

**Success:** T548-v2-fix workflow used spawn_children=true and successfully coordinated 3 child workflows:
1. r1-multi-variable-cliques: Multi-variable clique building and treewidth computation
2. r2-server-migration: Migrate server synthetic helpers to inference module
3. r3-test-coverage: Bounded-treewidth test coverage

**Observations:**
- Parent workflow waited for each child to complete before spawning next (sequential, not parallel)
- Each child ran its own 4-phase epistemicExecutor (question→research→plan→execute)
- Children merged their branches, parent merged the final combined result
- Total time: 32 minutes for complex task with 7 planned steps split across 3 children

**What worked:**
- Plan phase correctly identified decomposition opportunity
- Children received focused scope (steps 1-3, 4-5, 6-7 respectively)
- All 363 tests pass after final merge

**Prevention:** Complex tasks with 5+ steps should consider decomposition. Plan phase spawn_children=true enables parallel/sequential child execution.

---

### [2026-04-11] Multi-phase child spawn test (cgroup-freeze-test-001)

**Success:** Designed to test cgroup freeze mid-phase decomposition, but demonstrated multi-phase child spawning instead:
- 4 children spawned across question (2) and research (2) phases
- ~15 minutes total execution
- Created test_alpha.py and test_beta.py as requested

**Observations:**
- spawn_children triggered at END of each phase, not MID-phase
- No actual cgroup freeze/thaw occurred (freeze is for mid-execution spawn)
- Agent correctly identified independent subtasks and decomposed
- Children ran their own 4-phase epistemicExecutor cycles

**What this tested:**
- ✓ Child workflows at multiple phases (question, research)
- ✓ Sequential child execution
- ✓ Parent resume after children complete
- ✗ Actual cgroup freeze/thaw (requires mid-phase spawn_children output)

**Key insight:** End-of-phase decomposition (spawn_children in final output) works reliably. Mid-phase decomposition (agent calls spawn while executing) requires different triggering — agent must stream spawn_children before completing the phase.

---

### [2026-04-11] Workflow worktrees lack dependencies

**Symptom:** bayes-build-fix-001 workflow reported "tsc -b passes clean" but manual build in the same branch fails with TypeScript errors.

**Root cause:** Fresh worktrees don't have node_modules installed. The workflow ran `tsc -b` which likely failed silently or exited before TypeScript found the config. The agent analyzed the source code but couldn't actually run the build.

**Fix (manual):** Added non-null assertion `defaultMarkets[0]!` to fix the actual build error. The workflow correctly identified the issue (noUncheckedIndexedAccess) but couldn't verify the fix.

**Prevention:** 
1. Workflows should run `pnpm install` before build verification
2. The implement prompt mentions "Fresh worktree — install before testing" but question/research phases don't
3. Consider adding dependency installation as a setup step in epistemicExecutor

---

### [2026-04-11] Codex sandbox mode prevents file writes

**Symptom:** epistemicExecutor phases completed in <1 second without producing output files (questions.json, plan.json, etc.)

**Root cause:** `interruptible-handoff.ts` used `--sandbox read-only` which prevents codex from writing files.

**Fix:** Changed to `--sandbox workspace-write` in both `interruptible-handoff.ts:56` and `worker-scope.ts:56`.

**Prevention:** Valid codex sandbox modes are: `read-only`, `workspace-write`, `danger-full-access`. For autonomous workflow execution, use `workspace-write`.

---

### [2026-04-11] Codex -p flag is for profiles, not prompts

**Symptom:** Error `config profile "..." not found` when running codex exec.

**Root cause:** Code used `codex exec -p "prompt"` but codex uses `-p` for config profiles. The prompt is a positional argument.

**Fix:** Changed from `${claudeCmd} -p "${message}"` to passing prompt as positional argument for codex.

**Prevention:** For codex: `codex exec "prompt"` or `echo "prompt" | codex exec -`. For claude: `claude -p "prompt"`.

---

### [2026-04-11] Temporal payload size limit exceeded

**Symptom:** Workflow failed with "Complete result exceeds size limit" when codex output grew large (750KB+).

**Root cause:** `startInterruptiblePhase` returned the full worker output in the activity result, exceeding Temporal's ~2MB payload limit.

**Fix:** Added output truncation (100KB limit) in `interruptible-handoff.ts` with note pointing to full output file location.

**Prevention:** Never return large files in Temporal activity results. Return file paths instead, let workflow read what it needs via separate activities.

---

### [2026-04-11] Phase outputs not reliably created

**Symptom:** Workflow completes all 4 phases successfully (status=done), but JSON files (questions.json, plan.json, validation.json) are inconsistently created. Task deliverables also not created.

**Root cause:** Complex phase prompts with multiple responsibilities. Codex explores codebase extensively but doesn't reliably execute the "Write your output to X.json" instruction.

**Fix:** TBD - options include:
1. Simplify prompts to single responsibility per phase
2. Use structured output mode (`--json` on codex) to capture JSON directly
3. Add explicit file creation commands at end of prompts
4. Use Claude Code instead of Codex for better instruction following

**Prevention:** Test prompts in isolation before integrating. Monitor for phase output file existence as part of workflow health checks.

---

### [2026-04-11] Claude stream-json requires --verbose

**Symptom:** Claude command exits immediately with "requires --verbose" error.

**Root cause:** `claude --output-format stream-json` requires `--verbose` flag.

**Fix:** Added `--verbose` to Claude command in `interruptible-handoff.ts`.

**Prevention:** Test CLI commands manually before integrating. Check CLI help for required flag combinations.

---

### [2026-04-11] Codex requires OPENAI_API_KEY environment variable

**Symptom:** Codex workflows complete quickly without producing outputs. Worker logs show 500 errors followed by 401 Unauthorized.

**Root cause:** `OPENAI_API_KEY` environment variable is not set. Codex cannot authenticate with OpenAI API.

**Fix:** Either:
1. Set OPENAI_API_KEY in worker service environment
2. Switch to Claude provider (uses Anthropic API which is configured)

**Prevention:** Verify API credentials before deploying new providers. Add health checks that test actual API connectivity.

---

### [2026-04-11] Implement phase doesn't execute planned tasks

**Symptom:** Workflow creates plan.json with correct steps, but execute phase doesn't create the planned deliverables. Phase completes but actual task not done.

**Root cause:** The implement prompt says "follow the steps in plan.json" but doesn't enforce execution. Claude reads the plan but doesn't reliably execute it.

**Fix options:**
1. Add explicit verification step in implement prompt ("After each step, verify the file exists")
2. Add post-phase checks that fail the workflow if deliverables missing
3. Make prompts more directive ("You MUST create file X before stopping")
4. Consider splitting implement into smaller, more focused phases

**Prevention:** Test end-to-end task completion, not just phase artifact creation. Add deliverable verification as part of workflow success criteria.

---

### [2026-04-11] Implement prompt too permissive — deliverables not created

**Symptom:** claude-test-003 created plan.json with correct steps, but execute phase didn't create the planned files (src/hello.txt). Phase completed but actual deliverables missing.

**Root cause:** Implement prompt said "follow the steps" but didn't enforce explicit step-by-step execution with verification.

**Fix:** Rewrote implementPrompt in epistemicExecutor.ts to:
1. Require explicit step announcements: "=== Step N: {task} ==="
2. Require verification after each step
3. Add "DO NOT STOP until ALL steps are executed"
4. Add implementation.json artifact requirement with files_created/modified per step

**Result:** implement-test-001 workflow achieved plan_adherence=1.0, all 3 planned steps executed, both src/greeting.py and tests/test_greeting.py created and tests passing.

**Prevention:** Implement prompts must be directive, not suggestive. Require explicit step-by-step execution with announcements and verification. Add structured output artifact (implementation.json) to track what was actually done.

---

### [2026-04-11] Question/Research phases still don't produce JSON artifacts

**Symptom:** implement-test-001 created plan.json and validation.json, but questions.json and research.json were not created.

**Root cause:** Question and research prompts follow same pattern as original implement prompt — they say "write to X.json" but don't enforce it.

**Fix (pending):** Apply same directive pattern to questionPrompt and researchPrompt:
1. "YOU MUST write to .fleet/tasks/ID/questions.json before stopping"
2. Add explicit file existence verification requirement
3. Consider adding explicit Write tool call instruction

**Prevention:** All phase prompts need the same level of directiveness. The pattern from implement prompt should be applied uniformly.

---

### [2026-04-11] Claude CLI -p flag is --print, not prompt

**Symptom:** Command `claude -p "prompt"` treated -p as requiring a prompt argument.

**Root cause:** `-p` is shorthand for `--print` (non-interactive mode), not for passing a prompt. The prompt is a positional argument.

**Fix:** Correct syntax is `claude -p --output-format stream-json --verbose "prompt"` where prompt comes last as positional.

**Prevention:** Check `claude --help` — prompts are always positional arguments, not flag values.

---

### [2026-04-11] Shell escaping breaks complex prompts with JSON/backticks

**Symptom:** Research/plan phases got "Error: When using --print, --output-format=stream-json requires --verbose" even with --verbose present.

**Root cause:** Prompts containing JSON examples, backticks, and special characters broke shell quoting. The shell mangled the command before Claude received it.

**Fix:** Write prompt to a file, pass via stdin using `--input-format text`:
```bash
claude -p --verbose --output-format stream-json --permission-mode bypassPermissions --input-format text < prompt.txt
```

**Prevention:** Never pass complex prompts inline. Always write to file and use stdin redirection.

---

### [2026-04-11] First phase works, subsequent phases fail (RESOLVED)

**Symptom:** Question phase creates questions.json successfully, but research/plan phases don't create their JSON artifacts.

**Root cause:** Subsequent phases DO run (commits appear in git log), but Claude doesn't reliably create the intermediate JSON files. The agent explores, commits as "analysis:", and moves on without writing research.json or plan.json.

**Fix (partial):** The workflow still completes successfully — code deliverables (counter.py, tests) are created and tests pass. Validation phase correctly identifies the missing artifacts and scores plan_adherence=0 due to missing plan.json.

**Observations from debug-test-001:**
- questions.json: Created ✓ (2373 bytes, 3 questions, 5 assumptions)
- research.json: NOT created (phase ran, committed as "analysis")
- plan.json: NOT created (phase ran, committed as "analysis")
- counter.py: Created ✓ (813 bytes, proper Counter class)
- test_counter.py: Created ✓ (1623 bytes, 13 tests, all pass)
- validation.json: Created ✓ (verdict: changes_requested, correctly noted missing artifacts)

**Status:** Workflow completes successfully with real deliverables. Middle artifacts (research/plan) are nice-to-have for calibration but not blocking. Consider simplifying to 3 phases (question → execute → validate) if artifact reliability doesn't improve.

---

### [2026-04-11] Validation bypass allows bad merges — BUG

**Symptom:** task-simple-file-001 merged with phase="done" but created ZERO source files. Only .fleet/tasks artifacts exist in the merge.

**Root cause:** epistemicExecutor.ts:618-621 only rejects if `valParsed.verdict === "reject"`. If validation.json doesn't exist (valParsed is null), the condition is false and merge proceeds:
```typescript
if (valParsed && valParsed.verdict === "reject") {
  return await cancelWorkflow(...);
}
```

**Impact:** Workflows can auto-merge without creating any deliverables if the validation phase fails silently (doesn't produce validation.json).

**Proposed fix:**
```typescript
if (!valParsed || valParsed.verdict !== "approve") {
  return await cancelWorkflow(`Validation ${!valParsed ? 'missing' : 'rejected'}: ${valParsed?.reason ?? 'no validation output'}`);
}
```

**Prevention:** Require explicit "approve" verdict, not just absence of "reject". Missing validation output should fail, not pass.

---

### [2026-04-11] Validation fix confirmed — workflows now produce real deliverables

**Success:** After fixing the validation bypass bug, workflows consistently create deliverables:

- task-validation-test-001: Created hello.txt, all artifacts (questions/research/plan/implementation/validation), merged successfully
- task-analytics-test-002: Created Analytics.test.tsx (8 tests, 159 lines), merged successfully, 62 tests now pass (up from 54)

**What worked:**
1. Changed validation check from `if (valParsed && verdict === "reject")` to `if (!valParsed || verdict !== "approve")`
2. This forces workflows to fail if validation.json is missing or if verdict is not "approve"
3. Agents now reliably create both intermediate artifacts AND final deliverables

**Key insight:** The permissive "fail only on explicit reject" allowed silent failures to merge. Strict "require explicit approve" catches both missing validation output and any non-approval verdict.

---

### [2026-04-11] Workflows reliably produce test coverage at scale

**Success:** After fixing validation bypass, ran 15+ epistemicExecutor workflows in sequence, all producing real deliverables:
- Frontend tests: 54 → 204 (278% increase)
- New test files: Analytics, marketListFilters, ui-components, session, TradingPanel, AnalyticsSummaryCards, chartUtils, AssumptionContext, ProbabilityBar, TraderLeaderboard, AnalyticsFilters, VolumeChart
- Total: 567 tests (204 frontend + 363 backend)

**What worked:**
1. Clear, focused task descriptions with specific file paths
2. Pattern references ("Follow patterns from X.test.tsx")
3. One component/module per workflow
4. Validation fix ensuring only approved work merges

**Key insight:** Small, focused tasks (one test file each) have near-100% success rate. Complex multi-file tasks occasionally fail validation. Prefer decomposition.

**Final session stats (2026-04-11):**
- Frontend tests: 54 → 281 (420% increase)
- Test files: 9 → 27 (22 new files added)
- Total: 644 tests (281 frontend + 363 backend)
- ~25 workflows executed, all successful after validation fix

---

### [2026-04-11] Continued test coverage sprint

**Success:** Eight test coverage workflows completed via epistemicExecutor:
- task-discussion-thread-002: DiscussionThread.test.tsx (14 tests)
- task-bayes-net-graph-001: BayesNetGraph.test.tsx (13 tests)
- task-junction-tree-001: JunctionTreePanel.test.tsx (13 tests)
- task-portfolio-coverage-001: Portfolio.test.tsx expanded (20→310 lines, +9 tests)
- task-create-market-coverage-001: CreateMarketForm.test.tsx expanded (44→346 lines, +16 tests)
- task-system-coverage-001: System.test.tsx expanded (82→209 lines, +9 tests)
- task-market-detail-coverage-001: MarketDetail.test.tsx expanded (108→446 lines, +8 tests)

**Session stats:**
- Frontend tests: 304 → 410 (+106 tests)
- Total: 773 tests (410 frontend + 363 backend)
- All 10 workflows completed successfully with auto-merge

**Key learning:** Task queue mismatch causes workflows to hang at WorkflowTaskScheduled. Worker listens on `fleet-tasks`, not `fleet-bead`. Always verify task queue matches worker config.


### [2026-04-11] Progressive decomposition gap identified

**Current state:** epistemicExecutor spawn_children uses simple `{id, title, description}` — no dependency tracking, no validation criteria.

**Gap:** 4-step protocol (deps → descs → validations → review) would add: deps field for child-to-child dependencies, validation_criteria per child, review phase before committing to spawn.

---

### [2026-04-11] Progressive decomposition schema shipped via epistemicExecutor

**Success:** task-progressive-decomp-001 workflow completed in 13 minutes with auto-merge to temporal-fleet main.

**What was delivered:**
- validation_criteria field added to ParsedChildInput, RawChildInput, AnalysisDecomposeChild types
- Parsing logic with default "No specific criteria" for backward compatibility
- Self-review instruction in buildPrompt for decomposition quality
- 105 lines of new tests (analysisDecompose.test.ts)
- All 6 planned steps executed with 0.95 plan_adherence

**Key insight:** The original task description targeted epistemicExecutor.ts, but the workflow correctly identified that analysisDecompose.ts was the actual target file. The research phase re-scoped based on actual codebase structure.

**Validation quality:** Caught 3 missed questions (naming convention, backward compatibility, API exposure) but approved because implementation handled them correctly without explicit questions.

---

### [2026-04-11] Child context injection shipped via epistemicExecutor

**Success:** task-child-context-injection-001 workflow completed in 18m33s with auto-merge to temporal-fleet main.

**What was delivered:**
- New childSummaries.ts activity (50 lines) + tests (102 lines)
- parentLifecycle: child summaries passed to analysisDecompose for re-decomposition rounds
- recursiveLifecycle: integration prompt now has rich child summaries instead of bare ID lists
- child-summaries.json artifact for debuggability
- 0.85 plan_adherence, all 10 tests pass

**Key insight:** Research phase correctly identified that the task description referenced epistemicExecutor, but the actual codebase uses parentLifecycle/recursiveLifecycle. The workflow re-scoped automatically.

**Minor issue found:** formatChildSummaries() is exported and tested but never called by workflows (dead code). Both workflows duplicate the formatting logic inline.

---

### [2026-04-11] Agent identity scheme shipped via epistemicExecutor

**Success:** task-agent-identity-001 workflow completed in 17min with auto-merge to temporal-fleet main.

**What was delivered:**
- New agentIdentity.ts module (97 lines) with parseIdentity/formatIdentity/makeIdentity utilities
- 17 unit tests for identity parsing, formatting, round-trips
- sender_id in notifyAgent updated to use dotted identity format
- Log prefixes now include agent identity
- Workflow state threading for agentIdentity

**Decisions captured:**
- Context = taskId for workers, domain for persistent agents
- CAO session naming kept separate from agent identity
- AgentIdentity type lives in temporal-fleet, not shared package

**Minor gaps noted:** DAG child identity threading not fully implemented; notifyAgent callers not yet passing agentIdentity.

---

### [2026-04-11] Parallel child execution shipped via epistemicExecutor

**Success:** task-parallel-children-001 workflow completed in 24m35s with auto-merge to temporal-fleet main.

**What was delivered:**
- New parallelChildren.ts module (218 lines) with computeTopoRounds and executeChildrenInParallel
- 11 new tests for topological sorting, dependency mapping, and parallel execution
- parentLifecycle and recursiveLifecycle refactored to use parallel execution with round-based DAG scheduling
- dagExecutor now imports shared computeTopoRounds

**Key insight:** Research phase corrected the task premise — found that dagExecutor already had parallel execution, so the task became extracting that pattern into a shared module for parentLifecycle/recursiveLifecycle.

**Architecture:** Children grouped into topological waves (wave 0 = no deps), waves execute in parallel, waves run sequentially, branch merging done via onRoundComplete callback.

---

### [2026-04-11] Missing fleetSlug causes auto-merge failure

**Symptom:** Workflow task-fix-pr5-ts-errors-001 completed (phase="done") but branch was `undefined/Tfix-pr5-ts-errors-001` and merge activity failed.

**Root cause:** Workflow input lacked `fleetSlug` parameter. Branch name is computed as `${fleetSlug}/T${taskId}` — undefined fleetSlug → literal "undefined" in branch name. Merge target mismatch.

**Fix:** Manual merge of branch to frontend-scaffold, then delete branch.

**Prevention:** Always include `fleetSlug: "fleet"` (or appropriate value) in epistemicExecutor workflow input. Add input validation to reject undefined fleetSlug.

---
