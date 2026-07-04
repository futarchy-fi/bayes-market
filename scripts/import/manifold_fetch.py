#!/usr/bin/env python3
"""Manifold Markets importer for bayes-market.

Searches a curated set of AI-takeoff / transformative-AI (TAI) term queries
against the public Manifold Markets API (no key required), filters to open
BINARY markets with enough trader engagement and forecasting horizon left,
scores each surviving market for relevance, and writes
scripts/import/data/manifold_candidates.json.

Only uses the Python standard library (urllib.request, json, etc). Talks to
https://api.manifold.markets/v0. Sends a descriptive User-Agent because some
CDNs 403 the default urllib UA.

Usage:
    python3 scripts/import/manifold_fetch.py
    python3 scripts/import/manifold_fetch.py --limit 3 --skip-descriptions
    python3 scripts/import/manifold_fetch.py --min-bettors 8 --min-days-out 30

Run from anywhere; output path defaults to
scripts/import/data/manifold_candidates.json next to this file.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.manifold.markets/v0"
USER_AGENT = (
    "bayes-market-importer/0.1 "
    "(research script for futarchy.ai bayes-market; contact: kas@futarchy.ai)"
)
REQUEST_INTERVAL_SEC = 1.0
MAX_RETRIES = 5
BACKOFF_BASE_SEC = 2.0
BACKOFF_MAX_SEC = 30.0

# ---------------------------------------------------------------------------
# Curated query terms, each tagged with a relevance tier:
#   1 = core AI-takeoff / AGI concept
#   2 = strongly related structural, economic, or governance driver
#   3 = broader context that still matters for TAI modeling
# A market's final tier is the *best* (lowest-numbered) tier among all the
# terms whose search results surfaced it.
# ---------------------------------------------------------------------------
QUERY_TERMS = [
    ("takeoff", 1),
    ("AGI", 1),
    ("superintelligence", 1),
    ("transformative AI", 1),
    ("AI automation", 2),
    ("frontier model", 2),
    ("training compute", 2),
    ("AI GDP", 2),
    ("AI unemployment", 2),
    ("AI regulation", 2),
    ("AI treaty", 2),
    ("AI moratorium", 2),
    ("open weights", 3),
    ("AI benchmark", 3),
    ("AI agents", 2),
    ("AI R&D automation", 1),
    ("GPT-6", 2),
    ("GPT-7", 2),
    ("AI datacenter", 2),
    ("AI energy", 3),
    ("AI chip export", 2),
    ("AI alignment", 2),
    ("AI catastrophe", 1),
    ("AI capabilities 2030", 1),
    ("economic growth AI", 2),
    # a few extra terms judged useful for broader TAI coverage
    ("AI safety", 2),
    ("compute governance", 2),
    ("AI existential risk", 1),
    ("recursive self-improvement", 1),
    ("AI winter", 3),
]

# /v0/search-markets supports `topicSlug` (confirmed against
# docs.manifold.markets/api as of 2026-07). Pull these topic tags too.
TOPIC_SLUGS = [
    ("ai", 2),
    ("ai-safety", 1),
]

CONDITIONAL_PATTERNS = [
    re.compile(r"\bconditional on\b", re.I),
    re.compile(r"^if\b.{3,100}\bwill\b", re.I),
    re.compile(r"\bassuming\b.{0,80}\bwill\b", re.I),
    re.compile(r"\bgiven that\b", re.I),
    re.compile(r"\bin the event that\b", re.I),
]


def is_conditional(question):
    q = question or ""
    return any(p.search(q) for p in CONDITIONAL_PATTERNS)


# ---------------------------------------------------------------------------
# HTTP plumbing: 1 req/sec throttle, retry with backoff on 429/5xx.
# ---------------------------------------------------------------------------
_last_request_monotonic = [0.0]


def _throttle():
    now = time.monotonic()
    elapsed = now - _last_request_monotonic[0]
    if elapsed < REQUEST_INTERVAL_SEC:
        time.sleep(REQUEST_INTERVAL_SEC - elapsed)
    _last_request_monotonic[0] = time.monotonic()


def http_get_json(path, params):
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{query}"

    delay = BACKOFF_BASE_SEC
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 or 500 <= e.code < 600:
                if attempt == MAX_RETRIES:
                    break
                print(
                    f"  ! HTTP {e.code} for {url} (attempt {attempt}/{MAX_RETRIES}), "
                    f"retrying in {delay:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_SEC)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt == MAX_RETRIES:
                break
            print(
                f"  ! network error for {url}: {e} "
                f"(attempt {attempt}/{MAX_RETRIES}), retrying in {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX_SEC)
    raise RuntimeError(f"giving up on {url}: {last_err}")


def search_markets(term, topic_slug=None, limit=300, contract_type="BINARY", filt="open"):
    params = {
        "term": term,
        "contractType": contract_type,
        "filter": filt,
        "limit": limit,
    }
    if topic_slug is not None:
        params["topicSlug"] = topic_slug
    return http_get_json("/search-markets", params)


def fetch_full_market(market_id):
    try:
        return http_get_json(f"/market/{market_id}", {})
    except Exception as e:
        print(f"  ! failed to fetch full market {market_id}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Search phase
# ---------------------------------------------------------------------------
def record_results(seen, results, matched_label, tier):
    added = 0
    for m in results:
        mid = m.get("id")
        if not mid:
            continue
        if mid not in seen:
            seen[mid] = {"market": m, "matchedTerms": set(), "best_tier": tier}
            added += 1
        seen[mid]["matchedTerms"].add(matched_label)
        seen[mid]["best_tier"] = min(seen[mid]["best_tier"], tier)
    return added


def run_searches(args):
    seen = {}
    term_queries = QUERY_TERMS
    if args.limit is not None:
        term_queries = term_queries[: args.limit]

    total = len(term_queries) + (0 if args.limit is not None else len(TOPIC_SLUGS))
    idx = 0

    for term, tier in term_queries:
        idx += 1
        print(f"[{idx}/{total}] term={term!r} (tier {tier})...", flush=True)
        try:
            results = search_markets(term=term, limit=args.search_page_size)
        except Exception as e:
            print(f"  ! search failed for term={term!r}: {e}", file=sys.stderr)
            continue
        added = record_results(seen, results, f"term:{term}", tier)
        print(f"    -> {len(results)} results, {added} new unique markets")

    if args.limit is None:
        for slug, tier in TOPIC_SLUGS:
            idx += 1
            print(f"[{idx}/{total}] topicSlug={slug!r} (tier {tier})...", flush=True)
            try:
                results = search_markets(term="", topic_slug=slug, limit=args.search_page_size)
            except Exception as e:
                print(f"  ! search failed for topicSlug={slug!r}: {e}", file=sys.stderr)
                continue
            added = record_results(seen, results, f"topic:{slug}", tier)
            print(f"    -> {len(results)} results, {added} new unique markets")

    return seen


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def passes_filters(m, min_bettors, min_days_out):
    if m.get("outcomeType") != "BINARY":
        return False
    if m.get("isResolved"):
        return False
    close_time = m.get("closeTime")
    if close_time is None:
        return False
    now_ms = time.time() * 1000
    if close_time <= now_ms + min_days_out * 86400 * 1000:
        return False
    if (m.get("uniqueBettorCount") or 0) < min_bettors:
        return False
    return True


def ms_to_iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_candidate(entry, args):
    m = entry["market"]
    mid = m["id"]
    record = {
        "id": mid,
        "question": m.get("question", ""),
        "url": m.get("url", ""),
        "probability": m.get("probability"),
        "uniqueBettorCount": m.get("uniqueBettorCount", 0),
        "closeTime": ms_to_iso(m.get("closeTime")),
        "volume": m.get("volume", 0),
        "textDescription": "",
        "matchedTerms": sorted(entry["matchedTerms"]),
        "tier": entry["best_tier"],
        "conditional": is_conditional(m.get("question", "")),
    }
    if not args.skip_descriptions:
        full = fetch_full_market(mid)
        if full:
            desc = full.get("textDescription") or ""
            record["textDescription"] = desc[:500]
    return record


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_summary(total_fetched, candidates):
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"Total unique markets fetched across all queries: {total_fetched}")
    print(f"Candidates after filters:                        {len(candidates)}")

    tiers = Counter(c["tier"] for c in candidates)
    print("\nTier histogram:")
    for tier in sorted(tiers):
        print(f"  tier {tier}: {tiers[tier]}")

    n_conditional = sum(1 for c in candidates if c["conditional"])
    print(f"\nConditional-form questions flagged: {n_conditional}")

    print("\nTop 20 (sorted by tier, then uniqueBettorCount desc):")
    for c in candidates[:20]:
        prob = c["probability"]
        prob_str = f"{prob * 100:5.1f}%" if isinstance(prob, (int, float)) else "  n/a"
        print(f"  [T{c['tier']}] {prob_str}  ({c['uniqueBettorCount']:>4} bettors)  {c['question']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N query terms and skip topic-slug queries "
        "(smoke test / fast iteration)",
    )
    p.add_argument(
        "--search-page-size",
        type=int,
        default=300,
        help="Number of results requested per search query (API 'limit' param, max 1000)",
    )
    p.add_argument(
        "--min-bettors",
        type=int,
        default=15,
        help="Minimum uniqueBettorCount to keep a market",
    )
    p.add_argument(
        "--min-days-out",
        type=int,
        default=30,
        help="Minimum days until market close to keep a market",
    )
    p.add_argument(
        "--skip-descriptions",
        action="store_true",
        help="Skip fetching full market descriptions (faster smoke test; "
        "textDescription will be empty)",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: scripts/import/data/manifold_candidates.json "
        "next to this script)",
    )
    return p.parse_args()


def main():
    args = parse_args()

    print("Phase 1: searching Manifold Markets...")
    seen = run_searches(args)
    print(f"\nTotal unique markets found across all queries: {len(seen)}")

    print("\nPhase 2: filtering (BINARY, open, closeTime > now+"
          f"{args.min_days_out}d, uniqueBettorCount >= {args.min_bettors})...")
    filtered = [e for e in seen.values() if passes_filters(e["market"], args.min_bettors, args.min_days_out)]
    print(f"Markets passing filters: {len(filtered)}")

    print("\nPhase 3: fetching descriptions & building candidate records...")
    candidates = []
    for i, entry in enumerate(filtered, 1):
        q = entry["market"].get("question", "")[:60]
        print(f"  [{i}/{len(filtered)}] {q!r}")
        candidates.append(build_candidate(entry, args))

    candidates.sort(key=lambda c: (c["tier"], -c["uniqueBettorCount"]))

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent / "data" / "manifold_candidates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"\nWrote {len(candidates)} candidates to {out_path}")

    print_summary(len(seen), candidates)


if __name__ == "__main__":
    main()
