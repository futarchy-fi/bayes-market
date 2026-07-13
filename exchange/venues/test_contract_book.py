from decimal import Decimal

from exchange.venues.book.engine import BookEngine
from exchange.venues.book.venue import BookVenue
from exchange.venues.contract_suite import VenueContractSuite


class TestBookVenueContract(VenueContractSuite):
    supports_snapshot_roundtrip = True

    def make_venue(self, risk_engine):
        venue = BookVenue(BookEngine(risk_engine))
        market = venue.create_market("Contract market")

        yes, no = risk_engine.create_account(), risk_engine.create_account()
        risk_engine.mint(yes.id, Decimal("10"))
        risk_engine.mint(no.id, Decimal("10"))
        venue.place(no.id, self._order(market["id"], "bid", "no", "0.5000"))
        venue.place(yes.id, self._order(market["id"], "bid", "yes", "0.5000"))
        venue.place(yes.id, self._order(market["id"], "ask", "yes", "0.5000"))
        return venue

    @staticmethod
    def _order(market_id, side, outcome, price):
        return {
            "marketId": market_id,
            "side": side,
            "outcome": outcome,
            "price": price,
            "size": "1.00",
        }

    def sample_quote_payload(self, venue):
        return self._order(venue.market_ids()[0], "bid", "yes", "0.5000")

    def sample_resolvable(self, venue):
        return venue.market_ids()[0], "yes"

    def restore_venue(self, snapshot, risk_engine):
        return BookVenue.from_snapshot(snapshot, risk_engine)
