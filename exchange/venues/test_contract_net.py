from exchange.venues.contract_suite import VenueContractSuite
from exchange.venues.joint.test_venue import TINY_SEEDS
from exchange.venues.joint.venue import JointVenue


class TestNetVenueContract(VenueContractSuite):
    supports_snapshot_roundtrip = True

    def make_venue(self, risk_engine):
        return JointVenue(risk_engine, TINY_SEEDS)

    def sample_quote_payload(self, venue):
        return {
            "variableId": "gcx_a",
            "outcomeId": "yes",
            "target": 0.8,
            "context": {},
        }

    def sample_resolvable(self, venue):
        return "g1", "yes"

    def restore_venue(self, snapshot, risk_engine):
        return JointVenue.from_snapshot(snapshot, risk_engine, TINY_SEEDS)
