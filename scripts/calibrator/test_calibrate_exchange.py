"""Money-safety proofs for the calibrator's exchange backend."""

import json
import logging
from decimal import Decimal

import httpx

from scripts.calibrator.calibrate_anchors import (
    ExchangeConfig,
    HttpExchange,
    run_exchange,
)


def _anchor(number: int, value: float = 0.8) -> dict:
    return {
        "marketId": f"x{number}",
        "variableId": f"v{number}",
        "source": "metaculus",
        "ref": str(number),
        "value": value,
        "fetchedAt": "2099-01-01T00:00:00Z",
    }


class ExchangeStub:
    def __init__(self, *, available="1000", prices=None, stakes=None):
        self.available = available
        self.prices = prices or {}
        self.stakes = stakes or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/v1/me":
            return httpx.Response(200, json={"available": self.available})
        if request.method == "GET" and path.startswith("/v1/net/markets/"):
            market_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={
                "id": market_id,
                "variableId": f"v{market_id.removeprefix('x')}",
                "status": "active",
                "marginals": {"yes": self.prices.get(market_id, 0.5)},
            })
        if request.method == "POST":
            body = json.loads(request.content)
            stake = self.stakes.get(body["variableId"], "10")
            if path == "/v1/net/orders/preview":
                return httpx.Response(200, json={
                    "stake": stake, "before": 0.5, "after": body["target"], "b": "1",
                })
            if path == "/v1/net/orders":
                return httpx.Response(200, json={
                    "orderId": f"order-{body['variableId']}", "stake": stake,
                })
        return httpx.Response(404, json={"error": {"message": "not found"}})


def _run(tmp_path, stub: ExchangeStub, anchors, config=None):
    with HttpExchange(
        "http://exchange", "service-key",
        transport=httpx.MockTransport(stub),
    ) as client:
        return run_exchange(
            anchors,
            client,
            config or ExchangeConfig(execute=True),
            log_path=tmp_path / "trades.jsonl",
        )


def test_budget_cap_is_respected_across_multiple_anchors(tmp_path):
    stub = ExchangeStub(stakes={"v1": "30", "v2": "25", "v3": "20"})
    stats = _run(tmp_path, stub, [_anchor(1), _anchor(2), _anchor(3)])

    order_posts = [
        request for request in stub.requests
        if request.url.path == "/v1/net/orders"
    ]
    assert [json.loads(request.content)["variableId"] for request in order_posts] == [
        "v1", "v3",
    ]
    assert stats["traded"] == 2
    assert stats["budget_skipped"] == 1
    assert Decimal(stats["stake"]) == Decimal("50")


def test_min_balance_skips_everything_and_warns_for_top_up(tmp_path, caplog):
    stub = ExchangeStub(available="99")
    with caplog.at_level(logging.WARNING, logger="calibrator"):
        stats = _run(tmp_path, stub, [_anchor(1)])

    assert stats["traded"] == 0
    assert [request.method for request in stub.requests] == ["GET"]
    assert "LOW BALANCE" in caplog.text
    assert "Top up" in caplog.text


def test_min_gap_skips_preview_and_trade(tmp_path):
    stub = ExchangeStub(prices={"x1": 0.5})
    stats = _run(tmp_path, stub, [_anchor(1, 0.509)])

    assert stats["within_min_gap"] == 1
    assert not any(request.method == "POST" for request in stub.requests)


def test_report_only_performs_zero_posts(tmp_path):
    stub = ExchangeStub()
    stats = _run(
        tmp_path, stub, [_anchor(1)], ExchangeConfig(execute=False),
    )

    assert stats["reported"] == 1
    assert not any(request.method == "POST" for request in stub.requests)


def test_normal_anchor_trade_posts_net_body_and_logs_stake(tmp_path):
    stub = ExchangeStub(prices={"x1": 0.4}, stakes={"v1": "12.5"})
    stats = _run(tmp_path, stub, [_anchor(1, 0.7)])

    order_request = next(
        request for request in stub.requests
        if request.url.path == "/v1/net/orders"
    )
    assert json.loads(order_request.content) == {
        "variableId": "v1", "outcomeId": "yes", "target": 0.45,
    }
    assert order_request.headers["Authorization"] == "Bearer service-key"
    assert stats["traded"] == 1
    log = json.loads((tmp_path / "trades.jsonl").read_text())
    assert (log["venue"], log["orderId"], log["stake"]) == (
        "net", "order-v1", "12.5",
    )
