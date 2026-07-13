"""Table formatting for terminal output. No external dependencies."""

from __future__ import annotations

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
PURPLE = "\033[35m"


def _trunc(text: str, width: int) -> str:
    s = str(text)
    if len(s) > width:
        return s[: width - 1] + "\u2026"
    return s


def _pad(text: str, width: int, right: bool = False) -> str:
    s = str(text)
    if right:
        return s.rjust(width)
    return s.ljust(width)


def _bar(yes: float, width: int = 20) -> str:
    filled = round(yes * width)
    empty = width - filled
    return f"{GREEN}{'█' * filled}{DIM}{'░' * empty}{RESET}"


def _signed(value: float) -> str:
    return f"{value:+,.2f}"


def markets_table(markets: list[dict]) -> str:
    if not markets:
        return f"\n  {DIM}No open markets.{RESET}\n"

    lines = [
        "",
        f"  {BOLD}{_pad('ID', 4)}{_pad('Market', 30)}{_pad('YES', 7)}{_pad('NO', 7)}Trades{RESET}",
        f"  {DIM}{'─' * 58}{RESET}",
    ]

    for m in markets:
        mid = str(m.get("market_id", m.get("id", "?")))
        question = m.get("question", "")

        # Extract short title from "Will PR #N 'title' merge by..." format
        title = question
        if "'" in question:
            parts = question.split("'")
            if len(parts) >= 2:
                pr_part = question.split("PR #")[1].split(" ")[0] if "PR #" in question else ""
                title = f"PR #{pr_part} {parts[1]}" if pr_part else parts[1]

        yes_p = float(m.get("prices", {}).get("yes", 0.5))
        no_p = float(m.get("prices", {}).get("no", 0.5))
        trades = m.get("num_trades", 0)

        yes_str = f"{yes_p:.2f}"
        no_str = f"{no_p:.2f}"

        lines.append(
            f"  {_pad(mid, 4)}"
            f"{_pad(_trunc(title, 28), 30)}"
            f"{GREEN}{_pad(yes_str, 7)}{RESET}"
            f"{RED}{_pad(no_str, 7)}{RESET}"
            f"{_pad(str(trades), 6, right=True)}"
        )

    lines.append("")
    return "\n".join(lines)


def market_detail(m: dict) -> str:
    mid = m.get("market_id", m.get("id", "?"))
    question = m.get("question", "")
    yes_p = float(m.get("prices", {}).get("yes", 0.5))
    no_p = float(m.get("prices", {}).get("no", 0.5))
    volume = m.get("volume", "0")
    deadline = m.get("deadline", "-")
    status = m.get("status", "-")
    trades_count = m.get("num_trades", 0)

    status_color = GREEN if status == "open" else YELLOW

    lines = [
        "",
        f"  {BOLD}#{mid}{RESET}  {question}",
        f"  {DIM}{'─' * 60}{RESET}",
        "",
        f"  Status     {status_color}{status}{RESET}",
        f"  Deadline   {deadline or '-'}",
        "",
        f"  {_bar(yes_p)}",
        f"  {GREEN}YES  {yes_p:.2f}{RESET}    {RED}NO  {no_p:.2f}{RESET}",
        "",
        f"  Volume     {float(volume):,.0f}",
        f"  Trades     {trades_count}",
    ]

    trades = m.get("trades", m.get("recent_trades", []))
    if trades:
        lines.append("")
        lines.append(f"  {BOLD}Recent Trades{RESET}")
        lines.append(f"  {DIM}{'─' * 50}{RESET}")
        lines.append(
            f"  {DIM}{_pad('Side', 6)}{_pad('Amount', 10)}{_pad('Price', 8)}{_pad('Time', 24)}{RESET}"
        )
        for t in trades[:10]:
            side = t.get("outcome", t.get("side", "?"))
            amount = t.get("amount", 0)
            price = t.get("price", 0)
            ts = t.get("created_at", t.get("time", "-"))
            if isinstance(ts, str) and "T" in ts:
                ts = ts.split("T")[0] + " " + ts.split("T")[1][:5]
            color = GREEN if side.lower() == "yes" else RED
            lines.append(
                f"  {color}{_pad(side.upper(), 6)}{RESET}"
                f"{_pad(f'{float(amount):.1f}', 10)}"
                f"{_pad(f'{float(price):.2f}', 8)}"
                f"{DIM}{ts}{RESET}"
            )

    lines.append("")
    return "\n".join(lines)


