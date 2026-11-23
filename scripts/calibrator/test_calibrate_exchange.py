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


class GraphExchangeStub(ExchangeStub):
    """Stub implementing GET /v1/net/markets?fields=graph alongside market/order routes."""

    def __init__(self, *, graph_markets, available="1000", prices=None, stakes=None):
        super().__init__(available=available, prices=prices, stakes=stakes)
        self.graph_markets = graph_markets

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if (
            request.method == "GET"
            and request.url.path == "/v1/net/markets"
            and request.url.params.get("fields") == "graph"
        ):
            self.requests.append(request)
            return httpx.Response(200, json={"markets": self.graph_markets, "count": len(self.graph_markets)})
        return super().__call__(request)


def test_only_connected_skips_degree_zero_markets(tmp_path):
    graph = [
        {"id": "x1", "variableId": "v1", "status": "active", "marginals": {"yes": 0.5}},
        {"id": "x2", "variableId": "v2", "status": "active", "marginals": {"yes": 0.5}, "parents": ["v1"]},
        {"id": "x3", "variableId": "v3", "status": "active", "marginals": {"yes": 0.5}},
    ]
    anchors = [_anchor(1, 0.8), _anchor(2, 0.8), _anchor(3, 0.8)]

    stub = GraphExchangeStub(graph_markets=graph)
    stats = _run(tmp_path, stub, anchors, ExchangeConfig(execute=True, only_connected=True))

    order_vars = [
        json.loads(r.content)["variableId"]
        for r in stub.requests
        if r.url.path == "/v1/net/orders"
    ]
    assert order_vars == ["v1", "v2"]
    assert stats["isolated_skipped"] == 1
    assert stats["traded"] == 2

    # Disabling only_connected allows trading the isolated market too.
    stub_all = GraphExchangeStub(graph_markets=graph)
    stats_all = _run(tmp_path, stub_all, anchors, ExchangeConfig(execute=True, only_connected=False))
    order_vars_all = [
        json.loads(r.content)["variableId"]
        for r in stub_all.requests
        if r.url.path == "/v1/net/orders"
    ]
    assert order_vars_all == ["v1", "v2", "v3"]
    assert stats_all["isolated_skipped"] == 0
    assert stats_all["traded"] == 3


def test_manifold_resolved_upstream_counted_and_logged(tmp_path, monkeypatch, caplog):
    import scripts.calibrator.calibrate_anchors as cal_mod

    monkeypatch.setattr(cal_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        cal_mod,
        "http_json",
        lambda url, **_kw: {"isResolved": True, "resolution": "YES", "probability": 1.0},
    )
    stub = ExchangeStub()
    manifold_anchor = {
        "marketId": "x1",
        "variableId": "v1",
        "source": "manifold",
        "ref": "slug-resolved",
    }
    with caplog.at_level(logging.WARNING, logger="calibrator"):
        stats = _run(tmp_path, stub, [manifold_anchor])

    assert stats["resolved_upstream"] == 1
    assert stats["fetch_failed"] == 0
    assert stats["traded"] == 0
    assert "upstream resolved: marketId=x1 resolution=YES" in caplog.text
    # Iron rule: calibrator NEVER calls resolve/admin endpoints.
    assert not any("/resolve" in r.url.path or "/admin" in r.url.path for r in stub.requests)


def test_polymarket_unresolved_and_resolved_upstream(tmp_path, monkeypatch, caplog):
    import scripts.calibrator.calibrate_anchors as cal_mod

    monkeypatch.setattr(cal_mod.time, "sleep", lambda _s: None)

    def fake_http_json(url, **_kw):
        if url.endswith("/poly-open"):
            return {
                "closed": False,
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.75", "0.25"]',
            }
        if url.endswith("/poly-closed"):
            return {
                "closed": True,
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0", "1"]',
            }
        raise ValueError(f"unexpected url {url}")

    monkeypatch.setattr(cal_mod, "http_json", fake_http_json)
    stub = ExchangeStub(prices={"x1": 0.5, "x2": 0.5}, stakes={"v1": "10"})
    anchors = [
        {"marketId": "x1", "variableId": "v1", "source": "polymarket", "ref": "poly-open"},
        {"marketId": "x2", "variableId": "v2", "source": "polymarket", "ref": "poly-closed"},
    ]
    with caplog.at_level(logging.WARNING, logger="calibrator"):
        stats = _run(tmp_path, stub, anchors)

    assert stats["traded"] == 1
    assert stats["resolved_upstream"] == 1
    assert stats["fetch_failed"] == 0
    assert "upstream resolved: marketId=x2 resolution=NO" in caplog.text
    order_posts = [r for r in stub.requests if r.url.path == "/v1/net/orders"]
    assert len(order_posts) == 1
    assert json.loads(order_posts[0].content) == {
        "variableId": "v1", "outcomeId": "yes", "target": 0.55,
    }


def test_largest_gap_prioritized_first_under_budget_cap(tmp_path):
    stub = ExchangeStub(
        prices={"x1": 0.50, "x2": 0.50, "x3": 0.50},
        stakes={"v1": "25", "v2": "25", "v3": "25"},
    )
    anchors = [
        _anchor(1, 0.55),  # |gap| = 0.05
        _anchor(2, 0.90),  # |gap| = 0.40 (largest)
        _anchor(3, 0.70),  # |gap| = 0.20 (second largest)
    ]
    stats = _run(
        tmp_path, stub, anchors,
        ExchangeConfig(execute=True, run_budget=Decimal("50")),
    )
    order_vars = [
        json.loads(r.content)["variableId"]
        for r in stub.requests
        if r.url.path == "/v1/net/orders"
    ]
    assert order_vars == ["v2", "v3"]
    assert stats["traded"] == 2
    assert stats["budget_skipped"] == 1


def test_default_min_gap_is_two_percent(tmp_path):
    assert ExchangeConfig().min_gap == Decimal("0.02")
    stub = ExchangeStub(prices={"x1": 0.50})
    stats = _run(tmp_path, stub, [_anchor(1, 0.515)])
    assert stats["within_min_gap"] == 1
    assert stats["traded"] == 0
    assert not any(r.method == "POST" for r in stub.requests)


def test_append_log_uses_flock_and_is_safe_under_concurrent_writes(tmp_path, monkeypatch):
    import fcntl
    import threading
    import scripts.calibrator.calibrate_anchors as cal_mod

    flock_ops: list[int] = []
    real_flock = fcntl.flock

    def spy_flock(fd, op):
        flock_ops.append(op)
        return real_flock(fd, op)

    monkeypatch.setattr(cal_mod.fcntl, "flock", spy_flock)

    log_path = tmp_path / "trades.jsonl"
    errors: list[Exception] = []

    def worker(tid: int):
        try:
            for seq in range(25):
                cal_mod.append_log({"thread": tid, "seq": seq, "payload": "x" * 64}, log_path)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    parsed = [json.loads(line) for line in lines]
    assert {(row["thread"], row["seq"]) for row in parsed} == {
        (tid, seq) for tid in range(8) for seq in range(25)
    }
    assert fcntl.LOCK_EX in flock_ops
    assert fcntl.LOCK_UN in flock_ops
