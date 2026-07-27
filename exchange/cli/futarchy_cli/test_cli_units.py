import httpx
import pytest

from .api import APIError, Client
from .main import context_pipe, encode_context, filter_net_markets, parse_given


def _client_with(handler) -> Client:
    client = Client(api_url="http://test")
    client._http = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return client


def test_device_poll_raises_on_202_pending():
    # regression: a 202 pending body used to be returned as success, so
    # `futarchy login` saved an empty API key on the very first poll.
    def handler(request):
        return httpx.Response(202, json={"error": {"code": "device_flow_pending"}})

    with pytest.raises(APIError) as exc:
        _client_with(handler).device_auth_poll("dc")
    assert exc.value.status == 202


def test_device_poll_returns_token_on_200():
    def handler(request):
        return httpx.Response(200, json={"api_key": "k", "github_login": "u"})

    resp = _client_with(handler).device_auth_poll("dc")
    assert resp["api_key"] == "k"


def test_given_context_dict_and_wire_encoding():
    context = parse_given(["parent=yes", "region=north west"])

    assert context == {"parent": "yes", "region": "north west"}
    assert context_pipe(context) == "parent=yes|region=north west"
    assert encode_context(context) == "parent%3Dyes%7Cregion%3Dnorth%20west"


def test_given_rejects_malformed_pair():
    with pytest.raises(ValueError, match="expected VAR=OUTCOME"):
        parse_given(["parent-yes"])


def test_filter_net_markets_matches_id_variable_or_title_case_insensitively():
    markets = [
        {"id": "MARKET-1", "variableId": "alpha", "title": "First"},
        {"id": "market-2", "variableId": "BETA_NODE", "title": "Second"},
        {"id": "market-3", "variableId": "gamma", "title": "Launch Window"},
    ]

    assert filter_net_markets(markets, "market-1") == [markets[0]]
    assert filter_net_markets(markets, "beta") == [markets[1]]
    assert filter_net_markets(markets, "LAUNCH") == [markets[2]]
    assert filter_net_markets(markets, None) == markets


def test_markets_table_renders_missing_prices_as_unavailable_not_050():
    from .fmt import markets_table

    table = markets_table([
        {"id": 1, "question": "Open market", "prices": {"yes": 0.7, "no": 0.3}},
        {"id": 2, "question": "Resolved market", "prices": {}, "status": "resolved"},
        {"id": 3, "question": "No prices key at all", "status": "closed"},
    ])

    assert "0.70" in table and "0.30" in table
    # The two markets without prices must not show a live-looking number.
    assert table.count("n/a") == 4
    assert "0.50" not in table


def test_market_detail_without_prices_says_unavailable_not_a_half_bar():
    from .fmt import market_detail

    detail = market_detail(
        {"id": 2, "question": "Resolved market", "prices": {}, "status": "resolved"}
    )

    assert "unavailable" in detail
    assert "0.50" not in detail
    assert "█" not in detail  # no fake half-filled price bar