def user_info(data: dict) -> str:
    available = data.get("available", data.get("balance", "0"))
    frozen = data.get("frozen", "0")
    total = data.get("total", available)

    lines = [
        "",
        f"  {BOLD}Account{RESET}",
        f"  {DIM}{'─' * 40}{RESET}",
        f"  Available  {CYAN}{float(available):,.2f}{RESET}",
        f"  Frozen     {float(frozen):,.2f}",
        f"  Total      {BOLD}{float(total):,.2f}{RESET}",
    ]

    locks = data.get("locks", [])
    positions = data.get("positions", [])
    if locks:
        lines.append("")
        lines.append(f"  {BOLD}Locks{RESET}")
        lines.append(f"  {DIM}{'─' * 40}{RESET}")
        for lk in locks:
            mkt = lk.get("market_id", "?")
            amt = float(lk.get("amount", 0))
            lt = lk.get("lock_type", "")
            lines.append(f"  Market #{mkt}  {amt:,.2f}  {DIM}{lt}{RESET}")
    elif positions:
        lines.append("")
        lines.append(f"  {BOLD}Positions{RESET}")
        lines.append(f"  {DIM}{'─' * 40}{RESET}")
        for p in positions:
            mid = p.get("market_id", "?")
            side = p.get("outcome", p.get("side", "?"))
            shares = p.get("shares", p.get("amount", 0))
            color = GREEN if str(side).lower() == "yes" else RED
            lines.append(
                f"  #{_pad(str(mid), 4)} {color}{_pad(side, 4)}{RESET} {float(shares):,.1f}"
            )
    else:
        lines.append(f"\n  {DIM}No open positions.{RESET}")

    lines.append("")
    lines.append(f"  {DIM}Run futarchy activity for account history.{RESET}")
    lines.append("")
    return "\n".join(lines)


def activity_page(data: dict) -> str:
    entries = data.get("entries", [])
    if not entries:
        return f"\n  {DIM}No account activity yet.{RESET}\n"

    lines = [
        "",
        f"  {BOLD}Activity{RESET}",
        f"  {DIM}{'─' * 56}{RESET}",
    ]

    for entry in entries:
        ts = entry.get("created_at", "-")
        if isinstance(ts, str) and "T" in ts:
            ts = ts.split("T")[0] + " " + ts.split("T")[1][:5]

        summary = entry.get("summary", entry.get("reason", "activity"))
        market = entry.get("market_question")
        if not market and entry.get("market_id"):
            market = f"Market #{entry['market_id']}"

        avail_delta = float(entry.get("available_delta", 0))
        frozen_delta = float(entry.get("frozen_delta", 0))
        total_after = float(entry.get("total_after", 0))
        available_after = float(entry.get("available_after", 0))
        frozen_after = float(entry.get("frozen_after", 0))

        lines.append(f"  {BOLD}{summary}{RESET}  {DIM}{ts}{RESET}")
        if market:
            lines.append(f"  {DIM}{market}{RESET}")
        lines.append(
            f"  Avail {_signed(avail_delta)}  Frozen {_signed(frozen_delta)}"
        )
        lines.append(
            f"  Total {total_after:,.2f}  {DIM}(avail {available_after:,.2f}, frozen {frozen_after:,.2f}){RESET}"
        )
        lines.append("")

    if data.get("has_more"):
        cursor = data.get("next_before_tx_id")
        lines.append(
            f"  {DIM}Older entries available: futarchy activity --before-tx-id {cursor}{RESET}"
        )
        lines.append("")

    return "\n".join(lines)


