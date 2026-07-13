from decimal import Decimal

from exchange.core.market_engine import MarketEngine
from exchange.venues.amm import AmmVenue
from exchange.venues.contract_suite import VenueContractSuite


class TestAmmVenueContract(VenueContractSuite):
    def make_venue(self, risk_engine):
        engine = MarketEngine(risk_engine)
        engine.create_market(
            question="Contract market",
            category="test",
            category_id="contract",
            metadata={},
            b=Decimal("10"),
        )
        return AmmVenue(engine)

    def sample_quote_payload(self, venue):
        return {
            "marketId": venue.market_ids()[0],
            "side": "buy",
            "outcome": "yes",
            "budget": "10",
        }

    def sample_resolvable(self, venue):
        return venue.market_ids()[0], "yes"
