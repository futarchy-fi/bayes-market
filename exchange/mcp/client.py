"""HTTP operations exposed by the Futarchy MCP server."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_URL = "https://api.futarchy.ai"


class ExchangeAPIError(RuntimeError):
    """A readable error returned by the exchange API."""


class ExchangeClient:
    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("FUTARCHY_API_KEY")
        self.http = httpx.Client(
            base_url=(api_url or os.getenv("FUTARCHY_API_URL", DEFAULT_API_URL)).rstrip("/"),
            headers={"Accept": "application/json"},
            timeout=15,
            transport=transport,
        )

    def _request(self, method: str, path: str, *, auth: bool = False, **kwargs: Any) -> Any:
        if auth and not self.api_key:
            raise RuntimeError("This tool requires FUTARCHY_API_KEY to be set.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if auth else None
        try:
            response = self.http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise RuntimeError(f"Could not reach the Futarchy API: {error}") from error
        if response.is_error:
            try:
                body = response.json()
                error = body.get("error", body.get("detail", body))
                if isinstance(error, dict):
                    code = error.get("code", "unknown_error")
                    message = error.get("message", str(error))
                    raise ExchangeAPIError(
                        f"Futarchy API error {response.status_code} [{code}]: {message}"
                    )
                raise ExchangeAPIError(f"Futarchy API error {response.status_code}: {error}")
            except ValueError:
                raise ExchangeAPIError(
                    f"Futarchy API error {response.status_code}: {response.text}"
                )
        return response.json()

    def health(self) -> dict:
        return self._request("GET", "/v1/health")

    def net_markets(self, query: str = "", limit: int = 20) -> dict:
        data = self._request("GET", "/v1/net/markets")
        needle = query.casefold()
        markets = [
            market for market in data.get("markets", [])
            if not needle or any(
                needle in str(market.get(field, "")).casefold()
                for field in ("id", "variableId", "title")
            )
        ][:max(0, limit)]
        return {"markets": markets, "count": len(markets)}

    def net_marginal(
        self, variable_id: str, context: dict[str, str] | None = None,
    ) -> dict:
        params: dict[str, str] = {"variable": variable_id}
        if context:
            params["context"] = "|".join(f"{var}={outcome}" for var, outcome in context.items())
        return self._request("GET", "/v1/net/marginal", params=params)

    @staticmethod
    def _edit_body(
        variable_id: str,
        outcome_id: str,
        target: float,
        context: dict[str, str] | None,
    ) -> dict:
        body = {"variableId": variable_id, "outcomeId": outcome_id, "target": target}
        if context:
            body["context"] = context
        return body

    def net_preview_edit(
        self,
        variable_id: str,
        outcome_id: str,
        target: float,
        context: dict[str, str] | None = None,
    ) -> dict:
        return self._request(
            "POST", "/v1/net/orders/preview", auth=True,
            json=self._edit_body(variable_id, outcome_id, target, context),
        )

    def net_place_edit(
        self,
        variable_id: str,
        outcome_id: str,
        target: float,
        context: dict[str, str] | None = None,
    ) -> dict:
        return self._request(
            "POST", "/v1/net/orders", auth=True,
            json=self._edit_body(variable_id, outcome_id, target, context),
        )

    def my_orders(self) -> dict:
        return self._request("GET", "/v1/net/orders/mine", auth=True)

    def my_account(self) -> dict:
        return self._request("GET", "/v1/me", auth=True)

    def my_portfolio(self) -> dict:
        return self._request("GET", "/v1/me/net", auth=True)

    def leaderboard(self) -> dict:
        return self._request("GET", "/v1/leaderboard")

    def amm_markets(self, category: str = "", status: str = "open") -> list[dict]:
        params = {"status": status}
        if category:
            params["category"] = category
        return self._request("GET", "/v1/markets", params=params)

    def amm_buy(self, market_id: int, outcome: str, budget: str) -> dict:
        return self._request(
            "POST", f"/v1/markets/{market_id}/buy", auth=True,
            json={"outcome": outcome, "budget": budget},
        )

    def amm_sell(self, market_id: int, outcome: str, amount: str) -> dict:
        return self._request(
            "POST", f"/v1/markets/{market_id}/sell", auth=True,
            json={"outcome": outcome, "amount": amount},
        )