def trade_result(data: dict) -> str:
    outcome = data.get("outcome", "?")
    amount = data.get("amount", data.get("shares", 0))
    price = data.get("price", 0)
    value = data.get("value", data.get("cost", 0))
    trade_id = data.get("trade_id", "")

    color = GREEN if str(outcome).lower() == "yes" else RED

    return (
        f"\n  {GREEN}Trade executed{RESET}"
        f"{'  #' + str(trade_id) if trade_id else ''}\n"
        f"  {DIM}{'─' * 30}{RESET}\n"
        f"  Side     {color}{outcome.upper()}{RESET}\n"
        f"  Tokens   {float(amount):,.1f}\n"
        f"  Price    {float(price):.4f}\n"
        f"  Value    {float(value):,.2f}\n"
    )


def _marginals(values: dict) -> str:
    if len(values) == 2 and "yes" in values:
        return f"P(yes)={float(values['yes']):.4f}"
    return "  ".join(f"{key}={float(value):.4f}" for key, value in values.items())


def net_markets_table(markets: list[dict]) -> str:
    if not markets:
        return f"\n  {DIM}No net markets.{RESET}\n"
    id_width = max(len("ID"), *(len(str(m.get("id", "?"))) for m in markets)) + 2
    variable_width = max(
        len("Variable"), *(len(str(m.get("variableId", "?"))) for m in markets)
    ) + 2
    marginal_width = max(
        len("Marginals"), *(
            len(_marginals(m.get("marginals", {}))) for m in markets
        )
    ) + 2
    lines = [
        "",
        f"  {BOLD}{_pad('ID', id_width)}{_pad('Variable', variable_width)}"
        f"{_pad('Marginals', marginal_width)}Status{RESET}",
        f"  {DIM}{'─' * (id_width + variable_width + marginal_width + 10)}{RESET}",
    ]
    for market in markets:
        lines.append(
            f"  {_pad(market.get('id', '?'), id_width)}"
            f"{_pad(market.get('variableId', '?'), variable_width)}"
            f"{_pad(_marginals(market.get('marginals', {})), marginal_width)}"
            f"{market.get('status', '-')}"
        )
    lines.append("")
    return "\n".join(lines)


def net_market_detail(market: dict) -> str:
    parents = ", ".join(market.get("parents", [])) or "-"
    outcomes = market.get("outcomes", [])
    outcome_labels = ", ".join(
        str(outcome.get("id", outcome)) if isinstance(outcome, dict) else str(outcome)
        for outcome in outcomes
    ) or "-"
    lines = [
        "",
        f"  {BOLD}{market.get('title') or market.get('id', '?')}{RESET}",
        f"  {DIM}{'─' * 60}{RESET}",
        f"  ID          {market.get('id', '?')}",
        f"  Variable    {market.get('variableId', '?')}",
        f"  Status      {market.get('status', '-')}",
        f"  Outcomes    {outcome_labels}",
        f"  Parents     {parents}",
        f"  Marginals   {_marginals(market.get('marginals', {}))}",
    ]
    if market.get("description"):
        lines.append(f"  Description {market['description']}")
    lines.append("")
    return "\n".join(lines)


def net_marginal(data: dict) -> str:
    context = ", ".join(f"{k}={v}" for k, v in data.get("context", {}).items()) or "none"
    return (
        f"\n  {BOLD}{data.get('variable', '?')}{RESET}\n"
        f"  {DIM}{'─' * 40}{RESET}\n"
        f"  Given       {context}\n"
        f"  Marginal    {_marginals(data.get('marginal', {}))}\n"
    )


