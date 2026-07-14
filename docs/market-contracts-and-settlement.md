# Market contracts and settlement

Status: product direction. This document describes where the exchange should
go; it is not a claim that every field or workflow exists today.

## Product model

A prediction market is judged by its declared oracle (resolver). The oracle
may resolve the contract to an outcome or VOID under the published resolution
criteria. The protocol enforces who may resolve; it does not decide whether the
oracle exercised good judgment.

Two markets may ask the same real-world question while using different oracles
or criteria. They are different contracts and may rationally trade at different
prices. A trusted default index may hide contracts from unknown oracles, but
curation must not change who owns settlement authority.

For now, administrators may override settlement because all balances are test
credits. An override should eventually be recorded as an admin action rather
than presented as the oracle's decision. The settlement source may later move
on-chain without changing the contract or listing model below.

## Terms and invariants

- A **topic** is an optional discovery grouping. Sharing a topic does not make
  two markets economically interchangeable.
- A **contract** fixes the question, outcomes, oracle, resolution criteria,
  optional condition, outcome mapping, and VOID payoff.
- A **listing** is one venue's tradable instance of a contract.
- A **venue** owns its matching rule, liquidity, orders or positions, and local
  settlement accounting.

Creator, liquidity funder, oracle, and listing curator are separate roles,
even when one account performs several of them in the current implementation.

Once trading begins, the contract's oracle, criteria, outcomes, condition, and
VOID payoff should be immutable. Different values imply a different contract
identifier. Only listings of the same contract may be presented as fungible or
used for automatic cross-venue arbitrage.

Closing trading, resolving to an outcome, declaring VOID, and calling off a
conditional exposure are distinct operations. A deadline does not imply VOID
unless the contract says that its condition fails at the deadline.

## Conditional contracts

For a materialized contract `X if Y` where the contract requires `Y = true`:

- If Y resolves true, wait for X and settle from X.
- If Y resolves false, the conditional contract resolves VOID with reason
  `condition_false`; its stake is returned.
- If X resolves before Y, keep the contract pending until Y resolves.
- If Y itself is declared VOID, follow the contract's explicit upstream-VOID
  policy.

The current NET venue does not materialize `X if Y` as a separate market. It
attaches context to an individual order: a contradictory Y marks that order
`called_off` and releases its full lock while leaving the X and Y markets
unchanged; X arriving first leaves the order `awaiting_context`. This is the
right economic result for that exposure, but it is not a market-level VOID.
The durable contract model should preserve both distinctions rather than
collapsing them into `closed`.

## Target architecture

The destination is one control plane above multiple execution venues:

```text
accounts · contract catalog · portfolio view · resolution log · curation
                                |
              +-----------------+-----------------+
              |                 |                 |
          Bayes net A       AMM / book        Bayes net B
        own liquidity      own liquidity      own liquidity
```

The control plane should eventually hold three identities:

1. `topicId`: optional discovery grouping.
2. `contractId`: immutable resolution terms and oracle.
3. `listingId`: a venue instance and its local market identifier.

A resolution is appended once for a contract and delivered idempotently to
each listing through the venue's existing settlement adapter. Partial delivery
must be visible and retryable; it need not be a distributed transaction.
Multiple venue instances and multiple Bayes nets may coexist, each with its own
graph, mechanism state, and liquidity.

Default discovery belongs to a separate curated index of trusted oracle
principals. Unlisted contracts remain addressable, and listing policy never
grants or removes settlement authority.

## Practical migration

The first pass deliberately uses existing market metadata and detail routes:

- New self-serve AMM and book markets can state human-readable resolution
  criteria.
- Their authenticated creator identity is published as the current oracle.
- Venue panels show the oracle and criteria before a trade.
- Creator authority to resolve YES, NO, or VOID remains unchanged.

This pass does not change deadline automation. The current AMM expiry
reconciler automatically voids non-creator markets at their deadline while
leaving creator-resolved markets open. That legacy distinction is not the
target contract model: a later, versioned migration should replace it with an
explicit per-contract expiry policy without rewriting live market terms.

The current NET API does not yet publish per-market oracle or criteria fields.
The UI should report that absence rather than borrowing terms from an AMM or
book listing with the same title.

In this first pass, the terms remain generic metadata and administrators can
still edit that metadata. Immutability and an append-only override history
belong to the later contract catalog; the UI must not imply they exist yet.

Next, evolve the existing instrument registry into the contract catalog. Add a
contract identity covering oracle, criteria, condition, outcome mapping, and
VOID payoff; backfill existing markets conservatively; and gate automatic
arbitrage on exact contract identity. Then add the shared resolution log and
per-listing delivery.

This direction does not require one matching engine, one global Bayes net,
pooled liquidity, on-chain settlement today, or automatic equivalence based on
question text.
