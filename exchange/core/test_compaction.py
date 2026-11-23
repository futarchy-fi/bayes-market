"""I4: transaction-log compaction bounds snapshot growth while preserving
total_minted() and per-account activity running balances.
"""
from decimal import Decimal

from exchange.core.market_engine import MarketEngine
from exchange.core.models import ZERO, reset_counters
from exchange.core.persistence import compact_empty_batch_rounds, load_snapshot, save_snapshot
from exchange.core.risk_engine import RiskEngine


def _build_log(engine):
    """A varied log across two accounts: mints, a lock, and transfers."""
    a = engine.create_account()
    b = engine.create_account()
    engine.mint(a.id, Decimal("1000"))
    engine.mint(b.id, Decimal("500"))
    engine.lock(a.id, market_id=1, amount=Decimal("300"))
    engine.transfer_available(a.id, b.id, Decimal("100"))
    engine.transfer_available(b.id, a.id, Decimal("50"))
    engine.mint(a.id, Decimal("200"))
    return a.id, b.id


def _running(txs, account_id):
    """Reconstruct running balances the way _build_account_activity does:
    accumulate deltas from zero, in order. Returns {tx_id: (avail, frozen)}."""
    avail = ZERO
    frozen = ZERO
    out = {}
    for tx in txs:
        if tx.account_id != account_id:
            continue
        avail += tx.available_delta
        frozen += tx.frozen_delta
        out[tx.id] = (avail, frozen)
    return out


def test_compact_noop_when_under_ceiling():
    reset_counters()
    e = RiskEngine()
    _build_log(e)
    n = len(e.transactions)
    assert e.compact_transactions(n) == 0
    assert e.compact_transactions(n + 5) == 0
    assert len(e.transactions) == n


def test_compact_bounds_the_log():
    reset_counters()
    e = RiskEngine()
    _build_log(e)
    n = len(e.transactions)
    dropped = e.compact_transactions(2)
    assert dropped == n - 2
    # <= 2 retained + at most one checkpoint per account touched by drops.
    assert len(e.transactions) <= 2 + 2


def test_compact_preserves_total_minted():
    reset_counters()
    e = RiskEngine()
    _build_log(e)
    before = e.total_minted()
    assert before == Decimal("1700")  # 1000 + 500 + 200
    e.compact_transactions(2)
    assert e.total_minted() == before
    # Idempotent-ish: compacting again holds the figure.
    e.compact_transactions(1)
    assert e.total_minted() == before


def test_compact_preserves_running_balances_and_final_equals_account():
    reset_counters()
    e = RiskEngine()
    a, b = _build_log(e)
    full_a = _running(e.transactions, a)
    full_b = _running(e.transactions, b)

    e.compact_transactions(3)  # force checkpoints

    # Every id still present keeps its exact running balance (the checkpoint
    # reuses the last dropped id, whose cumulative balance equals the sum of
    # all dropped deltas — so it lines up too).
    for tx_id, bal in _running(e.transactions, a).items():
        assert bal == full_a[tx_id]
    for tx_id, bal in _running(e.transactions, b).items():
        assert bal == full_b[tx_id]

    # Final reconstructed balance equals the account's stored balance.
    acc_a = e.get_account(a)
    last_a = list(_running(e.transactions, a).values())[-1]
    assert last_a == (acc_a.available_balance, acc_a.frozen_balance)


def test_checkpoint_ids_stay_below_retained_ids():
    # The activity cursor (tx_id < before_tx_id) needs ids monotonic with
    # recency: a checkpoint must sort older than every retained tx.
    reset_counters()
    e = RiskEngine()
    _build_log(e)
    keep = 2
    retained_ids = {tx.id for tx in e.transactions[-keep:]}
    e.compact_transactions(keep)
    checkpoint_ids = [tx.id for tx in e.transactions if tx.reason == "checkpoint"]
    assert checkpoint_ids
    assert max(checkpoint_ids) < min(retained_ids)


def test_minted_base_survives_snapshot_round_trip(tmp_path):
    reset_counters()
    e = RiskEngine()
    _build_log(e)
    e.compact_transactions(2)
    assert e._minted_base > ZERO  # some mints were compacted out
    minted = e.total_minted()

    me = MarketEngine(e)
    path = str(tmp_path / "state.json")
    save_snapshot(e, me, path, instruments={})
    risk2, _, _, _, _, _ = load_snapshot(path)

    assert risk2._minted_base == e._minted_base
    assert risk2.total_minted() == minted


def test_compact_empty_batch_rounds_strips_zero_participants_and_caps_history():
    empty_rounds = [
        {"round": i, "clearingPrice": "0.5", "participants": 0}
        for i in range(1, 1001)
    ]
    active_rounds = [
        {"round": 1000 + i, "clearingPrice": "0.55", "participants": 2}
        for i in range(1, 601)
    ]
    state = {
        "venues": {
            "batch": {
                "markets": [
                    {"id": 1, "round_history": empty_rounds + active_rounds},
                    {"id": 2, "round_history": [{"round": 1, "clearingPrice": "0.5", "participants": 0}]},
                ]
            }
        }
    }
    removed = compact_empty_batch_rounds(state, max_history=500)
    assert removed == 1000 + 100 + 1
    m1_hist = state["venues"]["batch"]["markets"][0]["round_history"]
    m2_hist = state["venues"]["batch"]["markets"][1]["round_history"]
    assert len(m1_hist) == 500
    assert m1_hist[0]["round"] == 1101
    assert m1_hist[-1]["round"] == 1600
    assert all(entry["participants"] > 0 for entry in m1_hist)
    assert m2_hist == []
    # Idempotent on a second pass.
    assert compact_empty_batch_rounds(state, max_history=500) == 0


def test_batch_engine_caps_round_history_and_strips_empty_on_reload():
    from exchange.venues.batch.engine import BatchEngine, MAX_ROUND_HISTORY

    reset_counters()
    risk = RiskEngine()
    trader = risk.create_account()
    risk.mint(trader.id, Decimal("10000"))
    engine = BatchEngine(risk)
    market = engine.create_market("Retention?", b=Decimal("10"))

    # Empty manual close_round never adds zero-participant records.
    empty_res = engine.close_round(market.id)
    assert empty_res["participants"] == 0
    assert market.round_history == []

    # Legacy bloated snapshot with empty rounds + >500 real rounds compacts on load.
    snap = engine.snapshot()
    snap["markets"][0]["round_history"] = [
        {"round": i, "clearingPrice": "0.5", "participants": 0}
        for i in range(1, 50)
    ] + [
        {"round": 100 + i, "clearingPrice": "0.6", "participants": 1}
        for i in range(1, MAX_ROUND_HISTORY + 25)
    ]
    restored = BatchEngine.from_snapshot(snap, risk)
    hist = restored.markets[market.id].round_history
    assert len(hist) == MAX_ROUND_HISTORY
    assert all(r["participants"] > 0 for r in hist)
    assert hist[-1]["round"] == 100 + MAX_ROUND_HISTORY + 24