def net_preview(data: dict) -> str:
    return (
        f"\n  {BOLD}Order preview{RESET}\n"
        f"  {DIM}{'─' * 30}{RESET}\n"
        f"  Stake       {float(data.get('stake', 0)):,.2f}\n"
        f"  Probability {float(data.get('before', 0)):.4f} → {float(data.get('after', 0)):.4f}\n"
    )


def net_order_result(data: dict) -> str:
    balance = data.get("balance", {})
    return (
        f"\n  {GREEN}Order placed{RESET}  {data.get('orderId', '?')}\n"
        f"  {DIM}{'─' * 36}{RESET}\n"
        f"  Stake frozen {float(data.get('stake', 0)):,.2f}\n"
        f"  Probability  {float(data.get('before', 0)):.4f} → {float(data.get('after', 0)):.4f}\n"
        f"  Balance      available {float(balance.get('available', 0)):,.2f}, "
        f"frozen {float(balance.get('frozen', 0)):,.2f}\n"
    )


def net_orders_table(data: dict) -> str:
    orders = data.get("orders", [])
    if not orders:
        return f"\n  {DIM}No net orders.{RESET}\n"
    order_width = max(
        len("Order"), *(len(str(order.get("orderId", "?"))) for order in orders)
    ) + 2
    variable_width = max(
        len("Variable"), *(
            len(str(order.get("variableId", "?"))) for order in orders
        )
    ) + 2
    outcome_width = max(
        len("Outcome"), *(
            len(str(order.get("outcomeId", "?"))) for order in orders
        )
    ) + 2
    lines = [
        "",
        f"  {BOLD}{_pad('Order', order_width)}{_pad('Variable', variable_width)}"
        f"{_pad('Outcome', outcome_width)}"
        f"{_pad('Target', 10)}{_pad('Stake', 12)}Status{RESET}",
        f"  {DIM}{'─' * (order_width + variable_width + outcome_width + 32)}{RESET}",
    ]
    for order in orders:
        target = f"{float(order.get('target', 0)):.4f}"
        stake = f"{float(order.get('stake', 0)):.2f}"
        lines.append(
            f"  {_pad(order.get('orderId', '?'), order_width)}"
            f"{_pad(order.get('variableId', '?'), variable_width)}"
            f"{_pad(order.get('outcomeId', '?'), outcome_width)}"
            f"{_pad(target, 10)}"
            f"{_pad(stake, 12)}"
            f"{order.get('status', '-')}"
        )
    lines.append("")
    return "\n".join(lines)


def net_portfolio(data: dict) -> str:
    orders = data.get("orders", [])
    opened = sum(order.get("status") == "open" for order in orders)
    awaiting = sum(order.get("status") == "awaiting_context" for order in orders)
    return (
        f"\n  {BOLD}Net portfolio{RESET}\n"
        f"  {DIM}{'─' * 32}{RESET}\n"
        f"  Open stake      {float(data.get('openStake', 0)):,.2f}\n"
        f"  Settled P&L     {float(data.get('settledPnl', 0)):,.2f}\n"
        f"  Open orders     {opened}\n"
        f"  Awaiting orders {awaiting}\n"
    )


def leaderboard_table(data: dict) -> str:
    entries = data.get("entries", [])
    if not entries:
        return f"\n  {DIM}Leaderboard is empty.{RESET}\n"
    lines = [
        "",
        f"  {BOLD}{_pad('Rank', 7)}{_pad('Login', 28)}Total{RESET}",
        f"  {DIM}{'─' * 48}{RESET}",
    ]
    for rank, entry in enumerate(entries, 1):
        login = entry.get("login") or f"account #{entry.get('accountId', '?')}"
        lines.append(
            f"  {_pad(str(rank), 7)}{_pad(_trunc(login, 26), 28)}"
            f"{float(entry.get('total', 0)):,.2f}"
        )
    lines.append("")
    return "\n".join(lines)
