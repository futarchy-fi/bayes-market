"""Common contract and errors for exchange venues."""

from typing import Protocol, runtime_checkable


class VenueError(Exception):
    """Base class for venue-level errors."""


class UnknownMarket(VenueError):
    pass


class InvalidOutcome(VenueError):
    pass


class InvalidTarget(VenueError):
    pass


class InsufficientCredits(VenueError):
    pass


class MarketClosed(VenueError):
    pass


class TradeRejected(VenueError):
    pass


@runtime_checkable
class Venue(Protocol):
    kind: str

    def market_ids(self) -> list: ...

    def get_market(self, market_id) -> dict: ...

    def quote(self, account_id, payload: dict) -> dict: ...

    def place(self, account_id, payload: dict) -> dict: ...

    def resolve(self, market_id, outcome_id: str) -> dict: ...

    def void(self, market_id) -> dict: ...

    def snapshot(self) -> dict: ...

    def stats(self) -> dict: ...
