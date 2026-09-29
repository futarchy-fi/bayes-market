#!/usr/bin/env python3
"""Import one Radiant project's binary variables as seeds-v1 markets (read-only).

Reads the canvas, the live Metaculus community prediction (via Radiant's
get_metaculus_posts) and the formula simulation over Radiant MCP; writes a
seeds-v1 file for BAYES_SEEDS_PATH. Nothing is written to Radiant or Metaculus:
the client refuses every tool outside READ_TOOLS.

  RADIANT_API_TOKEN=... python3 scripts/import/radiant_seeds.py \
      --project <uuid> --out radiant_seeds.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_seeds_external import clamp, year_from_title  # noqa: E402  same clamp/expiry rule

MCP_URL = "https://radiant.metaculus.com/mcp"
# Refuse redirects so the bearer token never follows a 3xx to another host.
_OPENER = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                                           {"redirect_request": lambda *a, **k: None})())
READ_TOOLS = frozenset({"read_canvas", "simulate_forecast_model", "get_metaculus_posts"})
CONTEXT = "Reading a forecasting canvas to import its binary variables into a prediction market."


class Radiant:
    """Minimal MCP (streamable HTTP) client restricted to READ_TOOLS."""

    def __init__(self, token: str):
        self.token, self.session, self.n = token, None, 0

    def _post(self, body: dict) -> dict | None:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "User-Agent": "bayes-market-radiant-seeds/1"}  # urllib's default UA gets 403
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(MCP_URL, json.dumps(body).encode(), headers)
        with _OPENER.open(req, timeout=180) as resp:
            self.session = resp.headers.get("Mcp-Session-Id") or self.session
            raw = resp.read().decode()
            if "text/event-stream" in (resp.headers.get("Content-Type") or ""):
                raw = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")][-1]
        return json.loads(raw) if raw.strip() else None

    def _rpc(self, method: str, params: dict) -> dict:
        self.n += 1
        out = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        if "error" in out:
            raise RuntimeError(f"{method}: {out['error']}")
        return out["result"]

    def call(self, name: str, args: dict):
        if name not in READ_TOOLS:
            raise PermissionError(f"refusing non-read Radiant tool {name!r}")
        if self.session is None:
            self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "bayes-market-radiant-seeds", "version": "1"}})
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        res = self._rpc("tools/call", {"name": name, "arguments":
                                       {**args, "context": CONTEXT, "llm_model": "unknown"}})
        text = res["content"][0]["text"]
        if res.get("isError"):
            raise RuntimeError(f"{name}: {text[:300]}")
        return json.loads(text)


def binary_kind(node: dict) -> str | None:
    """'metaculus' | 'probability' | 'formula' for binary variables, else None."""
    t, d = node["node_type"], node.get("data") or {}
    if t == "metaculus-question-node" and (d.get("metaculus") or {}).get("type") == "binary":
        return "metaculus"
    if t == "forecast-binary-probability-node":
        return "probability"
    if t == "forecast-formula-node" and (d.get("forecasting") or {}).get("outputType") == "probability":
        return "formula"
    return None


def fetch(client: Radiant, project_id: str) -> tuple[dict, dict, dict | None]:
    """Canvas, {post_id: post}, and simulation (None if no probability formulas)."""
    canvas = client.call("read_canvas", {"project_id": project_id})
    kinds = [(binary_kind(n), n) for n in canvas["nodes"]]
    post_ids = sorted({int(n["data"]["metaculus"]["post_id"]) for k, n in kinds if k == "metaculus"})
    posts = {int(p["id"]): p for p in client.call("get_metaculus_posts", {"post_ids": post_ids})["posts"]} \
        if post_ids else {}
    has_formula = any(k == "formula" for k, _ in kinds)
    sim = client.call("simulate_forecast_model",
                      {"project_id": project_id, "seed": 1, "iterations": 10000}) if has_formula else None
    if sim is not None and sim.get("status") != "ok":
        sys.exit(f"simulation failed: {sim.get('status')}")  # never a seeds file missing every formula
    return canvas, posts, sim


def build(project_id: str, canvas: dict, posts: dict, sim: dict | None, now: str):
    """Pure mapping -> (seeds-v1 dict, skipped counts, listed binary skips)."""
    skipped: Counter = Counter()
    listed: list[dict] = []
    markets: dict[str, dict] = {}
    vid_of: dict[str, str] = {}  # node id -> variableId
    prefix = f"r{project_id[:8].lower()}_"
    sim_nodes = (sim or {}).get("nodes", {})

    for node in canvas["nodes"]:
        kind, d = binary_kind(node), node.get("data") or {}
        if kind is None:
            skipped[f"metaculus:{d['metaculus'].get('type')}" if d.get("metaculus") else node["node_type"]] += 1
            continue
        ref = (d.get("forecasting") or {}).get("ref") or ""
        meta, post, reason = d.get("metaculus") or {}, None, None
        if kind == "metaculus":
            post = posts.get(int(meta["post_id"]))
            q = (post or {}).get("question") or {}
            latest = ((q.get("aggregations") or {}).get("recency_weighted") or {}).get("latest") or {}
            prob = (latest.get("centers") or [None])[0]
            if post and (post.get("status") != "open" or (post.get("scheduled_close_time") or now) < now):
                reason = "closed"  # resolved, or closed and awaiting resolution
        elif kind == "probability":
            prob = (d.get("forecasting") or {}).get("probability")
        else:
            prob = (sim_nodes.get(ref) or {}).get("mean")
        vid = (prefix + re.sub(r"[^a-z0-9_]", "_", ref.lower()))[:64]
        if reason is None and not (isinstance(prob, (int, float)) and 0 <= prob <= 1):
            reason = {"metaculus": "no_community_prediction", "probability": "no_probability",
                      "formula": "no_simulation_mean"}[kind]
        if reason is None and vid in markets:
            reason = "id_collision"
        if reason:
            skipped[reason] += 1
            listed.append({"node_id": node["id"], "ref": ref, "reason": reason})
            continue

        p = clamp(float(prob))
        title = (d.get("title") or meta.get("title") or ref).strip()
        year = year_from_title(title)  # a past year in a title is a baseline, not the deadline
        prov = {"source": "radiant", "project_id": project_id, "node_id": node["id"], "ref": ref,
                "method": "radiant-import-v1", "parents": []}
        market = {
            "id": vid,
            "title": title[:160],
            "description": (f"{title}. Imported from Radiant project {project_id} "
                            f"(node {ref}, {kind}). Value at import ({now}): {float(prob):.1%}."),
            "variableId": vid,
            "status": "active",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "marginals": {"yes": round(p, 6), "no": round(1 - p, 6)},
            "liquidity": 10000.0,
            "volume": 0.0,
            "created_at": now,
            "expires_at": f"{year if year >= int(now[:4]) else 2031}-12-31T23:59:59Z",
            "provenance": prov,
        }
        if kind == "metaculus":
            url = meta["url"]
            market["expires_at"] = post.get("scheduled_close_time") or market["expires_at"]
            prov.update(url=url, forecasters=latest.get("forecaster_count"))
            market["anchor"] = {"source": "metaculus", "ref": str(meta["post_id"]), "url": url,
                                "value": round(p, 6), "fetchedAt": now}
        markets[vid] = market
        vid_of[node["id"]] = vid

    parents = defaultdict(set)
    for e in canvas.get("edges", []):
        direction = (e.get("data") or {}).get("arrow_direction")
        src, dst = vid_of.get(e["source_node_id"]), vid_of.get(e["target_node_id"])
        if src and dst and direction in ("forward", "backward"):
            parent, child = (src, dst) if direction == "forward" else (dst, src)
            parents[child].add(parent)
    for child, ps in parents.items():
        markets[child]["provenance"]["parents"] = sorted(ps)

    return {"version": "seeds-v1", "markets": markets, "conditionalMarginals": {}}, skipped, listed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="Radiant project uuid")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seeds, skipped, listed = build(args.project, *fetch(Radiant(os.environ["RADIANT_API_TOKEN"]), args.project), now)
    Path(args.out).write_text(json.dumps(seeds, indent=1))
    print(json.dumps({"project": args.project, "markets": len(seeds["markets"]),
                      "skipped": dict(skipped), "skipped_binary": listed}, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
