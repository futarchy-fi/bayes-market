"""Reusable compliance tests for implementations of :class:`Venue`."""

from copy import deepcopy
from decimal import Decimal
from abc import ABC, abstractmethod

import pytest

from exchange.core.risk_engine import RiskEngine
from exchange.venues.base import InsufficientCredits, Venue


class VenueContractSuite(ABC):
    """Subclass and supply the three venue-specific fixture methods."""

    supports_snapshot_roundtrip = False

    @abstractmethod
    def make_venue(self, risk_engine: RiskEngine):
        raise NotImplementedError

    @abstractmethod
    def sample_quote_payload(self, venue) -> dict:
        raise NotImplementedError

    @abstractmethod
    def sample_resolvable(self, venue) -> tuple[object, str]:
        raise NotImplementedError

    def restore_venue(self, snapshot: dict, risk_engine: RiskEngine):
        raise NotImplementedError

    @staticmethod
    def _balances(risk: RiskEngine):
        return deepcopy({
            account_id: (
                account.available_balance,
                account.frozen_balance,
                account.locks,
            )
            for account_id, account in risk.accounts.items()
        })

    @staticmethod
    def _total_credits(risk: RiskEngine) -> Decimal:
        return sum((account.total for account in risk.accounts.values()), Decimal("0"))

    @staticmethod
    def _quoted_charge(quote: dict) -> Decimal:
        return Decimal(quote.get("cost", quote.get("stake")))

    def _setup(self, balance=Decimal("1000")):
        risk = RiskEngine()
        venue = self.make_venue(risk)
        trader = risk.create_account()
        risk.mint(trader.id, balance)
        return risk, venue, trader

    def test_quote_does_not_change_balances_or_market_state(self):
        risk, venue, trader = self._setup()
        balances = self._balances(risk)
        state = deepcopy(venue.snapshot())
        transactions = deepcopy(risk.transactions)

        venue.quote(trader.id, self.sample_quote_payload(venue))

        assert self._balances(risk) == balances
        assert venue.snapshot() == state
        assert risk.transactions == transactions

    def test_place_matches_ledger_and_moves_the_quote(self):
        risk, venue, trader = self._setup()
        payload = self.sample_quote_payload(venue)
        first_quote = venue.quote(trader.id, payload)
        available_before = trader.available_balance

        venue.place(trader.id, payload)

        for account in risk.accounts.values():
            assert account.frozen_balance == sum(
                (lock.amount for lock in account.locks), Decimal("0")
            )
        assert available_before - trader.available_balance == self._quoted_charge(
            first_quote
        )
        assert venue.quote(trader.id, payload) != first_quote

    def test_insufficient_credits_has_zero_state_change(self):
        risk, venue, trader = self._setup(balance=Decimal("0"))
        balances = self._balances(risk)
        state = deepcopy(venue.snapshot())
        transactions = deepcopy(risk.transactions)

        with pytest.raises(InsufficientCredits):
            venue.place(trader.id, self.sample_quote_payload(venue))

        assert self._balances(risk) == balances
        assert venue.snapshot() == state
        assert risk.transactions == transactions

    def test_resolve_conserves_all_account_credits(self):
        risk, venue, trader = self._setup()
        venue.place(trader.id, self.sample_quote_payload(venue))
        market_id, outcome_id = self.sample_resolvable(venue)
        total_before = self._total_credits(risk)

        venue.resolve(market_id, outcome_id)

        assert self._total_credits(risk) == total_before

    def test_void_makes_trader_whole(self):
        risk, venue, trader = self._setup()
        before = (trader.available_balance, trader.frozen_balance, trader.total)
        venue.place(trader.id, self.sample_quote_payload(venue))
        market_id, _ = self.sample_resolvable(venue)

        venue.void(market_id)

        assert (trader.available_balance, trader.frozen_balance, trader.total) == before

    def test_snapshot_roundtrip_when_supported(self):
        if not self.supports_snapshot_roundtrip:
            pytest.skip("venue persistence is owned by its engine")
        risk, venue, trader = self._setup()
        venue.place(trader.id, self.sample_quote_payload(venue))
        snapshot = deepcopy(venue.snapshot())

        restored = self.restore_venue(snapshot, risk)

        assert restored.snapshot() == snapshot

    def test_runtime_protocol(self):
        risk = RiskEngine()
        assert isinstance(self.make_venue(risk), Venue)
