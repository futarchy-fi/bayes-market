"""HTTP client for the Futarchy API."""

from __future__ import annotations

import json
import sys
from urllib.parse import quote

import httpx

DEFAULT_API_URL = "https://api.futarchy.ai"
TIMEOUT = 15.0


class APIError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class Client:
    def __init__(self, api_url: str = DEFAULT_API_URL, api_key: str | None = None):
        self.base = api_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._http = httpx.Client(base_url=self.base, headers=headers, timeout=TIMEOUT)

    def _request(self, method: str, path: str,
                 raise_on: tuple[int, ...] = (), **kwargs) -> dict | list:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.ConnectError:
            print(f"Error: cannot connect to {self.base}", file=sys.stderr)
            sys.exit(1)
        except httpx.TimeoutException:
            print(f"Error: request to {self.base}{path} timed out", file=sys.stderr)
            sys.exit(1)

        if resp.status_code >= 400 or resp.status_code in raise_on:
            try:
                detail = resp.json().get("detail", resp.text)
            except (json.JSONDecodeError, ValueError):
                detail = resp.text
            raise APIError(resp.status_code, detail)
        return resp.json()

    def get(self, path: str, **params) -> dict | list:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json=body)

    # ── Market endpoints ──

    def list_markets(self) -> list[dict]:
        return self.get("/v1/markets")

    def get_market(self, market_id: int) -> dict:
        return self.get(f"/v1/markets/{market_id}")

    # ── Auth / user endpoints ──

    def device_auth_start(self) -> dict:
        return self.post("/v1/auth/device", body={})

    def device_auth_poll(self, device_code: str) -> dict:
        # 202 = authorization pending: surface it as APIError(202) so the
        # login loop keeps polling instead of mistaking it for success.
        return self._request("POST", "/v1/auth/device/token", raise_on=(202,),
                             json={"device_code": device_code})

    def me(self) -> dict:
        return self.get("/v1/me")

    def activity(self, limit: int = 20,
                 before_tx_id: int | None = None) -> dict:
        params = {"limit": limit}
        if before_tx_id is not None:
            params["before_tx_id"] = before_tx_id
        return self.get("/v1/me/activity", **params)

    # ── Trading endpoints ──

    def buy(self, market_id: int, outcome: str, budget: float) -> dict:
        return self.post(f"/v1/markets/{market_id}/buy", body={
            "outcome": outcome,
            "budget": budget,
        })

    def sell(self, market_id: int, outcome: str, amount: float) -> dict:
        return self.post(f"/v1/markets/{market_id}/sell", body={
            "outcome": outcome,
            "amount": amount,
        })

    # ── Net venue endpoints ──

    def list_net_markets(self) -> dict:
        return self.get("/v1/net/markets")

    def get_net_market(self, market_id: str) -> dict:
        return self.get(f"/v1/net/markets/{quote(market_id, safe='')}")

    def net_marginal(self, variable_id: str, context: str = "") -> dict:
        path = f"/v1/net/marginal?variable={quote(variable_id, safe='')}"
        if context:
            path += f"&context={context}"
        return self._request("GET", path)

    def preview_net_order(self, body: dict) -> dict:
        return self.post("/v1/net/orders/preview", body=body)

    def place_net_order(self, body: dict) -> dict:
        return self.post("/v1/net/orders", body=body)

    def my_net_orders(self) -> dict:
        return self.get("/v1/net/orders/mine")

    def net_portfolio(self) -> dict:
        return self.get("/v1/me/net")

    def leaderboard(self) -> dict:
        return self.get("/v1/leaderboard")
