# Pre-registration — live combinatorial-vs-flat agent forecasting

Timestamped amendments. Everything below the line for an amendment was fixed
*before* the data it governs was collected; anything inspected earlier is
labelled pilot/exploratory and is not confirmatory.

---

## v1 — 2026-07-26 (superseded)

Dual elicitation (flat-interface vs full-interface), flat arm as a local
edge-free `FactoredMarket` initialised to the live net's prices, comb arm on the
live net venue. Estimand: comb-vs-flat aggregate accuracy.

**Retracted defect.** Marginal-agent briefs were rendered with the *current live
price* (`{marginal}` ← `prices[q]`). Under a strictly proper LMSR a trader whose
belief equals the price maximises expected score by not trading (moving the
price to `q` scores `-b·KL(p‖q) < 0`), so all six marginal agents were no-ops,
the flat arm received no information at all, and the advertised
"marginal baseline usable by both arms" did not exist. Found before any
execution; no live data was collected under v1.

---

## v2 — 2026-08-01

### Estimand (frozen)

**Margins-plus-association, under an explicitly imposed additive-evidence
aggregation rule.** We test whether the *combinatorial representation* can
carry an association that the flat representation cannot, when both arms are
driven by the same pre-specified aggregation protocol.

This is deliberately **not** a test of whether the venue, or unconstrained LLM
traders, aggregate marginal beliefs on their own. That is a different
experiment (show each arriving agent the true current price, ask for its
posterior, execute it unmodified, re-elicit per arrival order) and is not what
this design measures. Claims must be scoped accordingly.

### Signals (drawn from `seed` before any price is observed)

* Marginal agents: binary signal of accuracy `alpha = 0.60`, i.e. a log-odds
  shift `delta = log(alpha/(1-alpha)) = log 1.5`, sign `s_i ∈ {-1,+1}` balanced
  within each even-sized question group, residual sign re-drawn per replicate.
* Relational agents: an **odds ratio** `OR = 4.0`, and nothing else. Rendered as
  a conditional pair `(gy, gn)` solved to preserve the marginal exactly
  (`p_A·gy + (1-p_A)·gn = p_G`), so the relational treatment cannot leak into
  the margins the flat arm can trade.
* Frozen common prior `pi0`: one live snapshot, taken at run start, shared by
  both arms. It is the only place live numbers enter.

### Target

The unique joint with the pooled margins (log-odds addition of the marginal
signals against `pi0`) and the pre-registered odds ratio. Computed before
elicitation; never recomputed from observed behaviour.

### Execution adapters (mechanical, applied to every order in every arm)

1. **Marginal adapter.** A stated absolute probability is read as
   "the price I was shown, updated by my private evidence": the runner extracts
   `logit(stated) - logit(shown)` and applies it to the *current* price.
   Log-odds shifts commute, so independent signals compose.
2. **Conditional adapter.** A stated conditional pair is read as a rendering of
   an odds ratio; the runner extracts the odds ratio and re-renders it at the
   *current* margins before execution.

Both are licensed by the v2 briefs, which state the marginal signal as evidence
to be combined ("not a finished forecast that replaces the market price") and
the relational signal as an odds ratio ("if the prices have moved, keep the
4.0x odds ratio, not these two numbers").

### Analysis

* Primary: `delta_KL = KL(target‖flat) - KL(target‖comb)`, reported as the
  distribution over arrival orders (mean and range), not a single order.
* Secondary: decomposition into a margins KL and a signed dependence residual
  (the residual is an attribution, not a KL component — it may go negative).
* Order sensitivity is reported for both arms and is part of the result.

### Retraction carried forward

An earlier dry run reported `delta_KL = +0.050` from a single arrival order.
An order sweep showed the v1/v2-pre-adapter protocol did not aggregate at all:
`set_marginal` to an absolute probability at `alpha = 1.0` is last-writer-wins,
so the final price was simply the last trader's number. Over 200 random orders
the comb arm's KL ranged 0.00003–0.16456 and comb won only 155/200; the
original figure was an artefact of the pre-registered sign draw happening to
place both negative signals last. **That number is withdrawn.** Any result
computed by re-interpreting v1-brief responses under the v2 adapters is
pilot-only; confirmatory numbers require fresh elicitation under the v2 briefs.

### Known residual

The conditional adapter is a state-dependent projection, so it does not commute
with later marginal updates: the comb arm retains order-dependence of order
0.014 against an effect of ~0.05. A fully invariant implementation would act on
the joint's log-odds-ratio coordinate directly, which the conditional-probability
interface does not expose; batching all reports before execution is the
practical alternative. This is reported, not hidden, and a tolerance should be
pre-registered before the confirmatory run.

### Still required before `execute=True`

- [x] Fresh elicitation under the v2 briefs (pilot numbers retired)
- [x] This amendment, written before scoring the fresh elicitation
- [x] Exhaustive (not sampled) order enumeration: the relevant space is which
      SUBSET of marginal trades precedes each relational trade (a first attempt
      that only varied relational *positions* was not exhaustive and was
      corrected). All 2^12 = 4096 subsets enumerated: comb KL 0.00015-0.01419,
      delta_KL +0.036 to +0.050, comb closer in 4096/4096 — worst case, not a
      sample. The 200-draw random sweep had already found the same worst case.
- [x] Unit tests for both adapters and the order-invariance property
      (`test_adapters.py`, 7/7: marginal-preserving rendering, odds-ratio
      preservation under re-expression, exact flat-arm order invariance,
      last-writer-wins pinned as a regression, flat arm cannot express
      dependence, arms start identical, target normalized)
- [x] Replicates with fresh elicitation (3 total, distinct pre-registered sign
      draws, mixed sonnet/haiku/opus, model-to-role rotated across replicates):
      delta_KL = +0.050 / +0.050 / +0.056, comb near-exact on target in all
      three. Relational agents declined to trade in the flat interface in 9/9
      elicitations across replicates. The comb-interface no-op observed earlier
      is STOCHASTIC, not model-deterministic: across haiku comb trials it was
      empty/trade/empty — report as a no-op rate, not a capability claim.
- [x] Live-path implementation checks (read-only, against api.futarchy.ai):
      preview stake matches the closed-form b*log((1-p)/(1-q)) to 4 dp (the
      engine's rounding of the returned fill); target==price previews a ~0.005
      stake (harmless; the runner's 1e-4 tolerance skips such orders anyway);
      targets 0.0/1.0 rejected with a clean 400 invalid_target; extreme
      0.001/0.999 accepted with bounded ~300-credit stakes; conditional
      preview quotes the live conditional price correctly.
- [ ] Cost ceiling and capped canary before the full run
