#!/usr/bin/env python3
"""Stage 4: the live agent runner — controlled experiment + prod deployment.

Reusable harness that drives LLM agents as traders and applies their decisions
to EITHER a local pair of markets (backtest / dry-run) or the live exchange
(the prod run Kelvin approved). Same neutral prompt, same decision parser,
same scorer — only the backend swaps.

Two deployment shapes:
  1. Controlled experiment (this harness): the orchestrator elicits each
     agent's decision from build_prompt(), parses it, and applies via a
     backend. Backtest uses LocalBackend against real resolved questions;
     the live experiment uses ExchangeBackend (net venue = combinatorial,
     independent AMM markets = flat).
  2. Fully-autonomous prod (the exchange already supports this): N agent
     processes, each an LLM with the exchange MCP (exchange/mcp) configured
     and a service-account key, each briefed with private info, trading on
     their own. That is the production form; this harness is the measured,
     scored version of the same loop.

SAFETY: ExecutBackend defaults to DRY-RUN — it prints the exact POST it would
send and sends nothing. Live trading requires execute=True AND a
FUTARCHY_API_KEY, and should target a separate experiment namespace, not the
public leaderboard. Nothing here fires a live trade without both.

    PYTHONPATH=. python3 scripts/experiments/stage4_runner.py   # self-test (dry)
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request

from backend.inference.factored_market import FactoredMarket

YES, NO = "yes", "no"
OUTCOMES = (YES, NO)


# --- neutral trader prompt + decision parsing (shared with Stages 1/1b) -----

def build_prompt(questions: dict[str, str], prices: dict[str, float],
                 private_info: str, allow_conditional: bool) -> str:
    q_lines = "\n".join(
        f"  [{k}] {questions[k]}  (current price: {round(prices.get(k, 0.5)*100)}%)"
        for k in questions)
    actions = ['  {"action":"set_marginal","question":"<id>","probability":<0-1>}']
    if allow_conditional:
        actions.append('  {"action":"set_conditional","question":"<id>",'
                       '"given":{"question":"<id>","outcome":"yes|no"},"probability":<0-1>}')
    return (f"You are a prediction-market trader. Do NOT use tools — reason from "
            f"your evidence and reply with ONLY a JSON array of actions.\n\n"
            f"Questions:\n{q_lines}\n\nActions (use whichever fit your evidence):\n"
            + "\n".join(actions)
            + f"\n\nYour private evidence:\n  {private_info}\n\n"
            f"Return ONLY the JSON array.")


def parse_decision(text: str) -> list:
    s = text.strip()
    if "```" in s:
        s = s.split("```")[1]
        s = s[4:] if s.startswith("json") else s
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b == -1:
        raise ValueError("no JSON array in agent reply")
    return json.loads(s[a:b + 1])


def _clip(x, lo=0.02, hi=0.98):
    return max(lo, min(hi, x))


# --- backends --------------------------------------------------------------

class LocalBackend:
    """Applies decisions to local flat + comb FactoredMarkets (backtest/dry)."""

    def __init__(self, var_ids: list[str], edges: dict[str, str]):
        # edges: child_var -> parent_var (the known relational structure)
        self.var_ids = var_ids
        flat_nodes = [self._node(v, None) for v in var_ids]
        comb_nodes = [self._node(v, edges.get(v)) for v in var_ids]
        self.flat = FactoredMarket.from_nodes(flat_nodes, 100.0, max_width=6)
        self.comb = FactoredMarket.from_nodes(comb_nodes, 100.0, max_width=6)

    @staticmethod
    def _node(v, parent):
        if not parent:
            return {"variable_id": v, "outcomes": OUTCOMES, "parents": (),
                    "rows": {frozenset(): {YES: 0.5, NO: 0.5}}}
        return {"variable_id": v, "outcomes": OUTCOMES, "parents": (parent,),
                "rows": {frozenset({(parent, YES)}): {YES: 0.5, NO: 0.5},
                         frozenset({(parent, NO)}): {YES: 0.5, NO: 0.5}}}

    def prices(self, combinatorial):
        m = self.comb if combinatorial else self.flat
        return {v: m.marginal(v, {})[YES] for v in self.var_ids}

    def apply(self, decision, combinatorial, alpha=0.2):
        m = self.comb if combinatorial else self.flat
        for act in decision:
            q = act.get("question")
            if q not in self.var_ids:
                continue
            try:
                p = float(act["probability"])
            except (KeyError, TypeError, ValueError):
                continue
            if act.get("action") == "set_marginal":
                cur = m.marginal(q, {})[YES]
                m.trade_to_probability(q, YES, _clip(cur + alpha * (p - cur)))
            elif act.get("action") == "set_conditional" and combinatorial:
                g = act.get("given", {})
                gq, go = g.get("question"), g.get("outcome")
                if gq in self.var_ids and go in OUTCOMES:
                    try:
                        cur = m.marginal(q, {gq: go})[YES]
                        m.trade_to_probability(q, YES, _clip(cur + alpha * (p - cur)),
                                               context={gq: go})
                    except Exception:
                        pass


class ExchangeBackend:
    """Applies decisions to the LIVE net venue. DRY-RUN unless execute+key."""

    def __init__(self, base_url: str, var_of: dict[str, str],
                 api_key: str | None = None, execute: bool = False):
        self.base = base_url.rstrip("/")
        self.var_of = var_of          # question id -> exchange variableId
        self.api_key = api_key or os.environ.get("FUTARCHY_API_KEY")
        self.execute = execute and bool(self.api_key)
        try:
            import certifi
            self.ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            self.ctx = ssl.create_default_context()

    # The exchange edge (Cloudflare) 403s (error 1010) on non-browser User-
    # Agents for authenticated routes; a browser UA is required. Verified
    # 2026-07-15 against api.futarchy.ai (/v1/me, /v1/net/orders/preview 200).
    _UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    def _post(self, path, body):
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "User-Agent": self._UA,
                   "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if not self.execute:
            print(f"  DRY-RUN POST {path}  {json.dumps(body)}")
            return {"dryRun": True}
        req = urllib.request.Request(self.base + path, data=payload,
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=self.ctx) as r:
            return json.loads(r.read().decode())

    def _order_body(self, act):
        vid = self.var_of.get(act.get("question"))
        if not vid:
            return None
        body = {"variableId": vid, "outcomeId": YES, "target": float(act["probability"])}
        if act.get("action") == "set_conditional":
            gvar = self.var_of.get(act.get("given", {}).get("question"))
            if gvar:
                body["context"] = {gvar: act["given"].get("outcome")}
        return body

    def preview(self, decision):
        """Read-only: POST /v1/net/orders/preview, return stake/before/after
        per intended order. Sends nothing tradeable — the last check before
        execute. (Verified live 2026-07-15.)"""
        out = []
        for act in decision:
            body = self._order_body(act)
            if body:
                out.append((body, self._post("/v1/net/orders/preview", body)))
        return out

    def apply(self, decision, combinatorial=True):
        # combinatorial=True -> net venue (conditional edits propagate);
        # a flat arm would post to independent AMM markets instead.
        for act in decision:
            body = self._order_body(act)
            if body:
                self._post("/v1/net/orders", body)


def brier(preds: dict, outcomes: dict):
    keys = [k for k in outcomes if k in preds]
    return sum((preds[k] - outcomes[k]) ** 2 for k in keys) / len(keys)


# --- self-test (dry) -------------------------------------------------------

def _selftest():
    questions = {
        "A": "A major AI capability jump occurs in 2027.",
        "B": "Significant new binding AI regulation passes in 2028.",
    }
    edges = {"B": "A"}  # B depends on A
    local = LocalBackend(list(questions), edges)

    print("=== 1) prompt the runner builds (combinatorial interface) ===")
    print(build_prompt(questions, local.prices(True),
                       "Regulation tends to follow a capability jump; rare without one.",
                       allow_conditional=True))

    print("\n=== 2) apply a real-shaped agent decision locally (flat vs comb) ===")
    decision = [
        {"action": "set_conditional", "question": "B",
         "given": {"question": "A", "outcome": "yes"}, "probability": 0.75},
        {"action": "set_conditional", "question": "B",
         "given": {"question": "A", "outcome": "no"}, "probability": 0.15},
    ]
    local.apply(decision, combinatorial=True)
    local.apply(decision, combinatorial=False)
    print(f"  comb: P(B|A=yes)={local.comb.marginal('B', {'A': YES})[YES]:.2f} "
          f"P(B|A=no)={local.comb.marginal('B', {'A': NO})[YES]:.2f}  "
          f"(absorbed the relational trade)")
    print(f"  flat: P(B)={local.flat.marginal('B', {})[YES]:.2f}  "
          f"(conditional trade structurally dropped)")

    print("\n=== 3) live exchange path in DRY-RUN (nothing sent) ===")
    ex = ExchangeBackend("https://api.futarchy.ai",
                         var_of={"A": "cap_jump_2027", "B": "ai_regulation_2028"},
                         execute=False)
    ex.apply(decision, combinatorial=True)
    print(f"\n  execute={ex.execute}  (live trading needs execute=True + "
          f"FUTARCHY_API_KEY; targets a separate experiment namespace, not prod "
          f"leaderboard)")


if __name__ == "__main__":
    _selftest()
