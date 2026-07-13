# arb/ — coherence scanner + relbot v0

Read-only tooling that treats the bayes-market joint and external platforms
(Manifold, Metaculus) as one ecosystem and looks for incoherence between them
and inside them. Mechanism sketched by Gurkenglas (LessWrong) in conversation,
2026-07-12; staged here as the proof-organ for the oracle thesis: *the joint's
value is structure, and structure is checkable — and tradeable — everywhere.*

Both scripts are stdlib-only (plus `certifi` if your Python lacks a CA
bundle) and never trade: no API keys, no writes, no side effects.

Bayes reads now default to the exchange at `BAYES_API_URL` (default `http://127.0.0.1:3210`).
Use `--paper` or `BAYES_BACKEND=paper` to compare against the legacy paper backend.

## scan_manifold.py — the sensor

For every live bayes-market with an `anchor`, fetch the CURRENT external
forecast and report:

- divergence between the joint's price and the external price,
- anchor staleness (drift since seed import),
- externals that resolved/closed while bayes still prices them open.

```bash
python3 scripts/arb/scan_manifold.py --out /tmp/scan.json
```

First full run (2026-07-12): 337 Manifold anchors compared, mean |gap| 0.1pp,
zero gaps >5pp — expected, since the joint was seeded from these markets on
07-04 and has had 91 trades since. One resolution gap found ("AGI before July
1st 2026" resolved NO on Manifold, still open here). The 62 Metaculus anchors
need `METACULUS_TOKEN` (their API went auth-only).

## relbot.py — the relationship-order engine (v0)

The core mechanism: a **book of logical relationships** between markets, and
a **solver** that checks whether live AMM prices admit a bundle whose payoff
at resolution is ≥ its cost in *every* consistent world.

- Book sources: auto-detected same-title equivalence candidates
  (cross-creator duplicates), auto-detected by-year implication ladders
  (within one creator's series, "by 2027" ⇒ "by 2028"), and user-declared
  entries (`--book relationships.json`, entries
  `{type: implies|equiv, a, b, declaredBy}`).
- Bundles: `A⇒B` violated (`P(A)>P(B)`) → buy B-YES + A-NO; `A≡B` spread →
  buy cheap-YES + dear-NO. Each unit pair pays exactly 1 in every consistent
  world.
- Sizing integrates Manifold's Maniswap (cpmm-1) curve. The pool model is
  **verified against each market's displayed probability before being
  trusted** (first run: 338/338 reproduced, 0 dropped); profit is maximized
  over bundle size net of slippage.

```bash
python3 scripts/arb/relbot.py --min-profit 0.5 --out /tmp/relbot.json
```

First full run (2026-07-12): 46 relationships, 4 violated, 3 bundles clear
the slippage floor, **45.6 mana payable at resolution *if* the declared
relationships hold**, largest an 11.2pp gap between IsaacKing's Minecraft-AGI
benchmark market and Gabrielle's copy (+26 mana).

### Evan Daniel 2x2 joint marginals

`relationships_evand.json` vendors a transformed snapshot of Evan Daniel's
curated [`evand/conditional-markets`](https://github.com/evand/conditional-markets)
2x2 Manifold markets and is loaded automatically. Its `joint_marginal`
relations report each joint's A/B marginals and any declared standalone-binary
gaps; they are report-only and never construct bundles. The source dataset is
used with attribution under its MIT license.

Read honestly, this is closer to a negative result than a harvest: every
surviving bundle is a cross-creator duplicate, so its "every consistent
world" guarantee is conditional on an equivalence the resolver explicitly
does not guarantee (caveat 1), while the unconditional class — within-creator
ladders — shows no alpha at snapshot time (caveat 3). v0's real finding is
that *snapshot* coherence-arb on Manifold is already priced; the value lives
in the continuous loop and in pricing resolver risk itself.

## Caveats found by the first run (they are the roadmap)

1. **Resolver risk.** All three profitable bundles are cross-creator
   duplicates; e.g. Gabrielle's market states it "resolves based on my
   judgment instead of @IsaacKing's… not guaranteed" — so the 11pp gap is the
   market's price for resolver risk, not free money. Pricing exactly that
   risk is what a *market in relationship declarations* ("A≡B at 90%") would
   do — the unbuilt core of the mechanism.
2. **Capital lock.** Bundles are riskless *at resolution*, but capital sits
   until then (2027–2035). This is why platform credit against provably-safe
   books matters ("infinite loans free liquidity") — and sizing that credit
   for >2 correlated markets is an open math problem.
3. **Coherence-by-stasis.** Within-creator ladders (the truly riskless
   class) are coherent to <1pp today; that alpha appears in news bursts.
   The bot must be a loop, not a snapshot.
4. **Fees are unverified.** The trust gate validates the *pricing* function
   (pool state → displayed probability); a fee applied at bet time would sit
   outside that check and quietly eat the margin on every bundle. Irrelevant
   while the bot never trades — must be settled (docs check or a 1-mana probe
   bet) before the execution layer ships.

## Staging

- [x] v0: sensor + relationship book + verified-slippage solver (this PR)
- [ ] continuous loop + alerting on violations
- [ ] execution layer (Manifold API key, mana-capped, dry-run first)
- [ ] general CNF solver (arbitrary formulas, LP over consistent worlds) —
      the engine's own `backend/formula_schema.py` CNF shape is the target
      declaration language
- [ ] declaration market / bot-as-mini-platform (deposits + statements +
      attribution of profit to declarers)
