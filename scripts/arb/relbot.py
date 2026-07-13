#!/usr/bin/env python3
"""relbot v0 — relationship-order engine over Manifold (read-only core).

The mechanism from the 2026-07-12 Gurkenglas conversation, staged:

  1. A RELATIONSHIP BOOK: logical relationships between markets, each with a
     declarer. v0 sources: (a) auto-detected same-title equivalences across
     creators, (b) auto-detected by-year implication ladders within a
     creator's series, (c) user-declared entries from relationships.json
     (mirrors backend/formula_schema.py's spirit: literals over market ids).
  2. A SOLVER: for each relationship, check whether live AMM prices admit a
     bundle whose payoff at resolution is >= its cost in EVERY consistent
     world (riskless at resolution; capital is locked until then — this is
     where platform credit would enter).
  3. EXECUTION + attribution (who declared the binding relationship gets the
     cut) — NOT in v0: this script never trades; it prices and reports.

Riskless bundles used (unit pair pays exactly 1 in every consistent world):
  A implies B, price(A) > price(B):  buy B-YES + buy A-NO
  A equiv  B, price(A) < price(B):   buy A-YES + buy B-NO

Sizing integrates Manifold's Maniswap (cpmm-1) curve: the pool state is
fetched live, the share-out function is verified against the market's own
displayed probability before being trusted, and profit is maximized over the
bundle size (marginal cost of the two legs rises to 1 as you size up).

Stdlib only (+ optional certifi). Usage:
    python3 scripts/arb/relbot.py
    python3 scripts/arb/relbot.py --book scripts/arb/relationships.json --out /tmp/relbot.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BAYES_BASE = os.environ.get("BAYES_API_URL", "http://127.0.0.1:3210")
PAPER_BASE = "https://bayes.futarchy.ai"
MANIFOLD_BASE = "https://api.manifold.markets/v0"
USER_AGENT = "bayes-market-relbot/0.1 (research script for futarchy.ai bayes-market)"
MAX_LEG_MANA = 5000.0  # per-leg sizing cap so a pool is never dominated


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def fetch_json(url: str, timeout: float = 20.0):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                return None
            time.sleep(1.5 * (2**attempt))
        except Exception:
            time.sleep(1.5 * (2**attempt))
    return None


def bayes_markets(base: str, paper: bool = False) -> list[dict]:
    path = "/v1/markets" if paper else "/v1/net/markets?fields=graph"
    payload = fetch_json(f"{base}{path}")
    markets = payload["markets"] if isinstance(payload, dict) else payload
    return [m for m in markets if m.get("status") not in ("closed", "resolved", "void")]


# --------------------------------------------------------------------------
# Maniswap (cpmm-1) share math, self-verified against the displayed price.
# Pool holds YES shares y and NO shares n; weight p; probability of YES is
#   prob = p * n / (p * n + (1 - p) * y)
# Buying YES with M mana: both pools gain M, then s YES shares leave keeping
#   (y + M - s)^p * (n + M)^(1-p) = y^p * n^(1-p)
# --------------------------------------------------------------------------


def cpmm_prob(y: float, n: float, p: float) -> float:
    return p * n / (p * n + (1.0 - p) * y)


def shares_out(y: float, n: float, p: float, mana: float, side: str) -> float:
    if mana <= 0:
        return 0.0
    if side == "YES":
        k = (y**p) * (n ** (1.0 - p))
        return y + mana - (k / ((n + mana) ** (1.0 - p))) ** (1.0 / p)
    k = (n ** (1.0 - p)) * (y**p)
    return n + mana - (k / ((y + mana) ** p)) ** (1.0 / (1.0 - p))


def mana_for_shares(y: float, n: float, p: float, target: float, side: str) -> float:
    """Invert shares_out by bisection (shares_out is increasing in mana)."""
    if target <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    while shares_out(y, n, p, hi, side) < target:
        hi *= 2.0
        if hi > 1e9:
            return float("inf")
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if shares_out(y, n, p, mid, side) < target:
            lo = mid
        else:
            hi = mid
    return hi


class Leg:
    def __init__(self, market: dict, side: str):
        self.market = market
        self.side = side
        self.y = float(market["pool"]["YES"])
        self.n = float(market["pool"]["NO"])
        self.p = float(market.get("p") or 0.5)

    def cost(self, shares: float) -> float:
        return mana_for_shares(self.y, self.n, self.p, shares, self.side)


def best_bundle(leg_a: Leg, leg_b: Leg) -> dict:
    """Maximize S - cost_a(S) - cost_b(S); the pair pays exactly S at resolution."""

    def profit(shares: float) -> float:
        return shares - leg_a.cost(shares) - leg_b.cost(shares)

    hi = 1.0
    while (
        profit(hi * 2) > profit(hi)
        and leg_a.cost(hi * 2) < MAX_LEG_MANA
        and leg_b.cost(hi * 2) < MAX_LEG_MANA
    ):
        hi *= 2.0
        if hi > 1e7:
            break
    lo = 0.0
    for _ in range(70):  # ternary search on the concave profit curve
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if profit(m1) < profit(m2):
            lo = m1
        else:
            hi = m2
    shares = (lo + hi) / 2.0
    return {
        "shares": round(shares, 2),
        "cost_a": round(leg_a.cost(shares), 2),
        "cost_b": round(leg_b.cost(shares), 2),
        "guaranteed_profit": round(profit(shares), 2),
    }


# --------------------------------------------------------------------------
# Relationship book
# --------------------------------------------------------------------------

YEAR_RE = re.compile(r"(19|20)\d{2}")


def normalize_title(title: str) -> str:
    text = YEAR_RE.sub("YYYY", title.lower())
    text = re.sub(r"[^a-z ]", " ", text)
    return " ".join(text.split())


def auto_book(markets: dict[str, dict]) -> list[dict]:
    """Detect equivalence candidates and by-year implication ladders."""
    book: list[dict] = []
    by_title: dict[str, list[str]] = defaultdict(list)
    series: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)

    for mid, market in markets.items():
        title = market.get("question") or ""
        by_title[title.strip().lower()].append(mid)
        match = YEAR_RE.search(title)
        if match:
            key = (market.get("creatorUsername", "?"), normalize_title(title))
            series[key].append((int(match.group(0)), mid))

    for title, ids in by_title.items():
        for a, b in zip(ids, ids[1:]):
            book.append(
                {"type": "equiv", "a": a, "b": b, "declaredBy": "auto:same-title",
                 "note": "cross-creator duplicate — VERIFY resolution criteria match"}
            )
    for (creator, stem), items in series.items():
        if len(items) < 2 or not any(w in stem for w in ("before", "by yyyy", "until")):
            continue
        items.sort()
        for (y1, a), (y2, b) in zip(items, items[1:]):
            if y2 > y1:
                book.append(
                    {"type": "implies", "a": a, "b": b,
                     "declaredBy": f"auto:year-ladder:{creator}",
                     "note": f"'by {y1}' implies 'by {y2}' (same creator series)"}
                )
    return book


def load_user_book(path: str | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    entries = json.loads(Path(path).read_text())
    for entry in entries:
        entry.setdefault("declaredBy", "user")
    return entries


def joint_probabilities(market: dict, truth_table: dict) -> tuple[float, float]:
    """Return the A and B marginals from an exact-text 2x2 answer mapping."""
    answers = market.get("answers") or []

    def cell_sum(*cells: str) -> float:
        texts = {truth_table[cell] for cell in cells}
        return sum(float(answer["probability"]) for answer in answers
                   if answer.get("text") in texts)

    return (cell_sum("a_yes_b_yes", "a_yes_b_no"),
            cell_sum("a_yes_b_yes", "a_no_b_yes"))


def joint_marginal_gap(joint_p: float, binary_p: float) -> float:
    return round(joint_p - binary_p, 4)


def evaluate_joints(entries: list[dict]) -> dict:
    """Fetch joint markets and compare their marginals with declared binaries."""
    joints, gaps = [], []
    for entry in entries:
        slug = entry["joint_slug"]
        market = fetch_json(f"{MANIFOLD_BASE}/slug/{slug}")
        if (not isinstance(market, dict) or market.get("isResolved")
                or market.get("mechanism") != "cpmm-multi-1"):
            continue
        try:
            prob_a, prob_b = joint_probabilities(market, entry["truthTable"])
        except (KeyError, TypeError, ValueError):
            continue
        prob_a, prob_b = round(prob_a, 4), round(prob_b, 4)
        joints.append({"slug": slug, "name": entry["name"],
                       "pA": prob_a, "pB": prob_b})

        # Multichoice auto-arb sizing is future work; these checks are report-only.
        for leg, joint_p in (("A", prob_a), ("B", prob_b)):
            for binary_id in entry.get(f"binary{leg}", []):
                binary = fetch_json(f"{MANIFOLD_BASE}/market/{binary_id}")
                if (not isinstance(binary, dict) or binary.get("isResolved")
                        or binary.get("probability") is None):
                    continue
                binary_p = round(float(binary["probability"]), 4)
                gaps.append({
                    "leg": leg, "joint_slug": slug, "joint_p": joint_p,
                    "binary_id": binary_id, "binary_p": binary_p,
                    "gap": joint_marginal_gap(joint_p, binary_p),
                    "declaredBy": entry["declaredBy"],
                    "note": entry.get("note", ""),
                })
    return {"joints": joints, "gaps": gaps}


def evaluate(rel: dict, markets: dict[str, dict]) -> dict | None:
    market_a, market_b = markets.get(rel["a"]), markets.get(rel["b"])
    if not market_a or not market_b:
        return None
    if market_a.get("isResolved") or market_b.get("isResolved"):
        return None
    prob_a, prob_b = market_a.get("probability"), market_b.get("probability")
    if prob_a is None or prob_b is None:
        return None

    result = {
        **{k: rel[k] for k in ("type", "a", "b", "declaredBy")},
        "note": rel.get("note", ""),
        "title_a": market_a.get("question", "")[:80],
        "title_b": market_b.get("question", "")[:80],
        "prob_a": round(prob_a, 4),
        "prob_b": round(prob_b, 4),
        "violated": False,
    }
    if rel["type"] == "implies" and prob_a > prob_b:
        result["violated"] = True
        result["gross_gap"] = round(prob_a - prob_b, 4)
        result["bundle"] = {"legs": [f"buy YES {rel['b']}", f"buy NO {rel['a']}"],
                            **best_bundle(Leg(market_b, "YES"), Leg(market_a, "NO"))}
    elif rel["type"] == "equiv" and abs(prob_a - prob_b) > 1e-9:
        low, high = (rel["a"], rel["b"]) if prob_a < prob_b else (rel["b"], rel["a"])
        result["violated"] = True
        result["gross_gap"] = round(abs(prob_a - prob_b), 4)
        result["bundle"] = {"legs": [f"buy YES {low}", f"buy NO {high}"],
                            **best_bundle(Leg(markets[low], "YES"), Leg(markets[high], "NO"))}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None)
    parser.add_argument("--paper", action="store_true",
                        default=os.environ.get("BAYES_BACKEND", "").lower() == "paper",
                        help="read the legacy paper backend")
    parser.add_argument("--book", default=None, help="user relationships.json")
    parser.add_argument("--out", default=None)
    parser.add_argument("--min-profit", type=float, default=1.0,
                        help="only surface bundles with >= this guaranteed mana")
    args = parser.parse_args()

    base = args.base or (PAPER_BASE if args.paper else BAYES_BASE)
    local_markets = bayes_markets(base, args.paper)
    refs = sorted(
        {m["anchor"]["ref"] for m in local_markets
         if (m.get("anchor") or {}).get("source") == "manifold"}
    )
    print(f"fetching {len(refs)} manifold market objects…", file=sys.stderr)

    def grab(ref: str):
        time.sleep(0.1)
        return ref, fetch_json(f"{MANIFOLD_BASE}/market/{ref}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        markets = {ref: data for ref, data in pool.map(grab, refs)
                   if isinstance(data, dict) and data.get("mechanism") == "cpmm-1"
                   and data.get("pool")}

    # Trust gate: our AMM math must reproduce each market's displayed price.
    trusted, dropped = {}, 0
    for ref, market in markets.items():
        model = cpmm_prob(float(market["pool"]["YES"]), float(market["pool"]["NO"]),
                          float(market.get("p") or 0.5))
        if abs(model - float(market.get("probability", -1))) < 0.005:
            trusted[ref] = market
        else:
            dropped += 1
    print(f"cpmm model verified on {len(trusted)} markets ({dropped} dropped)",
          file=sys.stderr)

    default_joint_book = Path(__file__).with_name("relationships_evand.json")
    declared = load_user_book(args.book) + load_user_book(str(default_joint_book))
    joint_entries = [r for r in declared if r.get("type") == "joint_marginal"]
    book = auto_book(trusted) + [r for r in declared
                                 if r.get("type") != "joint_marginal"]
    results = [r for rel in book if (r := evaluate(rel, trusted))]
    violations = [r for r in results if r["violated"]]
    profitable = [r for r in violations
                  if r["bundle"]["guaranteed_profit"] >= args.min_profit]
    profitable.sort(key=lambda r: -r["bundle"]["guaranteed_profit"])

    joint_checks = evaluate_joints(joint_entries)
    report = {
        "relationships_checked": len(results),
        "violated": len(violations),
        "profitable_after_slippage": len(profitable),
        "total_guaranteed_mana": round(
            sum(r["bundle"]["guaranteed_profit"] for r in profitable), 2),
        "bundles": profitable,
        "all_violations": violations,
        "joint_marginal_checks": joint_checks,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))

    print(json.dumps({k: report[k] for k in
                      ("relationships_checked", "violated",
                       "profitable_after_slippage", "total_guaranteed_mana",
                       "joint_marginal_checks")}, indent=1))
    for r in profitable[:15]:
        b = r["bundle"]
        print(f"\n  [{r['type']}] {r['title_a']}  vs  {r['title_b']}"
              f"\n    probs {r['prob_a']} / {r['prob_b']}  gross gap {r['gross_gap']}"
              f"\n    bundle: {b['legs']}  size {b['shares']} shares"
              f"  cost {b['cost_a']}+{b['cost_b']}  GUARANTEED +{b['guaranteed_profit']} mana"
              f"\n    declaredBy {r['declaredBy']}  {r['note']}")
    if not profitable:
        print("\n  no bundle clears the profit floor after slippage right now")
    for gap in joint_checks["gaps"]:
        print(f"\n  [joint_marginal:{gap['leg']}] {gap['joint_slug']}"
              f"\n    joint {gap['joint_p']} / binary {gap['binary_p']}"
              f"  gap {gap['gap']}  binary {gap['binary_id']}"
              f"\n    declaredBy {gap['declaredBy']}  {gap['note']}")


if __name__ == "__main__":
    main()
