from copy import deepcopy
from decimal import Decimal

from exchange.venues.batch.engine import BatchEngine, BatchVenue
from exchange.venues.contract_suite import VenueContractSuite


class TestBatchVenueContract(VenueContractSuite):
    supports_snapshot_roundtrip = True

    def make_venue(self, risk_engine):
        venue = BatchVenue(BatchEngine(risk_engine))
        venue.create_market("Contract market", b=Decimal("10"))
        return venue

    def sample_quote_payload(self, venue):
        return {
            "marketId": venue.market_ids()[0],
            "outcome": "yes",
            "target": "0.7",
            "maxSpend": "5",
        }

    def sample_resolvable(self, venue):
        venue.close_round(venue.market_ids()[0])
        return venue.market_ids()[0], "yes"

    def restore_venue(self, snapshot, risk_engine):
        return BatchVenue.from_snapshot(snapshot, risk_engine)

    # Batch placement is deliberately sealed: it locks the declared maximum,
    # but cannot move the public quote until the round closes.  The shared
    # suite has no capability hook on this branch, so only this inherited test
    # is specialized; every other contract test runs unchanged.
    def test_place_matches_ledger_and_moves_the_quote(self):
        risk, venue, trader = self._setup()
        payload = self.sample_quote_payload(venue)
        quote_before = venue.quote(trader.id, payload)
        market_before = deepcopy(venue.get_market(payload["marketId"]))

        venue.place(trader.id, payload)

        assert trader.frozen_balance == Decimal(payload["maxSpend"])
        assert venue.get_market(payload["marketId"]) == market_before
        venue.close_round(payload["marketId"])
        assert venue.quote(trader.id, payload) != quote_before
        assert all(
            account.frozen_balance == sum(
                (lock.amount for lock in account.locks), Decimal(0)
            )
            for account in risk.accounts.values()
        )
