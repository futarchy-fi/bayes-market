"""Durable-state persistence: the exchange survives restarts, and says so honestly."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "backend" / "server.py"
spec = importlib.util.spec_from_file_location("bayes_market_durability_server", MODULE_PATH)
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def seed_live_state() -> None:
    """Put settled state, an open order, and a hash-chained event on the books."""
    server.reset_state()
    server.ORDERS["ord_test_000001"] = {"marketId": "mkt_a", "status": "open", "qty": 7}
    server.EVENTS["evt_test_000001"] = {
        "eventId": "evt_test_000001",
        "marketId": "mkt_a",
        "seq": 1,
        "eventType": "CommandAccepted",
        "prevEventHash": server.GENESIS_EVENT_HASH,
        "eventHash": "sha256:deadbeef",
    }
    server.MARKET_EVENT_SEQUENCES["mkt_a"] = 1
    server.LAST_EVENT_HASHES["mkt_a"] = "sha256:deadbeef"
    server.ACCOUNT_RISK["acct_a"] = {"exposure": 42.5}
    server.IDEMPOTENCY_KEYS[("mkt_a", "acct_a", "key-1")] = "cmd_test_000001"
    server.EVENT_COUNTER = 1
    server.ORDER_COUNTER = 1


class DurableStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(server.reset_state)

    def test_state_survives_a_restart_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(pathlib.Path(directory) / "state.json")
            with patch.object(server, "STATE_PATH", path):
                seed_live_state()
                before = server.state_digest()
                server.persist_state()

                # the restart: memory is gone, only the file survives
                server.reset_state()
                self.assertNotIn("ord_test_000001", server.ORDERS)
                self.assertNotEqual(server.state_digest(), before)

                self.assertTrue(server.restore_state())
                self.assertEqual(server.state_digest(), before)

            # every durable table came back, including the tuple-keyed one
            self.assertEqual(server.ORDERS["ord_test_000001"]["qty"], 7)
            self.assertEqual(server.LAST_EVENT_HASHES["mkt_a"], "sha256:deadbeef")
            self.assertEqual(server.ACCOUNT_RISK["acct_a"]["exposure"], 42.5)
            self.assertEqual(
                server.IDEMPOTENCY_KEYS[("mkt_a", "acct_a", "key-1")], "cmd_test_000001"
            )
            self.assertEqual(server.EVENT_COUNTER, 1)

    def test_event_journal_hash_chain_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(pathlib.Path(directory) / "state.json")
            with patch.object(server, "STATE_PATH", path):
                seed_live_state()
                server.persist_state()
                server.reset_state()
                server.restore_state()
                event = server.EVENTS["evt_test_000001"]
                self.assertEqual(event["prevEventHash"], server.GENESIS_EVENT_HASH)
                self.assertEqual(server.MARKET_EVENT_SEQUENCES["mkt_a"], 1)

    def test_health_reports_the_digest_immediately_after_restore(self):
        """Caught by the restart drill: health read blank until the next write."""
        with tempfile.TemporaryDirectory() as directory:
            path = str(pathlib.Path(directory) / "state.json")
            with patch.object(server, "STATE_PATH", path):
                seed_live_state()
                server.persist_state()
                expected = server.state_digest()

                server.reset_state()
                server._STATE_PERSIST.update({"error": "", "digest": "", "at": ""})
                server.restore_state()

                component = server.db_health_component()
                self.assertEqual(component["status"], "ok")
                self.assertEqual(component["digest"], expected)
                self.assertTrue(component["lastPersistedAt"])

    def test_unreadable_snapshot_refuses_to_start(self):
        """Fail-closed: never come up empty on top of a snapshot we cannot read."""
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "state.json"
            path.write_text("{ this is not json")
            with patch.object(server, "STATE_PATH", str(path)):
                with self.assertRaises(SystemExit) as caught:
                    server.restore_state()
                self.assertIn("refusing to start", str(caught.exception))

    def test_unknown_schema_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "state.json"
            path.write_text(json.dumps({"schemaVersion": "bayes-state/v99", "state": {}}))
            with patch.object(server, "STATE_PATH", str(path)):
                with self.assertRaises(SystemExit):
                    server.restore_state()

    def test_missing_snapshot_starts_from_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(pathlib.Path(directory) / "absent.json")
            with patch.object(server, "STATE_PATH", path):
                self.assertFalse(server.restore_state())

    def test_persistence_off_reports_in_memory(self):
        with patch.object(server, "STATE_PATH", ""):
            self.assertEqual(server.db_health_component()["kind"], "in_memory")

    def test_write_failure_reports_unhealthy_never_silent(self):
        """A write we cannot land must not be reported as a healthy exchange."""
        with patch.object(server, "STATE_PATH", "/nonexistent-dir/state.json"):
            server.persist_state()
            component = server.db_health_component()
            self.assertEqual(component["status"], "unhealthy")
            self.assertIn("error", component)
        server._STATE_PERSIST["error"] = ""


if __name__ == "__main__":
    unittest.main()
