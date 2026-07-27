#!/usr/bin/env python3
"""Sensor resolver class (hub-4pcv): markets resolved by registered q2 sensor
feeds, per Clause III — silence settles FALSE.

A sensor market carries resolver metadata:

    "resolver": {
        "type": "sensor",
        "feed": "<feed-id>",                    # <feeds_dir>/<feed-id>.json
        "rule": {"field": "status", "op": "==", "value": "live"},
        "max_feed_age_s": 3600
    }

Resolution discipline (fail-closed, the whole point of the class):

- A FRESH feed whose rule field is present decides: op true -> 'yes',
  op false -> 'no'. An explicit reading is the only way to 'yes'.
- An absent, unreadable, malformed, undated, stale, or future-dated feed is
  NOT a 'no' — it is sensor-silence, and pre-deadline it resolves NOTHING.
  A future-dated feed is never fresh (hub-eif7), and file mtime is never
  substituted for a missing generated_at.
- Past deadline, silence settles FALSE ('no') and the CAUSE is recorded in
  metadata['sensor_resolution'] — 'sensor-silent:<cause>', so a dead feed is
  visible in the settlement, not laundered into a clean 'no'.
- A sensor market with no deadline never force-resolves: it stays open and
  evaluate() reports why.

Auto-markets (sync_markets): one open sensor market per registry entry,
created through the normal engine path (funded AMM, minted subsidy),
idempotent on category_id — re-running never duplicates a market.
"""
import argparse
import datetime as dt
import json
import os
import sys
from decimal import Decimal

UTC = dt.timezone.utc
OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_feed(feeds_dir, feed_id):
    """(feed, cause). cause is None only when the bytes actually parsed."""
    path = os.path.join(feeds_dir, feed_id + ".json")
    try:
        with open(path, encoding="utf-8") as source:
            feed = json.load(source)
    except FileNotFoundError:
        return None, "unavailable:feed-absent ({})".format(feed_id)
    except (OSError, json.JSONDecodeError) as exc:
        return None, "unavailable:feed-unreadable ({}: {})".format(
            feed_id, exc.__class__.__name__)
    if not isinstance(feed, dict):
        return None, "unavailable:feed-shape ({})".format(feed_id)
    return feed, None


def silence_cause(feed, rule, max_age_s, now):
    """None if the feed can settle; otherwise the named cause of silence."""
    stamp = _parse_ts(feed.get("generated_at"))
    if stamp is None:
        return "unavailable:feed-undated"
    age = (now - stamp).total_seconds()
    if age < 0:
        return "unavailable:feed-future-dated"
    if max_age_s is not None and age > max_age_s:
        return "unavailable:feed-stale"
    field = rule.get("field")
    if field not in feed:
        return "unavailable:rule-field ({})".format(field)
    return None


def eval_rule(feed, rule):
    """True/False from a fresh, fielded feed. Caller checked silence first."""
    op = OPS.get(rule.get("op"))
    if op is None:
        return None
    try:
        return bool(op(feed[rule["field"]], rule.get("value")))
    except TypeError:
        return None  # e.g. '>= on a string vs int: unevaluable, never a guess


def due_resolutions(markets, feeds_dir, now=None):
    """The decisions due right now. Pure: reads feeds, touches nothing."""
    now = now or dt.datetime.now(UTC)
    decisions = []
    for market in sorted(markets, key=lambda m: m.id):
        resolver = (market.metadata or {}).get("resolver") or {}
        if market.status != "open" or resolver.get("type") != "sensor":
            continue
        rule = resolver.get("rule") or {}
        feed, cause = load_feed(feeds_dir, resolver.get("feed", ""))
        if feed is not None:
            cause = silence_cause(feed, rule, resolver.get("max_feed_age_s"), now)
        outcome = None
        if cause is None:
            verdict = eval_rule(feed, rule)
            if verdict is None:
                cause = "unavailable:rule-unevaluable"
            else:
                outcome = "yes" if verdict else "no"
                cause = "rule-{}".format(verdict)
        if outcome is None:
            deadline = _parse_ts(market.deadline)
            if deadline is not None and now >= deadline:
                outcome = "no"               # Clause III: silence settles FALSE
                cause = "sensor-silent:" + cause
        if outcome is not None:
            decisions.append({
                "market_id": market.id,
                "question": market.question,
                "outcome": outcome,
                "cause": cause,
            })
    return decisions


