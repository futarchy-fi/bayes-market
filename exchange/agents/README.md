# exchange/agents — resident coherence agent

`arb.py` keeps economically identical listings near a configured reference
venue. NET is the default reference, but it is a tradable signal, not an
oracle or ground truth. The agent runs report-only unless `--execute` is set.

Only listings with identical payouts, oracle, condition, resolution criteria,
outcome mapping, and VOID payoff may share an instrument. Creating an
instrument is currently the administrator's assertion that this is true; the
agent never infers equivalence from titles. See
[Market contracts and settlement](../../docs/market-contracts-and-settlement.md).

## Safety contract

- Exact YES/NO markets only; other outcome sets are rejected. A reference may
  be `net`, `amm`, or `book`; a book reference requires both a best bid and
  best ask.
- A NET response must contain a fresh server-observation `observedAt`; this
  detects cached responses, not an economically stale belief that the server
  still considers current. Execution needs two nearby valid reference samples
  before use (a mutation-free report may preview the first).
  Non-finite/out-of-range samples are ignored,
  one jump larger than `ANCHOR_MAX_JUMP` is held for confirmation, and accepted
  samples feed an EMA (`ANCHOR_ALPHA`). In-memory confirmation intentionally
  warms up again after restart or a long observation gap.
- AMM orders use the dedicated atomic `buy-to-price` endpoint. An older API
  returns 404 instead of silently ignoring its required safety fields. The
  server rereads the live market under its lock, no-ops after a crossing,
  limits the selected outcome's move, enforces a per-listing gross-share cap,
  and never debits more than the submitted budget. Executed actions record the
  returned debit.
- `INSTRUMENT_BUDGET_CAP` is shared by all new AMM debits in one instrument
  tick. It is also bounded by `available - MIN_BALANCE`.
- `INVENTORY_CAP` is split equally across the AMM listings the agent may trade,
  and the server enforces each resulting per-listing limit atomically.
- The first pass never posts order-book liquidity. It cancels the account's
  existing live book orders for registered listings before sampling a
  reference. A book may still be configured as a read-only reference when it
  has both a best bid and best ask.
- Remote failures are isolated per instrument. Repeated erroring passes back
  off exponentially up to `ARB_BACKOFF_CAP`.

These are play-credit limits, not a claim that the strategy is risk-free.
The instrument budget resets each tick and simultaneous agent processes can
multiply it. The inventory allocation covers the follower AMMs traded in the
current registry; it does not unwind legacy or reference-venue holdings. There
is still no portfolio-wide loss cap, durable anchor history, or hedge on the
reference venue.

## Configuration

| Option / environment | Default | Meaning |
| --- | ---: | --- |
| `--reference-venue` / `REFERENCE_VENUE` | `net` | `net`, `amm`, or `book` |
| `ANCHOR_ALPHA` | `0.3` | Weight of a confirmed sample in the EMA |
| `ANCHOR_MAX_AGE` | `120` | Maximum observation age/gap in seconds |
| `ANCHOR_MAX_JUMP` | `0.10` | One-sample reference jump requiring confirmation |
| `SPREAD_THR` | `0.02` | AMM gap required before action |
| `MAX_PRICE_MOVE` | `0.02` | Maximum selected-outcome movement per AMM action |
| `BUDGET_CAP` | `25` | Maximum debit for one AMM action |
| `INSTRUMENT_BUDGET_CAP` | `25` | New AMM debit budget per instrument tick |
| `INVENTORY_CAP` | `50` | Gross shares split across traded listings |
| `MIN_BALANCE` | `50` | Available-credit reserve |
| `ACTION_CAP` | `10` | Action ceiling before new trades stop; safety cancellations may exceed it |

`scripts/arb/repro_overshoot.py` demonstrates bounded thin/deep AMM
convergence; `scripts/arb/repro_anchor_manipulation.py` demonstrates the
reference filters. The reference user unit is `deploy/futarchy-arb.service`.
