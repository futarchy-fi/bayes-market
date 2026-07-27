#!/usr/bin/env python3
"""Sensor resolver (hub-4pcv). The counter, exercised: silence must settle
FALSE *with its cause named*, and nothing else may settle at all — a stale,
absent, undated, or future-dated feed never reads as a verdict (hub-eif7),
and pre-deadline silence never resolves."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal

import pytest

from exchange.core.models import reset_counters
from exchange.core.risk_engine import RiskEngine
from exchange.core.market_engine import MarketEngine
from exchange.core import sensor_resolver as sr

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def iso(when):
    return when.isoformat().replace("+00:00", "Z")


@pytest.fixture
def setup(tmp_path):
    reset_counters()
    engine = MarketEngine(RiskEngine())
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    registry = [{
        "feed": "q2-heart",
        "question": "Will the heartbeat read live by the deadline?",
        "rule": {"field": "status", "op": "==", "value": "live"},
        "max_feed_age_s": 3600,
        "deadline": iso(NOW + dt.timedelta(hours=1)),
    }]
    created = sr.sync_markets(engine, registry, now=NOW)
    assert len(created) == 1
    return engine, str(feeds), created[0]


def write_feed(feeds, name, doc):
    with open(os.path.join(feeds, name + ".json"), "w", encoding="utf-8") as fh:
        fh.write(doc if isinstance(doc, str) else json.dumps(doc))


def fresh_feed(**fields):
    return {"generated_at": iso(NOW - dt.timedelta(seconds=30)), **fields}


def test_fresh_true_settles_yes(setup):
    engine, feeds, mid = setup
    write_feed(feeds, "q2-heart", fresh_feed(status="live"))
    decisions = sr.due_resolutions(engine.markets.values(), feeds, now=NOW)
    assert decisions == [{"market_id": mid,
                          "question": "Will the heartbeat read live by the deadline?",
                          "outcome": "yes", "cause": "rule-True"}]
    sr.apply_resolutions(engine, decisions, now=NOW)
    assert engine.markets[mid].status == "resolved"
    assert engine.markets[mid].resolution == "yes"
    assert engine.markets[mid].metadata["sensor_resolution"]["cause"] == "rule-True"


def test_fresh_false_settles_no_with_rule_cause(setup):
    engine, feeds, mid = setup
    write_feed(feeds, "q2-heart", fresh_feed(status="degraded"))
    decisions = sr.due_resolutions(engine.markets.values(), feeds, now=NOW)
    assert [d["outcome"] for d in decisions] == ["no"]
    assert decisions[0]["cause"] == "rule-False"


def test_predeadline_silence_resolves_nothing(setup, tmp_path):
    engine, feeds, mid = setup
    # absent feed
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    # malformed feed
    write_feed(feeds, "q2-heart", "{not json")
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    # undated feed (file is fresh on disk — mtime must NOT substitute)
    write_feed(feeds, "q2-heart", {"status": "live"})
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    # stale feed
    write_feed(feeds, "q2-heart",
               {"generated_at": iso(NOW - dt.timedelta(hours=2)), "status": "live"})
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    # future-dated feed (hub-eif7: never fresh)
    write_feed(feeds, "q2-heart",
               {"generated_at": iso(NOW + dt.timedelta(hours=2)), "status": "live"})
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    # fresh but the rule's field is absent
    write_feed(feeds, "q2-heart", fresh_feed(other="live"))
    assert sr.due_resolutions(engine.markets.values(), feeds, now=NOW) == []
    assert engine.markets[mid].status == "open"


def test_past_deadline_silence_settles_false_with_named_cause(setup):
    engine, feeds, mid = setup
    later = NOW + dt.timedelta(hours=2)  # past the 1h deadline
    write_feed(feeds, "q2-heart",
               {"generated_at": iso(NOW - dt.timedelta(hours=2)), "status": "live"})
    decisions = sr.due_resolutions(engine.markets.values(), feeds, now=later)
    assert [d["outcome"] for d in decisions] == ["no"]
    assert decisions[0]["cause"] == "sensor-silent:unavailable:feed-stale"
    sr.apply_resolutions(engine, decisions, now=later)
    assert engine.markets[mid].metadata["sensor_resolution"]["cause"] == \
        "sensor-silent:unavailable:feed-stale"


def test_past_deadline_fresh_false_is_rule_false_not_silence(setup):
    engine, feeds, mid = setup
    later = NOW + dt.timedelta(hours=2)
    write_feed(feeds, "q2-heart",
               {"generated_at": iso(later - dt.timedelta(seconds=30)),
                "status": "degraded"})
    decisions = sr.due_resolutions(engine.markets.values(), feeds, now=later)
    assert decisions[0]["cause"] == "rule-False"


def test_no_deadline_never_force_resolves(tmp_path):
    reset_counters()
    engine = MarketEngine(RiskEngine())
    registry = [{
        "feed": "q2-heart", "question": "standing invariant holds",
        "rule": {"field": "status", "op": "==", "value": "live"},
        "max_feed_age_s": 3600,  # no deadline
    }]
    created = sr.sync_markets(engine, registry, now=NOW)
    decisions = sr.due_resolutions(engine.markets.values(), str(tmp_path), now=NOW)
    assert decisions == []
    assert engine.markets[created[0]].status == "open"


def test_sync_is_idempotent(setup):
    engine, feeds, mid = setup
    registry = [{
        "feed": "q2-heart", "question": "changed text does not duplicate",
        "rule": {"field": "status", "op": "==", "value": "live"},
    }]
    assert sr.sync_markets(engine, registry, now=NOW) == []
    assert len(engine.markets) == 1
    # a NEW feed id creates exactly one more
    registry.append({"feed": "q2-trace", "question": "second feed",
                     "rule": {"field": "ok", "op": "==", "value": True}})
    created = sr.sync_markets(engine, registry, now=NOW)
    assert len(created) == 1 and len(engine.markets) == 2


def test_untraded_sensor_market_has_zero_trades(setup):
    """Untraded renders as untraded: num_trades (serializer) reads len(trades)."""
    engine, feeds, mid = setup
    market = engine.markets[mid]
    assert len(market.trades) == 0


def test_cli_dry_run_writes_nothing_and_apply_persists(tmp_path):
    reset_counters()
    state = tmp_path / "state.json"
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps([{
        "feed": "q2-heart", "question": "will it hold",
        "rule": {"field": "status", "op": "==", "value": "live"},
        "max_feed_age_s": 3600,
    }]))
    # a state file with one open market, produced through the public save path
    from exchange.core import persistence
    engine = MarketEngine(RiskEngine())
    engine.create_market(question="will it hold", category="sensor",
                         category_id="q2-heart",
                         metadata={"resolver": {
                             "type": "sensor", "feed": "q2-heart",
                             "rule": {"field": "status", "op": "==", "value": "live"},
                             "max_feed_age_s": 3600}},
                         b=Decimal("100"))
    persistence.save_snapshot(engine.risk, engine, str(state),
                              venues={"book": {"untouched": True}})
    write_feed(str(feeds), "q2-heart",
               {"generated_at": iso(dt.datetime.now(UTC) - dt.timedelta(seconds=5)),
                "status": "live"})
    base = [sys.executable, "-m", "exchange.core.sensor_resolver",
            "--state", str(state), "--feeds-dir", str(feeds)]
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    dry = subprocess.run(base + ["--registry", str(registry)],
                         capture_output=True, text=True, env=env)
    assert dry.returncode == 0, dry.stderr
    report = json.loads(dry.stdout)
    assert report["dry_run"] is True and len(report["decisions"]) == 1
    _r, engine2, *_ = persistence.load_snapshot(str(state))
    assert all(m.status == "open" for m in engine2.markets.values())
    applied = subprocess.run(base + ["--apply"], capture_output=True, text=True, env=env)
    assert applied.returncode == 0, applied.stderr
    _r, engine3, _auth, _repos, venues, _instr = persistence.load_snapshot(str(state))
    resolved = [m for m in engine3.markets.values() if m.status == "resolved"]
    assert len(resolved) == 1 and resolved[0].resolution == "yes"
    assert venues == {"book": {"untouched": True}}  # sections not wiped


def test_cli_missing_state_exits_2(tmp_path):
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    run = subprocess.run(
        [sys.executable, "-m", "exchange.core.sensor_resolver",
         "--state", str(tmp_path / "nope.json"), "--feeds-dir", str(tmp_path)],
        capture_output=True, text=True, env=env)
    assert run.returncode == 2
    assert "unavailable:state" in run.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
