"""CLI opaque-section preservation.

Bug: core.cli.load_or_create once discarded the loaded ``venues`` section
returned by ``load_snapshot`` (bound to ``_venues`` and dropped), so every
mutating CLI command's ``save_snapshot`` call wrote an EMPTY venues section
back out — silently wiping any net-venue (JointVenue) state a prior API/CLI
session had persisted.

These tests drive ``core.cli.main()`` directly (no existing CLI test
module to follow conventions from), with ``sys.argv`` patched and
``FUTARCHY_STATE``/``--state`` pointed at a tmp_path file.
"""

import json
import sys
from decimal import Decimal

from exchange.core.cli import main
from exchange.core.models import Instrument, reset_counters
from exchange.core.persistence import load_snapshot, save_snapshot
from exchange.core.market_engine import MarketEngine
from exchange.core.risk_engine import RiskEngine


def _seed_state(path: str, venues_section: dict, instruments: dict) -> None:
    """Write a snapshot with non-empty opaque sections."""
    reset_counters()
    risk = RiskEngine()
    me = MarketEngine(risk)
    save_snapshot(
        risk, me, path, venues=venues_section, instruments=instruments,
    )


def test_mutating_cli_preserves_venues_and_instruments(tmp_path, monkeypatch, capsys):
    state_path = str(tmp_path / "state.json")
    venues_section = {
        "joint": {
            "orders": [{"orderId": "vb_1", "accountId": 1, "status": "open"}],
            "orderSeq": 1,
            "resolutions": {"gcx_a": "yes"},
            "voided": [],
            "marketStatus": {"g1": {"status": "resolved", "resolvedOutcome": "yes"}},
            "treasuryAccountId": 1,
            "liquidity": "50",
            "maxWidth": 8,
            "seedsSource": "<inline>",
        }
    }
    instruments = {
        "ship-date": Instrument(
            "ship-date", "Will it ship?",
            [{"venue": "net", "marketId": "g1"}],
        )
    }
    _seed_state(state_path, venues_section, instruments)

    # Sanity: the section really did land in the file as written.
    with open(state_path) as f:
        pre_state = json.load(f)
    assert pre_state["venues"] == venues_section
    assert "ship-date" in pre_state["instruments"]

    # Run a mutating CLI command (create-account) through the real entry
    # point — this is the load -> execute -> save path that used to wipe
    # the venues section on every save.
    monkeypatch.setattr(
        sys, "argv", ["futarchy-cli", "--state", state_path, "create-account"]
    )
    main()

    out = capsys.readouterr().out
    result = json.loads(out.strip().splitlines()[-1])
    assert result["ok"] is True

    with open(state_path) as f:
        post_state = json.load(f)

    # Byte-identical (same JSON-serializable structure) venues section —
    # nothing about the mutating command touched or erased it.
    assert post_state["venues"] == venues_section
    assert post_state["instruments"] == pre_state["instruments"]

    # And it round-trips through load_snapshot the same way.
    _risk, _me, _auth, _repos, loaded_venues, loaded_instruments = load_snapshot(
        state_path
    )
    assert loaded_venues == venues_section
    assert loaded_instruments["ship-date"].title == "Will it ship?"
