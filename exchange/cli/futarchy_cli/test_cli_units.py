import pytest

from .main import context_pipe, encode_context, filter_net_markets, parse_given


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
