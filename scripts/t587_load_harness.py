#!/usr/bin/env python3
"""T587 load/simulation harness for Bayes MVP readiness.

Performs concurrent HTTP GET load tests against configured endpoints and emits
summary metrics suitable for launch-gate evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Sample:
    ok: bool
    status: int | None
    latency_ms: float
    endpoint: str
    error: str | None = None


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def hit(base_url: str, endpoint: str, timeout_s: float) -> Sample:
    url = f"{base_url.rstrip('/')}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            _ = resp.read()
            dt = (time.perf_counter() - t0) * 1000.0
            return Sample(ok=(200 <= resp.status < 300), status=resp.status, latency_ms=dt, endpoint=endpoint)
    except urllib.error.HTTPError as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return Sample(ok=False, status=e.code, latency_ms=dt, endpoint=endpoint, error=str(e))
    except Exception as e:  # noqa: BLE001
        dt = (time.perf_counter() - t0) * 1000.0
        return Sample(ok=False, status=None, latency_ms=dt, endpoint=endpoint, error=str(e))


def run_load(base_url: str, endpoint: str, total_requests: int, concurrency: int, timeout_s: float) -> list[Sample]:
    samples: list[Sample] = []
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(hit, base_url, endpoint, timeout_s) for _ in range(total_requests)]
        for fut in cf.as_completed(futs):
            samples.append(fut.result())
    return samples


def summarize(samples: Iterable[Sample], endpoint: str, duration_s: float) -> dict:
    lst = list(samples)
    lat = sorted([s.latency_ms for s in lst])
    oks = [s for s in lst if s.ok]
    errs = [s for s in lst if not s.ok]
    statuses: dict[str, int] = {}
    for s in lst:
        key = str(s.status) if s.status is not None else "error"
        statuses[key] = statuses.get(key, 0) + 1

    return {
        "endpoint": endpoint,
        "requests": len(lst),
        "success_count": len(oks),
        "error_count": len(errs),
        "success_rate": (len(oks) / len(lst)) if lst else 0.0,
        "rps": (len(lst) / duration_s) if duration_s > 0 else 0.0,
        "latency_ms": {
            "min": min(lat) if lat else 0.0,
            "p50": _pct(lat, 0.50),
            "p95": _pct(lat, 0.95),
            "p99": _pct(lat, 0.99),
            "max": max(lat) if lat else 0.0,
            "mean": statistics.fmean(lat) if lat else 0.0,
        },
        "status_counts": statuses,
        "sample_errors": [e.error for e in errs[:5]],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bayes MVP load/simulation harness")
    p.add_argument("--base-url", default="http://127.0.0.1:3205", help="Base URL (default: %(default)s)")
    p.add_argument("--endpoints", default="/healthz,/", help="Comma-separated endpoints (default: %(default)s)")
    p.add_argument("--requests", type=int, default=200, help="Requests per endpoint (default: %(default)s)")
    p.add_argument("--concurrency", type=int, default=20, help="Concurrent workers (default: %(default)s)")
    p.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout seconds (default: %(default)s)")
    p.add_argument(
        "--out",
        default="apps/bayes-market/docs/artifacts/t587-load-harness-latest.json",
        help="Output JSON path (default: %(default)s)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    endpoints = [e.strip() for e in args.endpoints.split(",") if e.strip()]

    overall_started = time.time()
    results: list[dict] = []

    for endpoint in endpoints:
        started = time.perf_counter()
        samples = run_load(args.base_url, endpoint, args.requests, args.concurrency, args.timeout)
        duration_s = time.perf_counter() - started
        results.append(summarize(samples, endpoint, duration_s))

    payload = {
        "harness": "t587_load_harness.py",
        "base_url": args.base_url,
        "requests_per_endpoint": args.requests,
        "concurrency": args.concurrency,
        "timeout_s": args.timeout,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": time.time() - overall_started,
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    print(f"\nWrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
