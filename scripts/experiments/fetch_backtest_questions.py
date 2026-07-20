#!/usr/bin/env python3
"""Source REAL, already-resolved, relationally-linked questions for the backtest.

Ground truth must be real — never fabricated. This pulls resolved BINARY
markets from the public Manifold API and finds two kinds of real relational
structure with known outcomes:

  1. Implication ladders: "<stem> before/by YEAR" for several years by one
     creator. The logical structure is exact (before Y implies before Y+1),
     and the resolved outcomes are real. The informative ladders are the ones
     with a YES->... transition (the event happened in some year).
  2. (extensible) resolved conditional/joint pairs.

Writes a curated question-set JSON the backtest harness consumes:
  {question_id, title, resolvedOutcome (yes/no), createdAt, closeAt,
   earlyProbability (point-in-time signal), group, ladderRank}

Stdlib + optional certifi. Read-only against Manifold.

    PYTHONPATH=. python3 scripts/experiments/fetch_backtest_questions.py --out set.json
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

MANIFOLD = "https://api.manifold.markets/v0"
UA = "bayes-market-backtest-sourcing/0.1 (research; futarchy.ai)"
YEAR_RE = re.compile(r"\b(20[12]\d)\b")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CTX = _ctx()


def fetch(path: str):
    req = urllib.request.Request(MANIFOLD + path, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(1.5 * (2 ** attempt))
    return None


def search(term: str, limit: int = 60) -> list:
    q = urllib.parse.urlencode({"term": term, "filter": "resolved",
                                "contractType": "BINARY", "limit": limit})
    return fetch(f"/search-markets?{q}") or []


def early_probability(market_id: str) -> float | None:
    """A point-in-time signal: the market probability ~early in its life,
    reconstructed from the first bets (avoids look-ahead to the final price)."""
    bets = fetch(f"/bets?contractId={market_id}&limit=8&order=asc")
    if not bets:
        return None
    for b in bets:
        p = b.get("probAfter")
        if isinstance(p, (int, float)):
            return float(p)
    return None


# Asset price-threshold ladders: real, resolved, exact monotone structure
# (above $X implies above $Y for Y<X on the same date), varied outcomes.
THRESHOLD_TERMS = [
    "Bitcoin above", "BTC above", "Bitcoin closes above", "Ethereum above",
    "ETH above", "S&P above", "S&P 500 above", "Nasdaq above",
]
_AMT_RE = re.compile(r"\$?\s?([\d][\d,\.]*)\s?([KkMm]?)")
_DATE_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}",
    re.I)


def _amount(text: str) -> float | None:
    m = _AMT_RE.search(text.split("above", 1)[-1])
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v * {"k": 1e3, "m": 1e6, "": 1.0}[m.group(2).lower()]


def _date_key(title: str) -> str | None:
    m = _DATE_RE.search(title)
    return m.group(0).lower().replace(".", "") if m else None


def _asset(title: str) -> str:
    t = title.lower()
    for name, key in (("bitcoin", "BTC"), ("btc", "BTC"), ("ethereum", "ETH"),
                      ("eth", "ETH"), ("nasdaq", "NASDAQ"), ("s&p", "SP500")):
        if name in t:
            return key
    return "?"


def collect_ladders(min_len: int = 3, want_transition: bool = True) -> list[dict]:
    """Same-asset, same-date price-threshold ladders with real outcomes."""
    seen: dict[str, dict] = {}
    for term in THRESHOLD_TERMS:
        for m in search(term):
            if m.get("outcomeType") != "BINARY" or not m.get("isResolved"):
                continue
            res = str(m.get("resolution", "")).upper()
            if res not in ("YES", "NO"):
                continue
            title = m["question"]
            amt, dk = _amount(title), _date_key(title)
            if amt is None or dk is None:
                continue
            seen[m["id"]] = {
                "id": m["id"], "slug": m.get("slug"), "title": title,
                "asset": _asset(title), "threshold": amt, "dateKey": dk,
                "resolution": res, "createdTime": m.get("createdTime"),
                "closeTime": m.get("closeTime"),
            }
        time.sleep(1.0)

    groups: dict[tuple, list] = defaultdict(list)
    for m in seen.values():
        groups[(m["asset"], m["dateKey"])].append(m)

    ladders = []
    for (asset, dk), members in groups.items():
        if len(members) < min_len:
            continue
        members.sort(key=lambda x: x["threshold"])
        # monotone check: YES thresholds must all sit below NO thresholds
        yes_max = max((x["threshold"] for x in members if x["resolution"] == "YES"),
                      default=-1)
        no_min = min((x["threshold"] for x in members if x["resolution"] == "NO"),
                     default=1e18)
        monotone = yes_max < no_min  # real price bracket -> coherent step
        outcomes = [x["resolution"] for x in members]
        if want_transition and not ("YES" in outcomes and "NO" in outcomes):
            continue
        if not monotone:
            continue  # drop noisy/ambiguous resolutions
        ladders.append({"asset": asset, "dateKey": dk, "members": members,
                        "outcomes": outcomes,
                        "impliedPrice": (yes_max, no_min)})
    return ladders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-len", type=int, default=3)
    ap.add_argument("--with-early", action="store_true",
                    help="also fetch point-in-time early probabilities (slow)")
    args = ap.parse_args()

    ladders = collect_ladders(min_len=args.min_len)
    print(f"found {len(ladders)} resolved threshold ladders "
          f"(len>={args.min_len}, coherent YES/NO step)", file=sys.stderr)
    for lad in ladders[:15]:
        step = " ".join(f"${m['threshold']/1e3:.0f}K:{m['resolution'][0]}"
                        for m in lad["members"])
        print(f"  {lad['asset']:5} {lad['dateKey']:14}  {step}", file=sys.stderr)

    if args.with_early:
        for lad in ladders:
            for m in lad["members"]:
                m["earlyProbability"] = early_probability(m["id"])
                time.sleep(0.3)

    if args.out:
        json.dump(ladders, open(args.out, "w"), indent=1)
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
