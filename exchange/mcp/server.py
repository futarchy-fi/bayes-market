"""FastMCP tool definitions for the Futarchy exchange."""

from mcp.server.fastmcp import FastMCP

from .client import ExchangeClient

mcp = FastMCP("Futarchy Exchange")
client = ExchangeClient()


@mcp.tool()
def health() -> dict:
    """Check API availability and whether the net venue is enabled."""
    return client.health()


@mcp.tool()
def net_markets(query: str = "", limit: int = 20) -> dict:
    """List joint-network markets and current marginals. Search matches id, variableId, or title; use variableId (not market id) with marginal/edit tools."""
    return client.net_markets(query, limit)


@mcp.tool()
def net_marginal(variable_id: str, context: dict[str, str] | None = None) -> dict:
    """Read P(variable | context). Context maps conditioning variable IDs to outcome IDs; omit it for the unconditional live marginal."""
    return client.net_marginal(variable_id, context)


@mcp.tool()
def net_preview_edit(
    variable_id: str,
    outcome_id: str,
    target: float,
    context: dict[str, str] | None = None,
) -> dict:
    """Quote the stake needed to move an outcome probability to target (0.001–0.999), without changing state. Preview before placing an edit."""
    return client.net_preview_edit(variable_id, outcome_id, target, context)


@mcp.tool()
def net_place_edit(
    variable_id: str,
    outcome_id: str,
    target: float,
    context: dict[str, str] | None = None,
) -> dict:
    """Place a staked probability edit toward target (0.001–0.999). This changes the live belief state and freezes the quoted worst-case stake."""
    return client.net_place_edit(variable_id, outcome_id, target, context)


@mcp.tool()
def my_orders() -> dict:
    """List your net-venue probability-edit orders, newest first."""
    return client.my_orders()


@mcp.tool()
def my_account() -> dict:
    """Show your available, frozen, and total credit balances and locks."""
    return client.my_account()


@mcp.tool()
def my_portfolio() -> dict:
    """Show your net orders, aggregate open stake, and settled profit/loss."""
    return client.my_portfolio()


@mcp.tool()
def leaderboard() -> dict:
    """Show the public trader leaderboard ranked by total credit balance."""
    return client.leaderboard()


@mcp.tool()
def amm_markets(category: str = "", status: str = "open") -> list[dict]:
    """List independent LMSR/AMM markets and prices, filtered by exact category and status. Status defaults to open."""
    return client.amm_markets(category, status)


@mcp.tool()
def amm_buy(market_id: int, outcome: str, budget: str) -> dict:
    """Spend a positive decimal-string credit budget to buy outcome shares in an open AMM market."""
    return client.amm_buy(market_id, outcome, budget)


@mcp.tool()
def amm_sell(market_id: int, outcome: str, amount: str) -> dict:
    """Sell a positive decimal-string amount of owned outcome shares in an open AMM market."""
    return client.amm_sell(market_id, outcome, amount)


def main() -> None:
    """Run the server over standard input/output."""
    mcp.run(transport="stdio")
