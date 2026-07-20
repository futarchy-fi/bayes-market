#!/usr/bin/env python3
"""Pre-mounted preview run for the live combinatorial arm (net venue).

Read-only. The last check before `execute=True`: fetches live cluster prices,
builds each agent's neutral prompt from question_set.json, and — given the
agents' collected decisions — previews every intended order against the LIVE
net venue (`POST /v1/net/orders/preview`), reporting stake / before / after
per order. Sends nothing tradeable.

The agent decisions themselves are elicited by the orchestrator from the
prompts this emits (`--prompts`), then replayed here (`--preview FILE`).

Key comes from ~/.config/futarchy-exp/agent-keys.env (never committed). The
flat arm (independent AMM markets) previews separately once those markets
exist; this covers the combinatorial arm, which is live now.

    source ~/.config/futarchy-exp/agent-keys.env
    PYTHONPATH=. python3 scripts/experiments/live_run/preview_run.py --prompts
    PYTHONPATH=. python3 scripts/experiments/live_run/preview_run.py --preview decisions.json
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.experiments.stage4_runner import build_prompt, ExchangeBackend  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "question_set.json").read_text())
BASE = CONFIG.get("exchange_base", "https://api.futarchy.ai")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

QUESTIONS = {k: v["title"] for k, v in CONFIG["questions"].items()}
VAR_OF = {k: v["variableId"] for k, v in CONFIG["questions"].items()}


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _key():
    return (os.environ.get("FUTARCHY_API_KEY")
            or os.environ.get("FUTARCHY_EXP_KEY_47", ""))


def live_marginal(variable_id: str, context: dict | None = None) -> float | None:
    """Current YES price. Read from the preview endpoint's ``before`` field
    (a preview with any target is read-only and returns the live price) —
    more reliable than /v1/net/marginal, whose param shape varies."""
    body = {"variableId": variable_id, "outcomeId": "yes", "target": 0.5}
    if context:
        body["context"] = context
    req = urllib.request.Request(
        f"{BASE}/v1/net/orders/preview", data=json.dumps(body).encode(),
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Content-Type": "application/json",
                 "Authorization": f"Bearer {_key()}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ctx()) as r:
            d = json.loads(r.read().decode())
        return float(d["before"]) if "before" in d else None
    except Exception:
        return None


def live_prices() -> dict[str, float]:
    return {k: (live_marginal(v) or 0.5) for k, v in VAR_OF.items()}


def agent_briefs(prices: dict[str, float]) -> list[dict]:
    """Expand the info design into concrete per-agent (id, private_info, allow)
    specs, filling {marginal} placeholders with live prices."""
    design = CONFIG["agent_info_design"]
    out, idx = [], 0
    # map a brief's target question by keyword, for the {marginal} fill
    def fill(brief):
        for k in QUESTIONS:
            if VAR_OF[k].split("_by_")[0].split("_in_")[0] in brief.lower() or k in brief:
                return brief
        return brief
    for grp in design.get("marginal_agents", []):
        # infer which question this marginal group is about from its brief
        qkey = next((k for k in QUESTIONS if QUESTIONS[k].split()[2].lower() in grp["brief"].lower()
                     or k in grp["brief"]), list(QUESTIONS)[0])
        for _ in range(grp["n"]):
            info = grp["brief"].replace("{marginal}", f"{round(prices.get(qkey,0.5)*100)}%")
            out.append({"id": f"marg{idx}", "class": "marginal", "info": info, "allow_conditional": True})
            idx += 1
    for grp in design.get("relational_agents", []):
        for _ in range(grp["n"]):
            out.append({"id": f"rel{idx}", "class": "relational", "info": grp["brief"],
                        "allow_conditional": True})
            idx += 1
    return out


def emit_prompts():
    prices = live_prices()
    print(f"# live cluster prices: " + ", ".join(f"{k}={round(v*100)}%" for k, v in prices.items()),
          file=sys.stderr)
    specs = []
    for b in agent_briefs(prices):
        specs.append({"id": b["id"], "class": b["class"],
                      "prompt": build_prompt(QUESTIONS, prices, b["info"], b["allow_conditional"])})
    print(json.dumps(specs, indent=1))


def preview(decisions_path: str):
    ex = ExchangeBackend(BASE, VAR_OF, api_key=_key(), execute=False)
    decisions = json.loads(Path(decisions_path).read_text())
    total_by_agent = []
    print(f"{'order':44} {'before':>8} {'after':>7} {'stake':>9}")
    for i, dec in enumerate(decisions):
        dec = dec if isinstance(dec, list) else json.loads(dec)
        results = ex.preview(dec)
        agent_stake = 0.0
        for body, (status, resp) in results:
            ctx = body.get("context")
            label = f"{body['variableId'][:26]}{' | '+list(ctx)[0][:12] if ctx else ''}->{body['target']}"
            if isinstance(resp, dict) and "stake" in resp:
                s = float(resp["stake"]); agent_stake += s
                print(f"{label:44} {float(resp.get('before',0)):>8.3f} "
                      f"{float(resp.get('after',0)):>7.2f} {s:>9.3f}")
            else:
                print(f"{label:44}  -> {status} {str(resp)[:40]}")
        total_by_agent.append(agent_stake)
        print(f"  agent {i}: total stake {agent_stake:.2f} / 1000 credits")
    print(f"\n{len(decisions)} agents previewed (read-only). "
          f"total stake across all orders: {sum(total_by_agent):.2f}. "
          f"NOTHING was traded.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", action="store_true", help="emit agent prompts (live prices)")
    ap.add_argument("--preview", metavar="FILE", help="preview collected decisions (read-only)")
    args = ap.parse_args()
    if args.prompts:
        emit_prompts()
    elif args.preview:
        preview(args.preview)
    else:
        ap.print_help(sys.stderr)


if __name__ == "__main__":
    main()
