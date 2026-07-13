import httpx
import pytest

from exchange.mcp.client import ExchangeAPIError, ExchangeClient


def test_net_marginal_success_and_context_encoding():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/net/marginal"
        assert request.url.params["variable"] == "launch/readiness"
        assert request.url.params["context"] == "review=pass|deploy=ready"
        assert "context=review%3Dpass%7Cdeploy%3Dready" in str(request.url)
        return httpx.Response(200, json={
            "variable": "launch/readiness",
            "context": {"review": "pass", "deploy": "ready"},
            "marginal": {"yes": 0.7, "no": 0.3},
        })

    client = ExchangeClient(transport=httpx.MockTransport(handler))
    result = client.net_marginal(
        "launch/readiness", {"review": "pass", "deploy": "ready"},
    )
    assert result["marginal"] == {"yes": 0.7, "no": 0.3}


def test_authed_tool_without_key_names_environment_variable(monkeypatch):
    monkeypatch.delenv("FUTARCHY_API_KEY", raising=False)
    client = ExchangeClient(transport=httpx.MockTransport(lambda request: None))
    with pytest.raises(RuntimeError, match="FUTARCHY_API_KEY"):
        client.my_account()


def test_api_error_is_readable():
    transport = httpx.MockTransport(lambda request: httpx.Response(
        404,
        json={"error": {"code": "unknown_market", "message": "No such variable"}},
    ))
    client = ExchangeClient(transport=transport)
    with pytest.raises(ExchangeAPIError, match=r"404 \[unknown_market\]: No such variable"):
        client.net_marginal("missing")