def apply_resolutions(engine, decisions, now=None):
    """Apply decisions through the engine and stamp the cause on the market."""
    now = now or dt.datetime.now(UTC)
    applied = []
    for decision in decisions:
        engine.resolve(decision["market_id"], decision["outcome"])
        market = engine.markets[decision["market_id"]]
        market.metadata["sensor_resolution"] = {
            "outcome": decision["outcome"],
            "cause": decision["cause"],
            "resolved_at": now.isoformat().replace("+00:00", "Z"),
        }
        applied.append(decision)
    return applied


def sync_markets(engine, registry, now=None):
    """One open sensor market per registry entry; idempotent on category_id.

    registry: list of {"feed", "question", "rule", "max_feed_age_s",
    "deadline" (optional), "b" (optional, default "100")}. An entry whose open
    market already exists is skipped — re-running sync is a no-op, never a
    duplicate."""
    now = now or dt.datetime.now(UTC)
    created = []
    existing = {
        m.category_id
        for m in engine.markets.values()
        if m.category == "sensor" and m.status == "open"
    }
    for entry in registry:
        feed_id = entry["feed"]
        if feed_id in existing:
            continue
        metadata = {
            "resolver": {
                "type": "sensor",
                "feed": feed_id,
                "rule": entry["rule"],
                "max_feed_age_s": entry.get("max_feed_age_s"),
            },
            "sensor_synced_at": now.isoformat().replace("+00:00", "Z"),
        }
        market, _amm = engine.create_market(
            question=entry["question"],
            category="sensor",
            category_id=feed_id,
            metadata=metadata,
            b=Decimal(str(entry.get("b", "100"))),
            deadline=entry.get("deadline"),
        )
        created.append(market.id)
    return created


def load_registry(path):
    try:
        with open(path, encoding="utf-8") as source:
            registry = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        print("unavailable:registry ({}: {})".format(path, exc.__class__.__name__),
              file=sys.stderr)
        sys.exit(2)
    if not isinstance(registry, list):
        print("unavailable:registry-shape ({}: expected a list)".format(path),
              file=sys.stderr)
        sys.exit(2)
    return registry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=os.environ.get(
        "FUTARCHY_STATE", "./futarchy_state.json"))
    parser.add_argument("--feeds-dir", required=True)
    parser.add_argument("--registry", help="auto-market registry JSON (optional)")
    parser.add_argument("--apply", action="store_true",
                        help="write decisions and creations to the state file; "
                             "default is a dry run that only prints them")
    args = parser.parse_args(argv)

    from exchange.core import persistence

    if os.path.exists(args.state):
        risk, engine, auth_store, tracked_repos, venues, instruments = (
            persistence.load_snapshot(args.state))
    else:
        print("unavailable:state ({} does not exist)".format(args.state),
              file=sys.stderr)
        sys.exit(2)

    created = []
    if args.registry:
        created = sync_markets(engine, load_registry(args.registry))
    decisions = due_resolutions(engine.markets.values(), args.feeds_dir)
    report = {"dry_run": not args.apply, "created": created, "decisions": decisions}
    print(json.dumps(report, indent=2))

    if args.apply and (created or decisions):
        applied = apply_resolutions(engine, decisions)
        # every loaded section passed back unchanged except the markets the
        # decisions touched — a sensor run must never wipe auth or venues
        persistence.save_snapshot(risk, engine, args.state,
                                  auth_store=auth_store,
                                  tracked_repos=tracked_repos,
                                  venues=venues,
                                  instruments=instruments)
        print("-- applied {} resolution(s), created {} market(s)".format(
            len(applied), len(created)), file=sys.stderr)
    elif created or decisions:
        print("-- DRY RUN: nothing written (pass --apply to settle)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
