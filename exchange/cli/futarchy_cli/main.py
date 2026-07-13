"""CLI entry point — flat command dispatch with argparse."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from urllib.parse import quote

from . import __version__
from . import api as api_mod
from . import auth
from . import fmt


def _add_global_args(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--json", dest="json_output", action="store_true",
                        default=argparse.SUPPRESS if suppress_defaults else False,
                        help="Output as JSON")
    parser.add_argument("--api-url", default=default,
                        help="Override API base URL")


def _client(args) -> api_mod.Client:
    url = args.api_url or auth.get_api_url()
    key = auth.get_api_key()
    return api_mod.Client(api_url=url, api_key=key)


def _authed_client(args) -> api_mod.Client:
    url = args.api_url or auth.get_api_url()
    key = auth.require_auth()
    return api_mod.Client(api_url=url, api_key=key)


def _output(args, data, formatter):
    if args.json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(formatter(data))


# ── Command handlers ──

def cmd_markets(args) -> int:
    client = _client(args)
    markets = client.list_markets()
    _output(args, markets, fmt.markets_table)
    return 0


def cmd_market(args) -> int:
    client = _client(args)
    market = client.get_market(args.market_id)
    _output(args, market, fmt.market_detail)
    return 0


def cmd_login(args) -> int:
    url = args.api_url or auth.get_api_url()
    client = api_mod.Client(api_url=url)
    auth.login(client)
    return 0


def cmd_logout(args) -> int:
    auth.logout()
    return 0


REPO = "https://github.com/futarchy-fi/bayes-market.git"
SPEC = f"futarchy @ git+{REPO}#subdirectory=exchange/cli"


def cmd_update(args) -> int:
    print(f"\n  Current version: {__version__}")
    print("  Updating...\n")

    if shutil.which("pipx"):
        # pipx: uninstall + reinstall to get latest from git
        subprocess.run(["pipx", "uninstall", "futarchy"],
                       capture_output=True)
        ret = subprocess.run(
            ["pipx", "install", "--pip-args=--no-cache-dir", SPEC])
    else:
        # pip fallback
        python = sys.executable
        ret = subprocess.run(
            [python, "-m", "pip", "install", "--force-reinstall",
             "--no-cache-dir", SPEC])

    if ret.returncode != 0:
        print("\n  Update failed.", file=sys.stderr)
        return 1

    # Show new version by running the freshly installed binary
    result = subprocess.run(
        ["futarchy", "--version"], capture_output=True, text=True)
    new_version = result.stdout.strip() if result.returncode == 0 else "unknown"
    print(f"\n  Updated to {new_version}")
    return 0


def cmd_me(args) -> int:
    client = _authed_client(args)
    data = client.me()
    _output(args, data, fmt.user_info)
    return 0


def cmd_activity(args) -> int:
    client = _authed_client(args)
    data = client.activity(limit=args.limit, before_tx_id=args.before_tx_id)
    _output(args, data, fmt.activity_page)
    return 0


def cmd_buy(args) -> int:
    client = _authed_client(args)
    result = client.buy(args.market_id, args.outcome, args.budget)
    _output(args, result, fmt.trade_result)
    return 0


def cmd_sell(args) -> int:
    client = _authed_client(args)
    result = client.sell(args.market_id, args.outcome, args.amount)
    _output(args, result, fmt.trade_result)
    return 0


def parse_given(pairs: list[str] | None) -> dict[str, str]:
    context = {}
    for pair in pairs or []:
        if pair.count("=") != 1:
            raise ValueError(f"invalid --given {pair!r}: expected VAR=OUTCOME")
        variable, outcome = (part.strip() for part in pair.split("=", 1))
        if not variable or not outcome:
            raise ValueError(f"invalid --given {pair!r}: expected VAR=OUTCOME")
        context[variable] = outcome
    return context


def context_pipe(context: dict[str, str]) -> str:
    return "|".join(f"{variable}={outcome}" for variable, outcome in context.items())


def encode_context(context: dict[str, str]) -> str:
    return quote(context_pipe(context), safe="")


def filter_net_markets(markets: list[dict], query: str | None) -> list[dict]:
    if not query:
        return markets
    needle = query.casefold()
    return [
        market for market in markets
        if any(needle in str(market.get(field, "")).casefold()
               for field in ("id", "variableId", "title"))
    ]


def _given_arg(value: str) -> str:
    try:
        parse_given([value])
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value


def _net_order_body(args) -> dict:
    context = parse_given(args.given)
    body = {
        "variableId": args.variable_id,
        "outcomeId": args.outcome_id,
        "target": args.target,
    }
    if context:
        body["context"] = context
    return body


def cmd_net_markets(args) -> int:
    data = _client(args).list_net_markets()
    markets = filter_net_markets(data.get("markets", []), args.query)
    if args.limit:
        markets = markets[:args.limit]
    _output(args, markets, fmt.net_markets_table)
    return 0


def cmd_net_market(args) -> int:
    data = _client(args).get_net_market(args.market_id)
    _output(args, data, fmt.net_market_detail)
    return 0


def cmd_net_marginal(args) -> int:
    context = parse_given(args.given)
    data = _client(args).net_marginal(args.variable_id, encode_context(context))
    _output(args, data, fmt.net_marginal)
    return 0


def cmd_net_preview(args) -> int:
    data = _authed_client(args).preview_net_order(_net_order_body(args))
    _output(args, data, fmt.net_preview)
    return 0


def cmd_net_edit(args) -> int:
    data = _authed_client(args).place_net_order(_net_order_body(args))
    _output(args, data, fmt.net_order_result)
    return 0


def cmd_net_orders(args) -> int:
    data = _authed_client(args).my_net_orders()
    _output(args, data, fmt.net_orders_table)
    return 0


def cmd_net_portfolio(args) -> int:
    data = _authed_client(args).net_portfolio()
    _output(args, data, fmt.net_portfolio)
    return 0


def cmd_net(args) -> int:
    if not args.net_command:
        args.net_parser.print_help()
        return 0
    return {
        "markets": cmd_net_markets,
        "market": cmd_net_market,
        "marginal": cmd_net_marginal,
        "preview": cmd_net_preview,
        "edit": cmd_net_edit,
        "orders": cmd_net_orders,
        "portfolio": cmd_net_portfolio,
    }[args.net_command](args)


def cmd_leaderboard(args) -> int:
    data = _client(args).leaderboard()
    _output(args, data, fmt.leaderboard_table)
    return 0


def _sub(subparsers, name: str, **kwargs) -> argparse.ArgumentParser:
    """Create a subparser with global args inherited."""
    p = subparsers.add_parser(name, **kwargs)
    _add_global_args(p, suppress_defaults=True)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="futarchy",
        description="Futarchy — prediction markets for code",
    )
    parser.add_argument("--version", action="version",
                        version=f"futarchy {__version__}")
    _add_global_args(parser)
    sub = parser.add_subparsers(dest="command")

    # futarchy markets
    _sub(sub, "markets", help="List open markets")

    # futarchy market <id>
    p_market = _sub(sub, "market", help="Show market detail")
    p_market.add_argument("market_id", type=int, help="Market ID")

    # futarchy login
    _sub(sub, "login", help="Create an account")

    # futarchy logout
    _sub(sub, "logout", help="Clear saved credentials")

    # futarchy update
    _sub(sub, "update", help="Update to latest version")

    # futarchy me
    _sub(sub, "me", help="Show balance and positions")

    # futarchy activity
    p_activity = _sub(sub, "activity", help="Show account activity")
    p_activity.add_argument("--limit", type=int, default=20,
                            help="Number of entries to fetch (default: 20)")
    p_activity.add_argument("--before-tx-id", type=int, default=None,
                            help="Fetch entries older than this transaction ID")

    # futarchy buy <id> <outcome> <budget>
    p_buy = _sub(sub, "buy", help="Buy outcome tokens")
    p_buy.add_argument("market_id", type=int, help="Market ID")
    p_buy.add_argument("outcome", choices=["yes", "no"], help="Outcome to buy")
    p_buy.add_argument("budget", type=float, help="Amount to spend")

    # futarchy sell <id> <outcome> <amount>
    p_sell = _sub(sub, "sell", help="Sell outcome tokens")
    p_sell.add_argument("market_id", type=int, help="Market ID")
    p_sell.add_argument("outcome", choices=["yes", "no"], help="Outcome to sell")
    p_sell.add_argument("amount", type=float, help="Number of tokens to sell")

    # futarchy net ...
    p_net = _sub(sub, "net", help="Trade the joint Bayes network")
    net_sub = p_net.add_subparsers(dest="net_command")

    p_net_markets = _sub(net_sub, "markets", help="List net markets")
    p_net_markets.add_argument("--limit", type=int, default=20,
                               help="Number to show; 0 shows all (default: 20)")
    p_net_markets.add_argument("--query", help="Filter by id, variable, or title")

    p_net_market = _sub(net_sub, "market", help="Show net market detail")
    p_net_market.add_argument("market_id", help="Net market ID")

    p_net_marginal = _sub(net_sub, "marginal", help="Show a variable marginal")
    p_net_marginal.add_argument("variable_id", help="Variable ID")
    p_net_marginal.add_argument("--given", action="append", default=[], type=_given_arg,
                                metavar="VAR=OUTCOME", help="Conditioning value (repeatable)")

    for name, help_text in (("preview", "Preview a probability edit"),
                            ("edit", "Place a probability edit")):
        order = _sub(net_sub, name, help=help_text)
        order.add_argument("variable_id", help="Variable ID")
        order.add_argument("outcome_id", help="Outcome ID")
        order.add_argument("target", type=float, help="Target probability")
        order.add_argument("--given", action="append", default=[], type=_given_arg,
                           metavar="VAR=OUTCOME", help="Conditioning value (repeatable)")

    _sub(net_sub, "orders", help="List your net orders")
    _sub(net_sub, "portfolio", help="Show your net portfolio")

    # futarchy leaderboard
    _sub(sub, "leaderboard", help="Show account leaderboard")

    args = parser.parse_args(argv)
    if args.command == "net":
        args.net_parser = p_net

    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "markets": cmd_markets,
        "market": cmd_market,
        "login": cmd_login,
        "logout": cmd_logout,
        "update": cmd_update,
        "me": cmd_me,
        "activity": cmd_activity,
        "buy": cmd_buy,
        "sell": cmd_sell,
        "net": cmd_net,
        "leaderboard": cmd_leaderboard,
    }

    try:
        return dispatch[args.command](args)
    except api_mod.APIError as e:
        if args.json_output:
            print(json.dumps({"error": e.detail, "status": e.status}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
