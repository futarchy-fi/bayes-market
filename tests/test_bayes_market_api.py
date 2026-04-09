from __future__ import annotations

import importlib.util
import itertools
import json
import math
import pathlib
import random
import threading
import time
import unittest
from copy import deepcopy
from email.message import Message
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.parse import urlencode

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "backend" / "server.py"
spec = importlib.util.spec_from_file_location("bayes_market_server", MODULE_PATH)
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


PROPERTY_PROBABILITIES = (0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95)
REFERENCE_NET_MARKET_IDS = tuple(server.INITIAL_MARKETS)
VARIABLE_ID_TO_MARKET_ID = {
    market["variableId"]: market_id for market_id, market in server.INITIAL_MARKETS.items()
}


def build_unconditional_probability_edit_body(
    account_id: str,
    market_id: str,
    outcome_id: str,
    probability: float,
    *,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "accountId": account_id,
        "variableId": server.MARKETS[market_id]["variableId"],
        "target": {"kind": "marginal", "outcomeId": outcome_id, "probability": probability},
        "context": [],
    }
    if idempotency_key is not None:
        body["idempotencyKey"] = idempotency_key
    return body


def build_event_trade_body(
    account_id: str,
    market_id: str,
    outcome_id: str,
    *,
    size: float = 12.5,
    side: str = "buy",
    idempotency_key: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "accountId": account_id,
        "formula": [[{"variableId": market_id, "outcomeId": outcome_id, "negated": False}]],
        "size": size,
        "side": side,
    }
    if idempotency_key is not None:
        body["idempotencyKey"] = idempotency_key
    return body


def build_market_resolution_body(
    account_id: str,
    outcome_id: str | None = None,
    *,
    final_probabilities: dict[str, float] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"accountId": account_id}
    if outcome_id is not None:
        body["outcomeId"] = outcome_id
    if final_probabilities is not None:
        body["finalProbabilities"] = deepcopy(final_probabilities)
    if idempotency_key is not None:
        body["idempotencyKey"] = idempotency_key
    return body


def expected_market_resolution_payload(market_id: str, outcome_id: str) -> dict[str, object]:
    return {
        "kind": "ResolveMarket",
        "outcomeId": outcome_id,
        "finalProbabilities": server.build_market_resolution_marginals(server.MARKETS[market_id], outcome_id),
    }


def build_create_market_body(
    *,
    title: str = "Test Market",
    description: str = "A test market",
    outcomes: list[dict[str, str]] | None = None,
    expires_at: str = "2026-12-31T23:59:59Z",
    liquidity: float = 10000.0,
) -> dict[str, object]:
    return {
        "title": title,
        "description": description,
        "outcomes": deepcopy(
            outcomes if outcomes is not None else [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}]
        ),
        "expires_at": expires_at,
        "liquidity": liquidity,
    }


def snapshot_domain_state() -> dict[str, object]:
    return {
        "markets": deepcopy(server.MARKETS),
        "conditional_marginals": deepcopy(server.CONDITIONAL_MARGINALS),
        "orders": deepcopy(server.ORDERS),
        "commands": deepcopy(server.COMMANDS),
        "events": deepcopy(server.EVENTS),
        "terminal_outcomes": deepcopy(server.TERMINAL_OUTCOMES),
        "idempotency_keys": deepcopy(server.IDEMPOTENCY_KEYS),
        "account_risk": deepcopy(server.ACCOUNT_RISK),
        "account_exposure": deepcopy(server.ACCOUNT_EXPOSURE),
    }


def assert_domain_state_unchanged(test_case: unittest.TestCase, snapshot: dict[str, object]) -> None:
    test_case.assertEqual(server.MARKETS, snapshot["markets"])
    test_case.assertEqual(server.CONDITIONAL_MARGINALS, snapshot["conditional_marginals"])
    test_case.assertEqual(server.ORDERS, snapshot["orders"])
    test_case.assertEqual(server.COMMANDS, snapshot["commands"])
    test_case.assertEqual(server.EVENTS, snapshot["events"])
    test_case.assertEqual(server.TERMINAL_OUTCOMES, snapshot["terminal_outcomes"])
    test_case.assertEqual(server.IDEMPOTENCY_KEYS, snapshot["idempotency_keys"])
    test_case.assertEqual(server.ACCOUNT_RISK, snapshot["account_risk"])
    test_case.assertEqual(server.ACCOUNT_EXPOSURE, snapshot["account_exposure"])


def pick_probability_distinct_from_current(market_id: str, outcome_id: str, rng: random.Random) -> float:
    current_probability = float(server.MARKETS[market_id]["marginals"][outcome_id])
    return rng.choice([candidate for candidate in PROPERTY_PROBABILITIES if candidate != current_probability])


def pick_probability_distinct_from_marginals(
    marginals: dict[str, float],
    outcome_id: str,
    rng: random.Random,
) -> float:
    current_probability = float(marginals[outcome_id])
    return rng.choice([candidate for candidate in PROPERTY_PROBABILITIES if candidate != current_probability])


def build_reference_joint_distribution(
    market_ids: tuple[str, ...] = REFERENCE_NET_MARKET_IDS,
) -> dict[tuple[str, ...], float]:
    outcome_grid = [tuple(outcome["id"] for outcome in server.MARKETS[market_id]["outcomes"]) for market_id in market_ids]
    joint: dict[tuple[str, ...], float] = {}

    for state in itertools.product(*outcome_grid):
        probability = 1.0
        for market_id, outcome_id in zip(market_ids, state):
            probability *= float(server.MARKETS[market_id]["marginals"][outcome_id])
        joint[state] = probability

    return joint


def context_assignments_by_market_id(context: list[dict[str, str]]) -> dict[str, str]:
    return {VARIABLE_ID_TO_MARKET_ID[assignment["variableId"]]: assignment["outcomeId"] for assignment in context}


def state_matches_context(
    market_ids: tuple[str, ...],
    state: tuple[str, ...],
    context_assignments: dict[str, str],
) -> bool:
    return all(state[market_ids.index(market_id)] == outcome_id for market_id, outcome_id in context_assignments.items())


def brute_force_conditional_marginals(
    joint: dict[tuple[str, ...], float],
    target_market_id: str,
    context: list[dict[str, str]],
    market_ids: tuple[str, ...] = REFERENCE_NET_MARKET_IDS,
) -> dict[str, float]:
    context_assignments = context_assignments_by_market_id(context)
    target_index = market_ids.index(target_market_id)
    totals = {
        outcome["id"]: 0.0
        for outcome in server.MARKETS[target_market_id]["outcomes"]
    }
    context_mass = 0.0

    for state, probability in joint.items():
        if not state_matches_context(market_ids, state, context_assignments):
            continue
        context_mass += probability
        totals[state[target_index]] += probability

    return {outcome_id: probability / context_mass for outcome_id, probability in totals.items()}


def brute_force_apply_probability_edit(
    joint: dict[tuple[str, ...], float],
    target_market_id: str,
    outcome_id: str,
    probability: float,
    context: list[dict[str, str]],
    market_ids: tuple[str, ...] = REFERENCE_NET_MARKET_IDS,
) -> dict[tuple[str, ...], float]:
    context_assignments = context_assignments_by_market_id(context)
    target_index = market_ids.index(target_market_id)
    before_marginals = brute_force_conditional_marginals(joint, target_market_id, context, market_ids=market_ids)
    current_probability = before_marginals[outcome_id]
    target_scale = probability / current_probability
    non_target_scale = (1.0 - probability) / (1.0 - current_probability)
    updated_joint: dict[tuple[str, ...], float] = {}

    for state, state_probability in joint.items():
        if state_matches_context(market_ids, state, context_assignments):
            scale = target_scale if state[target_index] == outcome_id else non_target_scale
            updated_joint[state] = state_probability * scale
        else:
            updated_joint[state] = state_probability

    return updated_joint


def build_random_context(target_market_id: str, rng: random.Random) -> list[dict[str, str]]:
    candidate_market_ids = [market_id for market_id in REFERENCE_NET_MARKET_IDS if market_id != target_market_id]
    rng.shuffle(candidate_market_ids)
    selected_market_ids = candidate_market_ids[: rng.randint(0, len(candidate_market_ids))]
    return [
        {
            "variableId": server.MARKETS[market_id]["variableId"],
            "outcomeId": rng.choice(
                [
                    outcome["id"]
                    for outcome in server.MARKETS[market_id]["outcomes"]
                    if float(server.MARKETS[market_id]["marginals"][outcome["id"]]) > 0.0
                ]
            ),
        }
        for market_id in sorted(selected_market_ids, key=lambda market_id: server.MARKETS[market_id]["variableId"])
    ]


def assert_marginals_close(
    test_case: unittest.TestCase,
    actual: dict[str, float],
    expected: dict[str, float],
    *,
    delta: float = 1e-9,
) -> None:
    test_case.assertEqual(set(actual), set(expected))
    for outcome_id, expected_probability in expected.items():
        test_case.assertAlmostEqual(actual[outcome_id], expected_probability, delta=delta)


def build_market_context_query_string(context: list[dict[str, str]]) -> str:
    return urlencode(
        [("context", f"{assignment['variableId']}={assignment['outcomeId']}") for assignment in context],
        doseq=True,
    )


def expected_seeded_account_state(account_id: str, min_asset: float) -> dict[str, object]:
    return server.build_account_risk_state(
        account_id,
        "2026-04-05T00:00:00Z",
        min_asset=min_asset,
    )


def rounded_score_delta(
    previous: dict[str, float],
    updated: dict[str, float],
    liquidity: float,
) -> dict[str, float]:
    return {
        outcome_id: server.round_risk_value(score)
        for outcome_id, score in server.lmsr.lmsr_score_delta(previous, updated, liquidity).items()
    }


def seed_account_min_asset(account_id: str, min_asset: float) -> dict[str, object]:
    account_state = expected_seeded_account_state(account_id, min_asset)
    server.ACCOUNT_RISK[account_id] = deepcopy(account_state)
    return account_state


def seed_low_headroom_account(
    account_id: str,
    market_id: str = "m1",
    probability: float = 0.8,
) -> tuple[dict[str, float], float]:
    return seed_account_with_preview_multiplier(account_id, 0.5, market_id=market_id, probability=probability)


def seed_exact_headroom_account(
    account_id: str,
    market_id: str = "m1",
    probability: float = 0.8,
) -> tuple[dict[str, float], float]:
    return seed_account_with_preview_multiplier(account_id, 1.0, market_id=market_id, probability=probability)


def seed_account_with_preview_multiplier(
    account_id: str,
    min_asset_multiplier: float,
    market_id: str = "m1",
    probability: float = 0.8,
) -> tuple[dict[str, float], float]:
    normalized_payload = server.normalize_probability_edit_payload(
        market_id,
        build_unconditional_probability_edit_body(account_id, market_id, "yes", probability),
    )
    preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
    seeded_min_asset = server.round_risk_value(preview["impactScore"] * min_asset_multiplier)
    seed_account_min_asset(account_id, seeded_min_asset)
    seeded_preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
    return seeded_preview["assetDelta"], seeded_min_asset


def expected_min_asset_violation_details(
    account_id: str,
    market_id: str,
    preview_or_asset_delta: dict[str, object],
) -> dict[str, object]:
    asset_delta = preview_or_asset_delta["assetDelta"] if "assetDelta" in preview_or_asset_delta else preview_or_asset_delta
    return {
        "accountId": account_id,
        "marketId": market_id,
        "riskLimit": asset_delta["riskLimit"],
        "beforeMinAsset": asset_delta["beforeMinAsset"],
        "impactScore": asset_delta["impactScore"],
        "afterMinAsset": asset_delta["afterMinAsset"],
    }


def assert_min_asset_violation_api_error(
    test_case: unittest.TestCase,
    error: Exception,
    *,
    account_id: str,
    market_id: str,
    preview_or_asset_delta: dict[str, object],
) -> None:
    test_case.assertIsInstance(error, server.ApiError)
    api_error = error
    test_case.assertEqual(api_error.status, 422)
    test_case.assertEqual(api_error.code, "min_asset_violation")
    test_case.assertEqual(api_error.message, "Edit would produce negative state-contingent assets")
    test_case.assertEqual(
        api_error.details,
        expected_min_asset_violation_details(account_id, market_id, preview_or_asset_delta),
    )


class BayesMarketApiUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def test_get_market_write_lock_returns_stable_lock_per_market(self):
        first = server.get_market_write_lock("m1")
        second = server.get_market_write_lock("m1")
        other_market = server.get_market_write_lock("m2")

        self.assertIs(first, second)
        self.assertIsNot(first, other_market)
        self.assertEqual(set(server.MARKET_WRITE_LOCKS), {"m1", "m2"})

    def test_reset_state_clears_market_write_lock_registry(self):
        original = server.get_market_write_lock("m1")

        self.assertIn("m1", server.MARKET_WRITE_LOCKS)

        server.reset_state()

        self.assertEqual(server.MARKET_WRITE_LOCKS, {})
        self.assertIsNot(server.get_market_write_lock("m1"), original)

    def test_reset_state_clears_account_exposure_projection(self):
        server.ACCOUNT_EXPOSURE["acct_test"] = {
            "accountId": "acct_test",
            "positions": {
                "m1|yes": {
                    "marketId": "m1",
                    "outcomeId": "yes",
                    "netSize": 12.5,
                }
            },
        }

        self.assertEqual(server.max_position_size, 100.0)
        self.assertIn("acct_test", server.ACCOUNT_EXPOSURE)

        server.reset_state()

        self.assertEqual(server.ACCOUNT_EXPOSURE, {})

    def test_aggregate_component_status_returns_ok_when_all_components_are_ok(self):
        components = {
            "db": {"status": "ok"},
            "inference": {"status": "ok"},
            "auth": {"status": "ok"},
        }

        self.assertEqual(server.aggregate_component_status(components), "ok")

    def test_aggregate_component_status_returns_degraded_when_any_component_is_degraded(self):
        components = {
            "db": {"status": "ok"},
            "inference": {"status": "degraded"},
            "auth": {"status": "ok"},
        }

        self.assertEqual(server.aggregate_component_status(components), "degraded")

    def test_aggregate_component_status_returns_unhealthy_when_any_component_is_unhealthy(self):
        components = {
            "db": {"status": "degraded"},
            "inference": {"status": "ok"},
            "auth": {"status": "unhealthy"},
        }

        self.assertEqual(server.aggregate_component_status(components), "unhealthy")

    def test_aggregate_component_status_rejects_empty_components(self):
        with self.assertRaisesRegex(ValueError, "components must not be empty"):
            server.aggregate_component_status({})

    def test_aggregate_component_status_rejects_missing_component_status(self):
        with self.assertRaisesRegex(ValueError, "component 'db' is missing status"):
            server.aggregate_component_status({"db": {}})

    def test_aggregate_component_status_rejects_unexpected_component_status(self):
        with self.assertRaisesRegex(ValueError, "component 'db' has unexpected status: 'healthy'"):
            server.aggregate_component_status({"db": {"status": "healthy"}})

    def test_v1_health_components_are_assembled_from_shared_builders(self):
        with (
            patch.object(server, "db_health_component", return_value={"status": "ok", "kind": "in_memory"}) as db_health_component,
            patch.object(
                server,
                "inference_health_component",
                return_value={"status": "degraded", "backend": "approximate", "version": "1.2.3"},
            ) as inference_health_component,
            patch.object(server, "auth_health_component", return_value={"status": "ok", "requires_agent_id": False}) as auth_health_component,
        ):
            components = server.v1_health_components()

        db_health_component.assert_called_once_with()
        inference_health_component.assert_called_once_with()
        auth_health_component.assert_called_once_with()
        self.assertEqual(
            components,
            {
                "db": {"status": "ok", "kind": "in_memory"},
                "inference": {
                    "status": "degraded",
                    "backend": "approximate",
                    "version": "1.2.3",
                },
                "auth": {
                    "status": "ok",
                    "requires_agent_id": False,
                },
            },
        )

    def test_v1_health_payload_extends_a_copy_of_legacy_health_payload(self):
        original_engine_config = server.ENGINE_CONFIG
        original_auth_require_agent_id = server.AUTH_REQUIRE_AGENT_ID
        self.addCleanup(setattr, server, "ENGINE_CONFIG", original_engine_config)
        self.addCleanup(setattr, server, "AUTH_REQUIRE_AGENT_ID", original_auth_require_agent_id)

        server.ENGINE_CONFIG = server.EngineConfig(
            mode="EXACT",
            backend="variable_elimination",
            version="9.9.9",
            precision="float64",
            compile_type="junction_tree",
            inference_sample_limit=100,
        )
        server.AUTH_REQUIRE_AGENT_ID = True

        legacy_payload = {
            "service": "legacy-bayes-market",
            "status": "legacy-status",
            "timestamp": "2026-04-10T00:00:00Z",
        }

        with (
            patch.object(server, "health_payload", return_value=legacy_payload) as health_payload,
            patch.object(
                server,
                "db_health_component",
                return_value={"status": "degraded", "kind": "in_memory"},
            ) as db_health_component,
            patch.object(server, "inference_health_component", wraps=server.inference_health_component) as inference_health_component,
            patch.object(server, "auth_health_component", wraps=server.auth_health_component) as auth_health_component,
            patch.object(server, "uptime_seconds", return_value=12.345) as uptime_seconds,
        ):
            payload = server.v1_health_payload()

        health_payload.assert_called_once_with()
        db_health_component.assert_called_once_with()
        inference_health_component.assert_called_once_with()
        auth_health_component.assert_called_once_with()
        uptime_seconds.assert_called_once_with()
        self.assertEqual(
            legacy_payload,
            {
                "service": "legacy-bayes-market",
                "status": "legacy-status",
                "timestamp": "2026-04-10T00:00:00Z",
            },
        )
        self.assertEqual(
            payload,
            {
                "service": "legacy-bayes-market",
                "status": "degraded",
                "timestamp": "2026-04-10T00:00:00Z",
                "version": "9.9.9",
                "uptime_seconds": 12.345,
                "components": {
                    "db": {"status": "degraded", "kind": "in_memory"},
                    "inference": {
                        "status": "ok",
                        "backend": "variable_elimination",
                        "version": "9.9.9",
                    },
                    "auth": {
                        "status": "ok",
                        "requires_agent_id": True,
                    },
                },
            },
        )

    def test_get_market_events_serializes_cross_market_appends_while_snapshotting_events(self):
        server.emit_terminal_event({"commandId": "cmd_m1_1", "marketId": "m1"}, "CommandAccepted", {"effects": {}})
        server.emit_terminal_event({"commandId": "cmd_m1_2", "marketId": "m1"}, "CommandAccepted", {"effects": {}})

        writer_errors: list[Exception] = []

        def append_other_market_event() -> None:
            try:
                server.emit_terminal_event(
                    {"commandId": "cmd_m2_1", "marketId": "m2"},
                    "CommandAccepted",
                    {"effects": {}},
                )
            except Exception as exc:
                writer_errors.append(exc)

        writer_thread = threading.Thread(target=append_other_market_event, daemon=True)

        class CoordinatedEventValues:
            def __init__(self, mapping: dict[str, dict[str, object]]) -> None:
                self._mapping = mapping
                self._started_writer = False

            def __iter__(self):
                iterator = iter(dict.values(self._mapping))
                for event in iterator:
                    if not self._started_writer:
                        self._started_writer = True
                        writer_thread.start()
                        time.sleep(0.05)
                    yield event

        class CoordinatedEventsDict(dict[str, dict[str, object]]):
            def values(self):
                return CoordinatedEventValues(self)

        original_events = server.EVENTS
        coordinated_events = CoordinatedEventsDict(server.EVENTS)
        server.EVENTS = coordinated_events

        try:
            payload, status = server.get_market_events("m1", {})
            writer_thread.join(timeout=1)
        finally:
            original_events.clear()
            original_events.update(coordinated_events)
            server.EVENTS = original_events

        self.assertEqual(status, 200)
        self.assertEqual([event["seq"] for event in payload["events"]], [1, 2])
        self.assertEqual(payload["chain"]["headSeq"], 2)
        self.assertEqual(payload["chain"]["headHash"], payload["events"][-1]["eventHash"])
        self.assertFalse(writer_errors)
        self.assertFalse(writer_thread.is_alive(), "cross-market append should complete after the read snapshot releases")
        self.assertEqual(len(server.EVENTS), 3)

    def test_root_route_returns_service_index(self):
        payload, status = server.route_request("GET", "/")

        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "bayes-market")
        self.assertEqual(payload["status"], "ok")
        self.assertIn("routes", payload)
        self.assertEqual(
            payload["routes"]["accounts"],
            ["/v1/accounts/{id}/risk", "/v1/accounts/{id}/pnl"],
        )
        self.assertEqual(payload["routes"]["health"], ["/health", "/healthz", "/v1/health"])
        self.assertIn("GET /v1/markets/{id}/analytics", payload["routes"]["markets"])
        self.assertIn("/v1/markets/{id}/meta", payload["routes"]["markets"])
        self.assertIn("/v1/markets/{id}/events", payload["routes"]["markets"])
        self.assertIn("/v1/markets/{id}/engine-stats", payload["routes"]["markets"])
        self.assertIn("POST /v1/markets/{id}/resolve", payload["routes"]["markets"])
        self.assertIn("POST /v1/markets/{id}/orders/event-trade", payload["routes"]["orders"])

    def test_legacy_health_routes_return_legacy_health_payload(self):
        legacy_payload = {
            "service": "bayes-market",
            "status": "ok",
            "timestamp": "2026-04-10T00:00:00Z",
        }

        with (
            patch.object(server, "health_payload", return_value=legacy_payload) as health_payload,
            patch.object(server, "v1_health_payload", return_value={"status": "wrong"}) as v1_health_payload,
        ):
            for path in ("/health", "/healthz"):
                with self.subTest(path=path):
                    payload, status = server.route_request("GET", path)

                    self.assertEqual(status, 200)
                    self.assertEqual(payload, legacy_payload)

        self.assertEqual(health_payload.call_count, 2)
        v1_health_payload.assert_not_called()

    def test_v1_health_route_returns_versioned_health_payload(self):
        versioned_payload = {
            "service": "bayes-market",
            "status": "ok",
            "timestamp": "2026-04-10T00:00:00Z",
            "version": "9.9.9",
            "uptime_seconds": 12.345,
            "components": {
                "db": {"status": "ok"},
                "inference": {"status": "ok"},
                "auth": {"status": "ok"},
            },
        }

        with (
            patch.object(server, "v1_health_payload", return_value=versioned_payload) as v1_health_payload,
            patch.object(server, "health_payload", return_value={"status": "legacy"}) as health_payload,
        ):
            payload, status = server.route_request("GET", "/v1/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload, versioned_payload)
        v1_health_payload.assert_called_once_with()
        health_payload.assert_not_called()

    def test_v1_health_route_is_method_not_allowed_for_non_get(self):
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request(method, "/v1/health", {})

                error = ctx.exception
                self.assertEqual(error.status, 405)
                self.assertEqual(error.code, "method_not_allowed")
                self.assertEqual(error.details["method"], method)
                self.assertEqual(error.details["path"], "/v1/health")

    def test_do_get_routes_public_health_paths_before_static_fallback(self):
        handler = object.__new__(server.BayesHandler)
        handler.headers = Message()
        handler.handle_api = Mock()
        handler._serve_static = Mock(return_value=False)

        with patch.object(server, "PUBLIC_HEALTH_ROUTES", ("/health", "/healthz", "/ready")):
            handler.path = "/ready"
            server.BayesHandler.do_GET(handler)

        handler.handle_api.assert_called_once_with("GET")
        handler._serve_static.assert_not_called()

    def test_market_analytics_returns_multi_outcome_price_series_and_excludes_contextual_edits(self):
        unconditional_body = build_unconditional_probability_edit_body("acct_chart", "m2", "yes", 0.4)
        contextual_body = build_unconditional_probability_edit_body("acct_context", "m2", "delayed", 0.2)
        contextual_body["context"] = [{"variableId": server.MARKETS["m1"]["variableId"], "outcomeId": "yes"}]

        unconditional_payload, unconditional_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            unconditional_body,
        )
        contextual_payload, contextual_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            contextual_body,
        )
        trade_payload, trade_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/event-trade",
            build_event_trade_body("acct_trade", "m2", "yes", size=7.0),
        )
        analytics_payload, analytics_status = server.route_request("GET", "/v1/markets/m2/analytics")

        self.assertEqual(unconditional_status, 201)
        self.assertEqual(contextual_status, 201)
        self.assertEqual(trade_status, 201)
        self.assertEqual(analytics_status, 200)
        self.assertEqual(analytics_payload["marketId"], "m2")
        self.assertEqual(analytics_payload["summary"]["totalTrades"], 3)
        self.assertEqual(analytics_payload["summary"]["uniqueTraders"], 3)
        self.assertEqual(analytics_payload["summary"]["bucketInterval"], "day")
        self.assertEqual(
            analytics_payload["summary"]["totalVolume"],
            server.round_risk_value(
                float(unconditional_payload["order"]["impactScore"])
                + float(contextual_payload["order"]["impactScore"])
                + float(trade_payload["order"]["notional"])
            ),
        )
        self.assertEqual(len(analytics_payload["volumeBuckets"]), 1)
        self.assertEqual(analytics_payload["volumeBuckets"][0]["tradeCount"], 3)
        self.assertEqual(
            analytics_payload["volumeBuckets"][0]["volume"],
            analytics_payload["summary"]["totalVolume"],
        )

        series_by_outcome = {
            series["outcomeId"]: series
            for series in analytics_payload["priceSeries"]
        }
        self.assertEqual(set(series_by_outcome), {"yes", "no", "delayed"})
        self.assertEqual(
            [point["probability"] for point in series_by_outcome["yes"]["points"]],
            [0.25, unconditional_payload["order"]["newMarginals"]["yes"]],
        )
        self.assertEqual(
            [point["probability"] for point in series_by_outcome["no"]["points"]],
            [0.6, unconditional_payload["order"]["newMarginals"]["no"]],
        )
        self.assertEqual(
            [point["probability"] for point in series_by_outcome["delayed"]["points"]],
            [0.15, unconditional_payload["order"]["newMarginals"]["delayed"]],
        )
        emitted_at_points = {
            point["emittedAt"]
            for series in analytics_payload["priceSeries"]
            for point in series["points"]
        }
        self.assertNotIn(contextual_payload["result"]["emittedAt"], emitted_at_points)
        self.assertNotIn(trade_payload["result"]["emittedAt"], emitted_at_points)

    def test_market_analytics_buckets_mixed_activity_by_hour_and_day(self):
        probability_payload, probability_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body("acct_prob", "m1", "yes", 0.8),
        )
        first_trade_payload, first_trade_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body("acct_buy", "m1", "yes", size=5.0, side="buy"),
        )
        second_trade_payload, second_trade_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body("acct_sell", "m1", "yes", size=2.0, side="sell"),
        )

        server.EVENTS[probability_payload["result"]["eventId"]]["emittedAt"] = "2026-04-08T10:15:00Z"
        server.EVENTS[first_trade_payload["result"]["eventId"]]["emittedAt"] = "2026-04-08T10:45:00Z"
        server.EVENTS[second_trade_payload["result"]["eventId"]]["emittedAt"] = "2026-04-09T01:10:00Z"

        hourly_payload, hourly_status = server.route_request("GET", "/v1/markets/m1/analytics?interval=hour")
        daily_payload, daily_status = server.route_request("GET", "/v1/markets/m1/analytics?interval=day")

        self.assertEqual(probability_status, 201)
        self.assertEqual(first_trade_status, 201)
        self.assertEqual(second_trade_status, 201)
        self.assertEqual(hourly_status, 200)
        self.assertEqual(daily_status, 200)
        self.assertEqual(hourly_payload["summary"]["bucketInterval"], "hour")
        self.assertEqual(daily_payload["summary"]["bucketInterval"], "day")
        self.assertEqual(hourly_payload["summary"]["lastUpdated"], "2026-04-09T01:10:00Z")
        self.assertEqual(daily_payload["summary"]["lastUpdated"], "2026-04-09T01:10:00Z")

        expected_first_bucket_volume = server.round_risk_value(
            float(probability_payload["order"]["impactScore"]) + float(first_trade_payload["order"]["notional"])
        )
        expected_second_bucket_volume = server.round_risk_value(float(second_trade_payload["order"]["notional"]))
        self.assertEqual(
            hourly_payload["volumeBuckets"],
            [
                {
                    "bucketStart": "2026-04-08T10:00:00Z",
                    "bucketEnd": "2026-04-08T11:00:00Z",
                    "tradeCount": 2,
                    "volume": expected_first_bucket_volume,
                },
                {
                    "bucketStart": "2026-04-09T01:00:00Z",
                    "bucketEnd": "2026-04-09T02:00:00Z",
                    "tradeCount": 1,
                    "volume": expected_second_bucket_volume,
                },
            ],
        )
        self.assertEqual(
            daily_payload["volumeBuckets"],
            [
                {
                    "bucketStart": "2026-04-08T00:00:00Z",
                    "bucketEnd": "2026-04-09T00:00:00Z",
                    "tradeCount": 2,
                    "volume": expected_first_bucket_volume,
                },
                {
                    "bucketStart": "2026-04-09T00:00:00Z",
                    "bucketEnd": "2026-04-10T00:00:00Z",
                    "tradeCount": 1,
                    "volume": expected_second_bucket_volume,
                },
            ],
        )

    def test_market_analytics_ranks_traders_deterministically_on_ties(self):
        alpha_payload, alpha_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/event-trade",
            build_event_trade_body("acct_alpha", "m2", "yes", size=4.0),
        )
        zeta_payload, zeta_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/event-trade",
            build_event_trade_body("acct_zeta", "m2", "yes", size=4.0),
        )
        beta_payload, beta_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/event-trade",
            build_event_trade_body("acct_beta", "m2", "yes", size=4.0),
        )

        shared_timestamp = "2026-04-08T09:00:00Z"
        server.EVENTS[alpha_payload["result"]["eventId"]]["emittedAt"] = shared_timestamp
        server.EVENTS[zeta_payload["result"]["eventId"]]["emittedAt"] = shared_timestamp
        server.EVENTS[beta_payload["result"]["eventId"]]["emittedAt"] = "2026-04-08T10:00:00Z"

        analytics_payload, analytics_status = server.route_request("GET", "/v1/markets/m2/analytics")

        self.assertEqual(alpha_status, 201)
        self.assertEqual(zeta_status, 201)
        self.assertEqual(beta_status, 201)
        self.assertEqual(analytics_status, 200)
        self.assertEqual(
            [row["accountId"] for row in analytics_payload["topTraders"]],
            ["acct_beta", "acct_alpha", "acct_zeta"],
        )
        self.assertEqual(
            {row["volume"] for row in analytics_payload["topTraders"]},
            {alpha_payload["order"]["notional"]},
        )

    def test_market_analytics_rejects_invalid_interval_query(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/m1/analytics?interval=week")

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_query")
        self.assertEqual(error.details["parameter"], "interval")
        self.assertEqual(error.details["received"], "week")
        self.assertEqual(error.details["allowed"], ["day", "hour"])

    def test_market_analytics_requires_known_market(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/missing/analytics")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "market_not_found")
        self.assertEqual(error.details["market_id"], "missing")

    def test_market_analytics_route_is_method_not_allowed_for_post(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/markets/m1/analytics", {})

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "POST")
        self.assertEqual(error.details["path"], "/v1/markets/m1/analytics")

    def test_account_pnl_replays_resolved_probability_edit_exposure_after_risk_settlement(self):
        account_id = "acct_resolved_pnl"
        edit_payload, edit_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8),
        )
        resolve_payload, resolve_status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_pnl", "yes"),
        )
        pnl_payload, pnl_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")

        order = edit_payload["order"]
        score_by_outcome = server._round_score_by_outcome(
            server.lmsr.lmsr_score_delta(
                order["previousMarginals"],
                order["newMarginals"],
                float(server.MARKETS["m1"]["liquidity"]),
            )
        )
        expected_marked_value = server.round_risk_value(float(score_by_outcome["yes"]))
        expected_realized_pnl = server.round_risk_value(expected_marked_value - float(order["impactScore"]))

        self.assertEqual(edit_status, 201)
        self.assertEqual(resolve_status, 201)
        self.assertEqual(pnl_status, 200)
        self.assertEqual(server.ACCOUNT_RISK[account_id]["markets"], {})
        self.assertEqual(server.ACCOUNT_RISK[account_id]["lmsrState"]["slices"], {})
        self.assertEqual(
            pnl_payload["account"]["pnl"]["positions"],
            [
                {
                    "marketId": "m1",
                    "marketTitle": server.MARKETS["m1"]["title"],
                    "marketStatus": "resolved",
                    "realizedPnl": expected_realized_pnl,
                    "unrealizedPnl": 0.0,
                    "costBasis": order["impactScore"],
                    "markedValue": expected_marked_value,
                }
            ],
        )
        self.assertEqual(
            pnl_payload["account"]["pnl"]["totals"],
            {
                "costBasis": order["impactScore"],
                "markedValue": expected_marked_value,
                "realizedPnl": expected_realized_pnl,
                "unrealizedPnl": 0.0,
                "netPnl": expected_realized_pnl,
            },
        )
        self.assertEqual(pnl_payload["account"]["pnl"]["updatedAt"], resolve_payload["result"]["emittedAt"])

    def test_account_pnl_marks_contextual_probability_edits_against_current_conditional_marginals(self):
        account_id = "acct_context_pnl"
        context = [{"variableId": server.MARKETS["m2"]["variableId"], "outcomeId": "yes"}]
        body = build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8)
        body["context"] = deepcopy(context)

        edit_payload, edit_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        pnl_payload, pnl_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")

        order = edit_payload["order"]
        context_key = server.context_state_key(context)
        valuation_distribution = server.CONDITIONAL_MARGINALS["m1"][context_key]
        score_by_outcome = server._round_score_by_outcome(
            server.lmsr.lmsr_score_delta(
                order["previousMarginals"],
                order["newMarginals"],
                float(server.MARKETS["m1"]["liquidity"]),
            )
        )
        expected_marked_value = server.round_risk_value(
            sum(float(valuation_distribution[outcome_id]) * float(score) for outcome_id, score in score_by_outcome.items())
        )
        expected_unrealized_pnl = server.round_risk_value(expected_marked_value - float(order["impactScore"]))

        self.assertEqual(edit_status, 201)
        self.assertEqual(pnl_status, 200)
        self.assertEqual(
            pnl_payload["account"]["pnl"]["positions"],
            [
                {
                    "marketId": "m1",
                    "marketTitle": server.MARKETS["m1"]["title"],
                    "marketStatus": "active",
                    "realizedPnl": 0.0,
                    "unrealizedPnl": expected_unrealized_pnl,
                    "costBasis": order["impactScore"],
                    "markedValue": expected_marked_value,
                }
            ],
        )

    def test_account_pnl_falls_back_to_unconditional_marginals_when_context_slice_missing(self):
        account_id = "acct_context_fallback"
        context = [{"variableId": server.MARKETS["m2"]["variableId"], "outcomeId": "yes"}]
        body = build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8)
        body["context"] = deepcopy(context)

        edit_payload, edit_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        context_key = server.context_state_key(context)
        del server.CONDITIONAL_MARGINALS["m1"][context_key]

        pnl_payload, pnl_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")

        order = edit_payload["order"]
        valuation_distribution = deepcopy(server.MARKETS["m1"]["marginals"])
        score_by_outcome = server._round_score_by_outcome(
            server.lmsr.lmsr_score_delta(
                order["previousMarginals"],
                order["newMarginals"],
                float(server.MARKETS["m1"]["liquidity"]),
            )
        )
        expected_marked_value = server.round_risk_value(
            sum(float(valuation_distribution[outcome_id]) * float(score) for outcome_id, score in score_by_outcome.items())
        )
        expected_unrealized_pnl = server.round_risk_value(expected_marked_value - float(order["impactScore"]))

        self.assertEqual(edit_status, 201)
        self.assertEqual(pnl_status, 200)
        self.assertEqual(pnl_payload["account"]["pnl"]["positions"][0]["markedValue"], expected_marked_value)
        self.assertEqual(pnl_payload["account"]["pnl"]["positions"][0]["unrealizedPnl"], expected_unrealized_pnl)

    def test_account_pnl_marks_event_trade_sells_with_signed_cost_basis_and_payout(self):
        account_id = "acct_short_pnl"
        trade_payload, trade_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body(account_id, "m1", "yes", size=3.0, side="sell"),
        )
        resolve_payload, resolve_status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_short", "no"),
        )
        pnl_payload, pnl_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")

        order = trade_payload["order"]
        expected_cost_basis = server.round_risk_value(-float(order["size"]) * float(order["price"]))
        expected_marked_value = 0.0
        expected_realized_pnl = server.round_risk_value(expected_marked_value - expected_cost_basis)

        self.assertEqual(trade_status, 201)
        self.assertEqual(resolve_status, 201)
        self.assertEqual(pnl_status, 200)
        self.assertEqual(
            pnl_payload["account"]["pnl"]["positions"],
            [
                {
                    "marketId": "m1",
                    "marketTitle": server.MARKETS["m1"]["title"],
                    "marketStatus": "resolved",
                    "realizedPnl": expected_realized_pnl,
                    "unrealizedPnl": 0.0,
                    "costBasis": expected_cost_basis,
                    "markedValue": expected_marked_value,
                }
            ],
        )
        self.assertEqual(pnl_payload["account"]["pnl"]["updatedAt"], resolve_payload["result"]["emittedAt"])

    def test_account_pnl_updated_at_tracks_market_valuation_changes_from_other_accounts(self):
        account_id = "acct_mark_to_market"
        own_trade_payload, own_trade_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body(account_id, "m1", "yes", size=5.0, side="buy"),
        )
        before_payload, before_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")
        other_edit_payload, other_edit_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body("acct_other", "m1", "yes", 0.8),
        )
        after_payload, after_status = server.route_request("GET", f"/v1/accounts/{account_id}/pnl")

        self.assertEqual(own_trade_status, 201)
        self.assertEqual(before_status, 200)
        self.assertEqual(other_edit_status, 201)
        self.assertEqual(after_status, 200)
        self.assertEqual(before_payload["account"]["pnl"]["updatedAt"], own_trade_payload["result"]["emittedAt"])
        self.assertEqual(after_payload["account"]["pnl"]["updatedAt"], other_edit_payload["result"]["emittedAt"])
        self.assertGreater(
            after_payload["account"]["pnl"]["positions"][0]["markedValue"],
            before_payload["account"]["pnl"]["positions"][0]["markedValue"],
        )
        self.assertGreater(
            after_payload["account"]["pnl"]["positions"][0]["unrealizedPnl"],
            before_payload["account"]["pnl"]["positions"][0]["unrealizedPnl"],
        )

    def test_account_pnl_requires_known_account(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/accounts/acct_missing/pnl")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "account_not_found")
        self.assertEqual(error.details["accountId"], "acct_missing")

    def test_account_pnl_route_is_method_not_allowed_for_post(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/accounts/acct_test/pnl", {})

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "POST")
        self.assertEqual(error.details["path"], "/v1/accounts/acct_test/pnl")

    def test_list_markets_returns_summary_shape(self):
        payload, status = server.route_request("GET", "/v1/markets")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 3)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m1", "m2", "m3"])
        self.assertEqual(payload["meta"]["filters"], {"status": None, "sort": None, "q": None})
        self.assertTrue(payload["meta"]["timestamp"].endswith("Z"))
        self.assertEqual(
            set(payload["markets"][0].keys()),
            {"id", "title", "status", "liquidity", "volume", "expires_at"},
        )
        self.assertNotIn("description", payload["markets"][0])

    def test_list_markets_accepts_status_all_alias(self):
        payload, status = server.route_request("GET", "/v1/markets?status=all")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 3)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m1", "m2", "m3"])
        self.assertEqual(payload["meta"]["filters"], {"status": None, "sort": None, "q": None})

    def test_list_markets_filters_by_status(self):
        payload, status = server.route_request("GET", "/v1/markets?status=resolved")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m3"])
        self.assertEqual(payload["meta"]["filters"], {"status": "resolved", "sort": None, "q": None})

    def test_list_markets_keeps_closed_and_draft_status_filters_valid(self):
        for market_status in ("closed", "draft"):
            with self.subTest(status=market_status):
                payload, status = server.route_request("GET", f"/v1/markets?status={market_status}")

                self.assertEqual(status, 200)
                self.assertEqual(payload["count"], 0)
                self.assertEqual(payload["markets"], [])
                self.assertEqual(payload["meta"]["filters"], {"status": market_status, "sort": None, "q": None})

    def test_list_markets_filters_by_trimmed_case_insensitive_title_search(self):
        payload, status = server.route_request("GET", "/v1/markets?q=%20ETH%20")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m1"])
        self.assertEqual(payload["meta"]["filters"], {"status": None, "sort": None, "q": "ETH"})

    def test_list_markets_treats_blank_search_like_no_filter(self):
        payload, status = server.route_request("GET", "/v1/markets?q=%20%20")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 3)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m1", "m2", "m3"])
        self.assertEqual(payload["meta"]["filters"], {"status": None, "sort": None, "q": None})

    def test_list_markets_applies_supported_sorts_descending(self):
        expectations = {
            "volume": ["m3", "m1", "m2"],
            "liquidity": ["m3", "m1", "m2"],
            "created": ["m2", "m1", "m3"],
        }

        for sort, expected_ids in expectations.items():
            with self.subTest(sort=sort):
                payload, status = server.route_request("GET", f"/v1/markets?sort={sort}")

                self.assertEqual(status, 200)
                self.assertEqual([market["id"] for market in payload["markets"]], expected_ids)
                self.assertEqual(payload["meta"]["filters"], {"status": None, "sort": sort, "q": None})

    def test_list_markets_combines_status_search_and_sort_filters(self):
        payload, status = server.route_request("GET", "/v1/markets?status=active&q=t&sort=liquidity")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual([market["id"] for market in payload["markets"]], ["m1", "m2"])
        self.assertEqual(payload["meta"]["filters"], {"status": "active", "sort": "liquidity", "q": "t"})

    def test_invalid_status_filter_returns_contract_error(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets?status=unknown")

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_query")
        self.assertEqual(error.details["parameter"], "status")

    def test_invalid_market_list_sort_returns_contract_error(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets?sort=oldest")

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_query")
        self.assertEqual(error.details["parameter"], "sort")

    def test_duplicate_market_list_query_params_return_contract_error(self):
        paths = {
            "status": "/v1/markets?status=active&status=resolved",
            "sort": "/v1/markets?sort=volume&sort=created",
            "q": "/v1/markets?q=eth&q=btc",
        }

        for parameter, path in paths.items():
            with self.subTest(parameter=parameter):
                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request("GET", path)

                error = ctx.exception
                self.assertEqual(error.status, 400)
                self.assertEqual(error.code, "invalid_query")
                self.assertEqual(error.details["parameter"], parameter)

    def test_market_detail_returns_variable_and_marginals(self):
        payload, status = server.route_request("GET", "/v1/markets/m1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["market"]["id"], "m1")
        self.assertEqual(payload["market"]["variableId"], "eth_price_gt_3000_mar15")
        self.assertEqual(payload["market"]["marginals"], {"yes": 0.65, "no": 0.35})

    def test_market_meta_returns_normalized_preview(self):
        payload, status = server.route_request("GET", "/v1/markets/m1/meta")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["preview"],
            {
                "marketId": "m1",
                "title": "ETH Price > $3000 on March 15",
                "description": "Will ETH trade above $3000 at any point on March 15, 2026?",
                "url": f"{server.DEFAULT_PUBLIC_ORIGIN}/markets/m1",
                "siteName": server.SITE_NAME,
                "type": server.OPEN_GRAPH_TYPE,
            },
        )

    def test_market_meta_prefers_configured_public_origin(self):
        with patch.dict(server.os.environ, {server.PUBLIC_ORIGIN_ENV: "https://bayes.futarchy.ai/app/"}, clear=False):
            payload, status = server.route_request("GET", "/v1/markets/m1/meta")

        self.assertEqual(status, 200)
        self.assertEqual(payload["preview"]["url"], "https://bayes.futarchy.ai/markets/m1")

    def test_market_events_returns_genesis_chain_for_existing_market_without_events(self):
        payload, status = server.route_request("GET", "/v1/markets/m1/events")

        self.assertEqual(status, 200)
        self.assertEqual(payload["marketId"], "m1")
        self.assertEqual(payload["events"], [])
        self.assertEqual(
            payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 0,
                "headHash": server.GENESIS_EVENT_HASH,
            },
        )
        self.assertEqual(
            payload["pagination"],
            {
                "fromSeq": 1,
                "limit": 100,
                "returned": 0,
                "nextFromSeq": None,
            },
        )
        self.assertTrue(payload["meta"]["timestamp"].endswith("Z"))

    def test_market_events_returns_canonical_events_with_chain_head(self):
        first_write, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_events",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        second_write, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_events",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
                "context": [],
            },
        )

        payload, status = server.route_request("GET", "/v1/markets/m1/events")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(status, 200)
        self.assertEqual([event["seq"] for event in payload["events"]], [1, 2])
        self.assertEqual(payload["events"][0], server.EVENTS[first_write["result"]["eventId"]])
        self.assertEqual(payload["events"][1], server.EVENTS[second_write["result"]["eventId"]])
        self.assertEqual(payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(payload["events"][1]["prevEventHash"], payload["events"][0]["eventHash"])
        self.assertEqual(
            payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 2,
                "headHash": payload["events"][1]["eventHash"],
            },
        )
        self.assertEqual(
            payload["pagination"],
            {
                "fromSeq": 1,
                "limit": 100,
                "returned": 2,
                "nextFromSeq": None,
            },
        )

    def test_market_events_supports_sequence_pagination(self):
        for probability in (0.8, 0.7):
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_events",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": probability},
                    "context": [],
                },
            )
            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")

        first_page, first_page_status = server.route_request("GET", "/v1/markets/m1/events?fromSeq=1&limit=1")
        second_page, second_page_status = server.route_request("GET", "/v1/markets/m1/events?fromSeq=2&limit=1")

        self.assertEqual(first_page_status, 200)
        self.assertEqual(second_page_status, 200)
        self.assertEqual([event["seq"] for event in first_page["events"]], [1])
        self.assertEqual(first_page["pagination"]["nextFromSeq"], 2)
        self.assertEqual(first_page["chain"]["headSeq"], 2)
        self.assertEqual(first_page["chain"]["headHash"], second_page["events"][0]["eventHash"])
        self.assertEqual([event["seq"] for event in second_page["events"]], [2])
        self.assertIsNone(second_page["pagination"]["nextFromSeq"])

    def test_market_events_requires_known_market(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/missing/events")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "market_not_found")
        self.assertEqual(error.details["market_id"], "missing")

    def test_market_events_rejects_invalid_query(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/m1/events?fromSeq=0")

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_query")
        self.assertEqual(error.details["parameter"], "fromSeq")

        with self.assertRaises(server.ApiError) as limit_ctx:
            server.route_request("GET", "/v1/markets/m1/events?limit=101")

        limit_error = limit_ctx.exception
        self.assertEqual(limit_error.status, 400)
        self.assertEqual(limit_error.code, "invalid_query")
        self.assertEqual(limit_error.details["parameter"], "limit")

    def test_market_events_route_is_method_not_allowed_for_post(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/markets/m1/events", {})

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "POST")
        self.assertEqual(error.details["path"], "/v1/markets/m1/events")

    def test_market_engine_stats_returns_zeroed_empty_state_for_existing_market(self):
        payload, status = server.route_request("GET", "/v1/markets/m1/engine-stats")

        self.assertEqual(status, 200)
        self.assertEqual(payload["marketId"], "m1")
        self.assertEqual(
            payload["engine"],
            {
                "mode": "EXACT",
                "backend": "junction_tree",
                "version": "0.1.0",
                "precision": "float64",
                "compile_id": None,
                "compile_type": None,
                "source_state_hash": None,
            },
        )
        self.assertEqual(
            payload["cliques"],
            {
                "num_cliques": 0,
                "max_clique_size": 0,
                "junction_tree_width": 0,
                "cliques": [],
            },
        )
        self.assertEqual(
            payload["diagnostics"],
            {
                "request_count": 0,
                "error_count": 0,
                "inference": {
                    "count": 0,
                    "mean_ms": 0.0,
                    "p50_ms": 0.0,
                    "p95_ms": 0.0,
                    "p99_ms": 0.0,
                },
                "cache": {
                    "hits": 0,
                    "misses": 0,
                    "hit_rate": 0.0,
                },
            },
        )
        self.assertTrue(payload["meta"]["timestamp"].endswith("Z"))

    def test_market_engine_stats_materializes_compile_snapshot_after_probability_edit(self):
        write_payload, write_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_engine_stats",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        payload, status = server.route_request("GET", "/v1/markets/m1/engine-stats")

        self.assertEqual(write_status, 201)
        self.assertEqual(write_payload["result"]["status"], "accepted")
        self.assertEqual(status, 200)
        self.assertEqual(payload["marketId"], "m1")
        self.assertEqual(payload["engine"]["mode"], "EXACT")
        self.assertEqual(payload["engine"]["backend"], "junction_tree")
        self.assertEqual(payload["engine"]["version"], "0.1.0")
        self.assertEqual(payload["engine"]["precision"], "float64")
        self.assertEqual(payload["engine"]["compile_type"], "junction_tree")
        self.assertEqual(payload["engine"]["source_state_hash"], server.market_replay_state_hash("m1"))
        self.assertEqual(
            payload["engine"]["compile_id"],
            f"comp-{payload['engine']['source_state_hash'].split(':', 1)[-1][:12]}",
        )
        self.assertEqual(
            payload["cliques"],
            {
                "num_cliques": 1,
                "max_clique_size": 1,
                "junction_tree_width": 0,
                "cliques": [
                    {
                        "id": "m1-c1",
                        "nodes": [server.MARKETS["m1"]["variableId"]],
                        "size": 1,
                        "states": len(server.MARKETS["m1"]["outcomes"]),
                    }
                ],
            },
        )
        self.assertEqual(payload["diagnostics"]["request_count"], 1)
        self.assertEqual(payload["diagnostics"]["error_count"], 0)
        self.assertEqual(payload["diagnostics"]["inference"]["count"], 1)
        self.assertEqual(payload["diagnostics"]["cache"], {"hits": 0, "misses": 0, "hit_rate": 0.0})
        self.assertIn("compile_time_ms", payload["diagnostics"])
        self.assertIn("memory_bytes", payload["diagnostics"])
        self.assertIn("last_updated", payload["diagnostics"])
        self.assertGreaterEqual(payload["diagnostics"]["compile_time_ms"], 0.0)
        self.assertGreater(payload["diagnostics"]["memory_bytes"], 0)
        self.assertTrue(payload["diagnostics"]["last_updated"].endswith("Z"))

    def test_market_engine_stats_materializes_compile_snapshot_after_resolution(self):
        context = [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m1"] = {
            server.context_state_key(context): {"yes": 0.7, "no": 0.3},
        }

        write_payload, write_status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_engine_stats", "yes"),
        )
        payload, status = server.route_request("GET", "/v1/markets/m1/engine-stats")

        self.assertEqual(write_status, 201)
        self.assertEqual(write_payload["result"]["status"], "accepted")
        self.assertEqual(status, 200)
        self.assertEqual(payload["marketId"], "m1")
        self.assertEqual(payload["engine"]["source_state_hash"], server.market_replay_state_hash("m1"))
        self.assertEqual(
            payload["engine"]["compile_id"],
            f"comp-{payload['engine']['source_state_hash'].split(':', 1)[-1][:12]}",
        )
        self.assertNotIn("m1", server.CONDITIONAL_MARGINALS)

    def test_refresh_market_compile_snapshot_uses_current_model_compiler_adapter(self):
        class StubClique:
            def __init__(self, clique_id: str, nodes: tuple[str, ...], size: int, states: int):
                self.id = clique_id
                self.nodes = nodes
                self.size = size
                self.states = states

            def to_dict(self) -> dict[str, object]:
                return {
                    "id": self.id,
                    "nodes": list(self.nodes),
                    "size": self.size,
                    "states": self.states,
                }

        class StubCompiler:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def compile_result(
                self,
                *,
                market_snapshot: dict[str, object],
                conditional_marginals: dict[str, dict[str, float]] | None = None,
                compile_time_ms: float = 0.0,
                last_updated: str,
            ) -> server.CompileResult:
                self.calls.append(
                    {
                        "market_snapshot": market_snapshot,
                        "conditional_marginals": conditional_marginals or {},
                        "compile_time_ms": compile_time_ms,
                        "last_updated": last_updated,
                    }
                )
                return server.CompileResult(
                    compile_id="comp-adapter-test",
                    compile_type="junction_tree",
                    source_state_hash="sha256:adapter",
                    cliques=(StubClique("adapter-c1", ("eth_price_gt_3000_mar15",), 1, 2),),
                    compile_time_ms=round(float(compile_time_ms), 3),
                    memory_bytes=512,
                    last_updated=last_updated,
                )

        original_compiler = server.CURRENT_MODEL_COMPILER
        stub_compiler = StubCompiler()
        server.CURRENT_MODEL_COMPILER = stub_compiler

        try:
            server.CONDITIONAL_MARGINALS["m1"] = {
                "btc_etf_approval_week=yes": {"yes": 0.8, "no": 0.2}
            }
            server.refresh_market_compile_snapshot("m1", compile_time_ms=12.345)
        finally:
            server.CURRENT_MODEL_COMPILER = original_compiler

        self.assertEqual(len(stub_compiler.calls), 1)
        self.assertEqual(stub_compiler.calls[0]["market_snapshot"], server.MARKETS["m1"])
        self.assertIsNot(stub_compiler.calls[0]["market_snapshot"], server.MARKETS["m1"])
        self.assertEqual(
            stub_compiler.calls[0]["conditional_marginals"],
            server.CONDITIONAL_MARGINALS["m1"],
        )
        self.assertIsNot(
            stub_compiler.calls[0]["conditional_marginals"],
            server.CONDITIONAL_MARGINALS["m1"],
        )
        self.assertEqual(stub_compiler.calls[0]["compile_time_ms"], 12.345)

        state = server.MARKET_ENGINE_STATS["m1"]
        self.assertEqual(state["compile_id"], "comp-adapter-test")
        self.assertEqual(state["source_state_hash"], "sha256:adapter")
        self.assertEqual(state["memory_bytes"], 512)
        self.assertEqual(
            state["cliques"],
            [{"id": "adapter-c1", "nodes": ["eth_price_gt_3000_mar15"], "size": 1, "states": 2}],
        )

    def test_market_engine_stats_tracks_market_rejections_without_compile_snapshot(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            {
                "accountId": "acct_engine_stats_rejection",
                "variableId": "fed_rate_cut_mar_2026",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                "context": [],
            },
        )
        stats_payload, stats_status = server.route_request("GET", "/v1/markets/m3/engine-stats")

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_active")
        self.assertEqual(stats_status, 200)
        self.assertEqual(stats_payload["engine"]["compile_id"], None)
        self.assertEqual(stats_payload["engine"]["compile_type"], None)
        self.assertEqual(stats_payload["engine"]["source_state_hash"], None)
        self.assertEqual(stats_payload["cliques"]["num_cliques"], 0)
        self.assertEqual(stats_payload["diagnostics"]["request_count"], 1)
        self.assertEqual(stats_payload["diagnostics"]["error_count"], 1)
        self.assertEqual(stats_payload["diagnostics"]["inference"]["count"], 1)
        self.assertEqual(stats_payload["diagnostics"]["cache"], {"hits": 0, "misses": 0, "hit_rate": 0.0})
        self.assertNotIn("compile_time_ms", stats_payload["diagnostics"])
        self.assertNotIn("memory_bytes", stats_payload["diagnostics"])
        self.assertNotIn("last_updated", stats_payload["diagnostics"])

    def test_market_engine_stats_requires_known_market(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/missing/engine-stats")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "market_not_found")
        self.assertEqual(error.details["market_id"], "missing")

    def test_market_engine_stats_route_is_method_not_allowed_for_post(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/markets/m1/engine-stats", {})

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "POST")
        self.assertEqual(error.details["path"], "/v1/markets/m1/engine-stats")

    def test_account_risk_requires_known_account(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/accounts/acct_missing/risk")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "account_not_found")
        self.assertEqual(error.details["accountId"], "acct_missing")

    def test_account_risk_route_is_method_not_allowed_for_post(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/accounts/acct_test/risk", {})

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "POST")
        self.assertEqual(error.details["path"], "/v1/accounts/acct_test/risk")

    def test_probability_edit_success_updates_market(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["marketId"], "m1")
        self.assertEqual(payload["order"]["accountId"], "acct_test")
        self.assertEqual(payload["order"]["payload"]["target"]["probability"], 0.8)
        self.assertEqual(payload["order"]["newMarginals"], {"yes": 0.8, "no": 0.2})
        self.assertTrue(payload["order"]["commandId"].startswith("cmd_"))
        self.assertTrue(payload["order"]["submittedAt"].endswith("Z"))
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(payload["result"]["eventType"], "CommandAccepted")
        self.assertEqual(payload["result"]["commandId"], payload["order"]["commandId"])
        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(event["schemaVersion"], "bayes-event/v1")
        self.assertEqual(event["seq"], 1)
        self.assertEqual(event["payload"]["effects"]["marginalDelta"][0]["before"], 0.65)
        self.assertEqual(event["payload"]["effects"]["marginalDelta"][0]["after"], 0.8)
        self.assertEqual(
            event["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": "acct_test",
                "marketId": "m1",
                "beforeMinAsset": 100.0,
                "afterMinAsset": round(100.0 - payload["order"]["impactScore"], 6),
            },
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})

    def test_probability_edit_success_persists_unconditional_order_state(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        stored_order = server.ORDERS[payload["order"]["id"]]
        self.assertEqual(stored_order["previousMarginals"], payload["order"]["previousMarginals"])
        self.assertEqual(stored_order["newMarginals"], payload["order"]["newMarginals"])
        self.assertEqual(stored_order["impactScore"], payload["order"]["impactScore"])
        self.assertEqual(server.MARKETS["m1"]["marginals"], stored_order["newMarginals"])
        self.assertEqual(server.CONDITIONAL_MARGINALS, {})

    def test_account_risk_read_model_updates_after_probability_edit(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        risk_payload, risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")

        self.assertEqual(status, 201)
        self.assertEqual(risk_status, 200)
        self.assertEqual(risk_payload["account"]["id"], "acct_test")
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - payload["order"]["impactScore"], 6),
        )
        self.assertEqual(
            risk_payload["account"]["risk"]["capacityIndicators"],
            {
                "limit": 100.0,
                "available": round(100.0 - payload["order"]["impactScore"], 6),
                "consumed": round(payload["order"]["impactScore"], 6),
                "utilization": round(payload["order"]["impactScore"] / 100.0, 6),
                "status": "healthy",
            },
        )
        self.assertTrue(risk_payload["account"]["risk"]["updatedAt"].endswith("Z"))
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["markets"],
            [
                {
                    "marketId": "m1",
                    "minAsset": round(100.0 - payload["order"]["impactScore"], 6),
                    "capacityConsumed": round(payload["order"]["impactScore"], 6),
                    "utilization": round(payload["order"]["impactScore"] / 100.0, 6),
                    "commandCount": 1,
                    "lastOrderId": payload["order"]["id"],
                    "lastCommandId": payload["order"]["commandId"],
                    "updatedAt": payload["order"]["filledAt"],
                }
            ],
        )

    def test_probability_edit_acceptance_populates_lmsr_ledger_slice(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        account = server.ACCOUNT_RISK["acct_test"]
        slice_key = server.account_lmsr_slice_key("m1", [])
        self.assertEqual(
            account["lmsrState"],
            {
                "version": server.ACCOUNT_LMSR_LEDGER_VERSION,
                "riskReadModel": server.ACCOUNT_LMSR_RISK_READ_MODEL,
                "slices": {
                    slice_key: {
                        "marketId": "m1",
                        "variableId": "eth_price_gt_3000_mar15",
                        "context": [],
                        "contextKey": "",
                        "liquidity": 150000.0,
                        "scoreByOutcome": rounded_score_delta(
                            payload["order"]["previousMarginals"],
                            payload["order"]["newMarginals"],
                            server.MARKETS["m1"]["liquidity"],
                        ),
                        "commandCount": 1,
                        "updatedAt": payload["order"]["filledAt"],
                        "lastOrderId": payload["order"]["id"],
                        "lastCommandId": payload["order"]["commandId"],
                    }
                },
            },
        )

    def test_probability_edit_acceptance_threads_unconditional_effects_into_audit_and_read_models(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        impact_score = payload["order"]["impactScore"]
        after_min_asset = round(100.0 - impact_score, 6)
        event = server.EVENTS[payload["result"]["eventId"]]
        slice_key = server.account_lmsr_slice_key("m1", [])

        self.assertEqual(
            event["payload"],
            {
                "effects": {
                    "marginalDelta": [
                        {
                            "variableId": "eth_price_gt_3000_mar15",
                            "outcomeId": "yes",
                            "before": 0.65,
                            "after": 0.8,
                        }
                    ],
                    "assetDelta": [
                        {
                            "accountId": "acct_test",
                            "marketId": "m1",
                            "beforeMinAsset": 100.0,
                            "afterMinAsset": after_min_asset,
                        }
                    ],
                },
                "pricing": {
                    "cost": impact_score,
                    "fee": 0.0,
                },
                "replayStateHash": server.market_replay_state_hash("m1"),
            },
        )
        self.assertEqual(
            server.ACCOUNT_RISK["acct_test"],
            server.build_account_risk_state(
                "acct_test",
                payload["order"]["filledAt"],
                min_asset=after_min_asset,
                markets={
                    "m1": {
                        "marketId": "m1",
                        "minAsset": after_min_asset,
                        "capacityConsumed": impact_score,
                        "utilization": round(impact_score / 100.0, 6),
                        "commandCount": 1,
                        "updatedAt": payload["order"]["filledAt"],
                        "lastOrderId": payload["order"]["id"],
                        "lastCommandId": payload["order"]["commandId"],
                    }
                },
                lmsr_state=server.build_account_lmsr_state(
                    {
                        slice_key: {
                            "marketId": "m1",
                            "variableId": "eth_price_gt_3000_mar15",
                            "context": [],
                            "contextKey": "",
                            "liquidity": 150000.0,
                            "scoreByOutcome": rounded_score_delta(
                                payload["order"]["previousMarginals"],
                                payload["order"]["newMarginals"],
                                server.MARKETS["m1"]["liquidity"],
                            ),
                            "commandCount": 1,
                            "updatedAt": payload["order"]["filledAt"],
                            "lastOrderId": payload["order"]["id"],
                            "lastCommandId": payload["order"]["commandId"],
                        }
                    }
                ),
            ),
        )

    def test_probability_edit_conditional_lmsr_ledger_keeps_separate_context_slices(self):
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        slices = server.ACCOUNT_RISK["acct_test"]["lmsrState"]["slices"]
        self.assertEqual(
            set(slices),
            {
                server.account_lmsr_slice_key("m1", []),
                server.account_lmsr_slice_key("m1", second_payload["order"]["payload"]["context"]),
            },
        )
        self.assertEqual(
            slices[server.account_lmsr_slice_key("m1", [])]["scoreByOutcome"],
            rounded_score_delta(
                first_payload["order"]["previousMarginals"],
                first_payload["order"]["newMarginals"],
                server.MARKETS["m1"]["liquidity"],
            ),
        )
        self.assertEqual(
            slices[server.account_lmsr_slice_key("m1", second_payload["order"]["payload"]["context"])],
            {
                "marketId": "m1",
                "variableId": "eth_price_gt_3000_mar15",
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
                "contextKey": "btc_etf_approval_week=yes",
                "liquidity": 150000.0,
                "scoreByOutcome": rounded_score_delta(
                    second_payload["order"]["previousMarginals"],
                    second_payload["order"]["newMarginals"],
                    server.MARKETS["m1"]["liquidity"],
                ),
                "commandCount": 1,
                "updatedAt": second_payload["order"]["filledAt"],
                "lastOrderId": second_payload["order"]["id"],
                "lastCommandId": second_payload["order"]["commandId"],
            },
        )

    def test_probability_edit_replay_does_not_double_apply_lmsr_ledger_slice(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-lmsr-ledger",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        post_first_account = deepcopy(server.ACCOUNT_RISK["acct_test"])
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(second_payload["order"]["id"], first_payload["order"]["id"])
        self.assertEqual(server.ACCOUNT_RISK["acct_test"], post_first_account)
        self.assertEqual(
            server.ACCOUNT_RISK["acct_test"]["lmsrState"]["slices"][server.account_lmsr_slice_key("m1", [])]["commandCount"],
            1,
        )

    def test_probability_edit_lmsr_ledger_accumulates_same_slice_score_by_outcome(self):
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
                "context": [],
            },
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        first_delta = rounded_score_delta(
            first_payload["order"]["previousMarginals"],
            first_payload["order"]["newMarginals"],
            server.MARKETS["m1"]["liquidity"],
        )
        second_delta = rounded_score_delta(
            second_payload["order"]["previousMarginals"],
            second_payload["order"]["newMarginals"],
            server.MARKETS["m1"]["liquidity"],
        )
        self.assertEqual(
            server.ACCOUNT_RISK["acct_test"]["lmsrState"]["slices"][server.account_lmsr_slice_key("m1", [])],
            {
                "marketId": "m1",
                "variableId": "eth_price_gt_3000_mar15",
                "context": [],
                "contextKey": "",
                "liquidity": 150000.0,
                "scoreByOutcome": {
                    outcome_id: server.round_risk_value(first_delta[outcome_id] + second_delta[outcome_id])
                    for outcome_id in first_delta
                },
                "commandCount": 2,
                "updatedAt": second_payload["order"]["filledAt"],
                "lastOrderId": second_payload["order"]["id"],
                "lastCommandId": second_payload["order"]["commandId"],
            },
        )

    def test_account_risk_aggregates_consumed_capacity_across_markets(self):
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "btc_etf_approval_week",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                "context": [],
            },
        )
        risk_payload, risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(risk_status, 200)
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - first_payload["order"]["impactScore"] - second_payload["order"]["impactScore"], 6),
        )
        market_consumed = sum(
            market["capacityConsumed"] for market in risk_payload["account"]["risk"]["minAssets"]["markets"]
        )
        self.assertEqual(
            risk_payload["account"]["risk"]["capacityIndicators"]["consumed"],
            round(market_consumed, 6),
        )
        self.assertEqual(
            [market["marketId"] for market in risk_payload["account"]["risk"]["minAssets"]["markets"]],
            ["m1", "m2"],
        )
        self.assertEqual(risk_payload["account"]["risk"]["updatedAt"], second_payload["order"]["filledAt"])

    def test_account_risk_asset_delta_matches_repeated_probability_edit_transition(self):
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        first_risk_payload, first_risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
                "context": [],
            },
        )
        second_risk_payload, second_risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")

        self.assertEqual(first_status, 201)
        self.assertEqual(first_risk_status, 200)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_risk_status, 200)
        second_event = server.EVENTS[second_payload["result"]["eventId"]]
        self.assertEqual(
            second_event["payload"]["effects"]["assetDelta"][0]["beforeMinAsset"],
            first_risk_payload["account"]["risk"]["minAssets"]["overall"],
        )
        self.assertEqual(
            second_event["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
            second_risk_payload["account"]["risk"]["minAssets"]["overall"],
        )
        self.assertEqual(second_risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 2)

    def test_probability_edit_materializes_canonical_command(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "idempotencyKey": "idem-123",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [
                    {"variableId": " fed_rate_cut_mar_2026 ", "outcomeId": " no "},
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                ],
            },
        )

        self.assertEqual(status, 201)
        command = server.COMMANDS[payload["order"]["commandId"]]
        self.assertEqual(command["schemaVersion"], "bayes-command/v1")
        self.assertEqual(command["marketId"], "m1")
        self.assertEqual(command["accountId"], "acct_test")
        self.assertEqual(command["commandType"], "ProbabilityEdit")
        self.assertEqual(command["idempotencyKey"], "idem-123")
        self.assertEqual(command["submittedAt"], payload["order"]["submittedAt"])
        self.assertEqual(
            command["payload"],
            {
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                    {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
                ],
            },
        )
        self.assertEqual(command["meta"], {"source": "api"})

    def test_unconditional_preview_is_side_effect_free_for_new_account(self):
        normalized_payload = server.normalize_probability_edit_payload(
            "m1",
            {
                "accountId": "acct_preview",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        preview = server.preview_unconditional_probability_edit("m1", normalized_payload, "acct_preview")

        self.assertEqual(preview["previousMarginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(preview["newMarginals"], {"yes": 0.8, "no": 0.2})
        self.assertEqual(preview["assetDelta"]["beforeMinAsset"], 100.0)
        self.assertEqual(preview["assetDelta"]["afterMinAsset"], round(100.0 - preview["impactScore"], 6))
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.CONDITIONAL_MARGINALS, {})
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.ACCOUNT_RISK, {})

    def test_probability_edit_three_outcome_market_rescales_remaining_mass(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            {
                "accountId": "acct_multi",
                "variableId": "btc_etf_approval_week",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["newMarginals"], {"yes": 0.4, "no": 0.48, "delayed": 0.12})
        self.assertEqual(payload["order"]["accountId"], "acct_multi")
        self.assertTrue(payload["order"]["commandId"].startswith("cmd_"))

    def test_validate_structure_preserving_edit_accepts_binary_market_payload(self):
        normalized_payload = {
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        self.assertIsNone(server.validate_structure_preserving_edit(server.MARKETS["m1"], normalized_payload))

    def test_validate_structure_preserving_edit_accepts_three_outcome_market_payload(self):
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        self.assertIsNone(server.validate_structure_preserving_edit(server.MARKETS["m2"], normalized_payload))

    def test_validate_structure_preserving_edit_accepts_high_probability_three_outcome_payload(self):
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.99},
            "context": [],
        }

        self.assertIsNone(server.validate_structure_preserving_edit(server.MARKETS["m2"], normalized_payload))

    def test_validate_structure_preserving_edit_rejects_unknown_target_outcome(self):
        normalized_payload = {
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "unknown", "probability": 0.8},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(server.MARKETS["m1"], normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["outcomeId"], "unknown")

    def test_validate_structure_preserving_edit_rejects_unknown_context_assignment(self):
        normalized_payload = {
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [{"variableId": "unknown_variable", "outcomeId": "yes"}],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(server.MARKETS["m1"], normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["field"], "context[0].variableId")

    def test_validate_structure_preserving_edit_rejects_invalid_known_context_outcome(self):
        normalized_payload = {
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "invalid"}],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(server.MARKETS["m1"], normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["field"], "context[0].outcomeId")
        self.assertEqual(error.details["variableId"], "btc_etf_approval_week")
        self.assertEqual(error.details["received"], "invalid")

    def test_validate_structure_preserving_edit_rejects_impossible_renormalization_fixture(self):
        malformed_market = deepcopy(server.MARKETS["m2"])
        malformed_market["id"] = "m2_malformed"
        malformed_market["marginals"] = {"yes": 1.0, "no": -0.2, "delayed": 0.2}
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(malformed_market, normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2_malformed")
        self.assertIn("non-negative", error.message)

    def test_validate_structure_preserving_edit_rejects_missing_market_outcome_mass(self):
        malformed_market = deepcopy(server.MARKETS["m2"])
        malformed_market["id"] = "m2_missing_outcome"
        malformed_market["marginals"] = {"no": 0.8, "delayed": 0.2}
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(malformed_market, normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2_missing_outcome")
        self.assertIn("exactly one value for each market outcome", error.message)

    def test_validate_structure_preserving_edit_rejects_unexpected_market_outcome_mass(self):
        malformed_market = deepcopy(server.MARKETS["m2"])
        malformed_market["id"] = "m2_extra_outcome"
        malformed_market["marginals"] = {"yes": 0.25, "no": 0.45, "delayed": 0.15, "later": 0.15}
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(malformed_market, normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2_extra_outcome")
        self.assertIn("exactly one value for each market outcome", error.message)

    def test_validate_structure_preserving_edit_rejects_non_unit_market_mass(self):
        malformed_market = deepcopy(server.MARKETS["m2"])
        malformed_market["id"] = "m2_non_unit"
        malformed_market["marginals"] = {"yes": 0.25, "no": 0.7, "delayed": 0.25}
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(malformed_market, normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2_non_unit")
        self.assertIn("sum to 1.0", error.message)

    def test_validate_structure_preserving_edit_rejects_non_finite_market_mass(self):
        malformed_market = deepcopy(server.MARKETS["m2"])
        malformed_market["id"] = "m2_non_finite"
        malformed_market["marginals"] = {"yes": math.nan, "no": 0.6, "delayed": 0.4}
        normalized_payload = {
            "variableId": "btc_etf_approval_week",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.validate_structure_preserving_edit(malformed_market, normalized_payload)

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2_non_finite")
        self.assertIn("finite numeric values", error.message)

    def test_normalize_probability_edit_payload_uses_existing_conditional_slice_for_validation(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"yes": 1.0, "no": -0.2, "delayed": 0.2}
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_conditional_validator",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": deepcopy(context),
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2")
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_normalize_probability_edit_payload_rejects_conditional_slice_missing_market_outcome_mass(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"no": 0.8, "delayed": 0.2}
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_conditional_validator",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": deepcopy(context),
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2")
        self.assertIn("exactly one value for each market outcome", error.message)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_normalize_probability_edit_payload_rejects_non_finite_conditional_slice_mass(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"yes": 0.25, "no": math.inf, "delayed": 0.15}
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_conditional_validator",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": deepcopy(context),
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2")
        self.assertIn("finite numeric values", error.message)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_normalize_probability_edit_payload_rejects_conditional_slice_with_extra_outcome_mass(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"yes": 0.25, "no": 0.45, "delayed": 0.15, "later": 0.15}
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_conditional_validator",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": deepcopy(context),
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2")
        self.assertIn("exactly one value for each market outcome", error.message)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_normalize_probability_edit_payload_rejects_conditional_slice_with_non_unit_mass(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"yes": 0.25, "no": 0.6, "delayed": 0.2}
        }

        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_conditional_validator",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": deepcopy(context),
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_structure_preserving_edit")
        self.assertEqual(error.details["marketId"], "m2")
        self.assertIn("sum to 1.0", error.message)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_probability_edit_rejects_wrong_variable_id(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_test",
                    "variableId": "wrong_variable",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                    "context": [],
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_probability_edit")
        self.assertEqual(error.details["expected"], "eth_price_gt_3000_mar15")

    def test_probability_edit_with_context_tracks_conditional_distribution(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(
            payload["order"]["payload"]["context"],
            [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
        )
        self.assertEqual(payload["order"]["previousMarginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(payload["order"]["newMarginals"], {"yes": 0.8, "no": 0.2})
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.CONDITIONAL_MARGINALS["m1"]["btc_etf_approval_week=yes"], {"yes": 0.8, "no": 0.2})

    def test_probability_edit_with_context_reads_base_slice_via_query_backend_adapter(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.contexts: list[dict[str, str] | None] = []

            def query_marginals(
                self,
                compile_result: object,
                *,
                context: dict[str, str] | None = None,
            ) -> object:
                self.contexts.append(deepcopy(context))
                return type("MarginalResult", (), {"marginals": {"yes": 0.2, "no": 0.8}})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_adapter_context",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.5},
                    "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
                },
            )
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["previousMarginals"], {"yes": 0.2, "no": 0.8})
        self.assertEqual(payload["order"]["newMarginals"], {"yes": 0.5, "no": 0.5})
        self.assertEqual(
            stub_backend.contexts,
            [
                {"btc_etf_approval_week": "yes"},
                {"btc_etf_approval_week": "yes"},
            ],
        )

    def test_preview_unconditional_probability_edit_reads_base_slice_via_query_backend_adapter(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.contexts: list[dict[str, str] | None] = []

            def query_marginals(
                self,
                compile_result: object,
                *,
                context: dict[str, str] | None = None,
            ) -> object:
                self.contexts.append(deepcopy(context))
                return type("MarginalResult", (), {"marginals": {"yes": 0.2, "no": 0.3, "delayed": 0.5}})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            normalized_payload = server.normalize_probability_edit_payload(
                "m2",
                {
                    "accountId": "acct_adapter_preview",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": [],
                },
            )
            preview = server.preview_unconditional_probability_edit("m2", normalized_payload, "acct_adapter_preview")
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        self.assertEqual(preview["previousMarginals"], {"yes": 0.2, "no": 0.3, "delayed": 0.5})
        self.assertEqual(preview["newMarginals"], {"yes": 0.4, "no": 0.225, "delayed": 0.375})
        self.assertEqual(server.MARKETS["m2"]["marginals"], {"yes": 0.25, "no": 0.6, "delayed": 0.15})
        self.assertEqual(
            stub_backend.contexts,
            [
                None,
                None,
            ],
        )

    def test_probability_edit_without_context_reads_base_slice_via_query_backend_adapter(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.contexts: list[dict[str, str] | None] = []

            def query_marginals(
                self,
                compile_result: object,
                *,
                context: dict[str, str] | None = None,
            ) -> object:
                self.contexts.append(deepcopy(context))
                return type("MarginalResult", (), {"marginals": {"yes": 0.2, "no": 0.3, "delayed": 0.5}})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m2/orders/probability-edit",
                {
                    "accountId": "acct_adapter_unconditional",
                    "variableId": "btc_etf_approval_week",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                    "context": [],
                },
            )
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["previousMarginals"], {"yes": 0.2, "no": 0.3, "delayed": 0.5})
        self.assertEqual(payload["order"]["newMarginals"], {"yes": 0.4, "no": 0.225, "delayed": 0.375})
        self.assertEqual(server.MARKETS["m2"]["marginals"], {"yes": 0.4, "no": 0.225, "delayed": 0.375})
        self.assertEqual(
            stub_backend.contexts,
            [
                None,
                None,
            ],
        )

    def test_probability_edit_without_context_reuses_previewed_adapter_rescale(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.contexts: list[dict[str, str] | None] = []

            def query_marginals(
                self,
                compile_result: object,
                *,
                context: dict[str, str] | None = None,
            ) -> object:
                self.contexts.append(deepcopy(context))
                return type("MarginalResult", (), {"marginals": {"yes": 0.2, "no": 0.3, "delayed": 0.5}})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            body = {
                "accountId": "acct_adapter_reuse",
                "variableId": "btc_etf_approval_week",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                "context": [],
            }
            normalized_payload = server.normalize_probability_edit_payload("m2", body)
            preview = server.preview_unconditional_probability_edit("m2", normalized_payload, "acct_adapter_reuse")

            payload, status = server.route_request(
                "POST",
                "/v1/markets/m2/orders/probability-edit",
                body,
            )
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["previousMarginals"], preview["previousMarginals"])
        self.assertEqual(payload["order"]["newMarginals"], preview["newMarginals"])
        self.assertEqual(payload["order"]["impactScore"], preview["impactScore"])
        self.assertEqual(server.MARKETS["m2"]["marginals"], preview["newMarginals"])
        self.assertEqual(
            stub_backend.contexts,
            [
                None,
                None,
                None,
                None,
            ],
        )

    def test_create_probability_edit_order_ignores_unconditional_preview_on_contextual_path(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.contexts: list[dict[str, str] | None] = []

            def query_marginals(
                self,
                compile_result: object,
                *,
                context: dict[str, str] | None = None,
            ) -> object:
                self.contexts.append(deepcopy(context))
                if context is None:
                    return type("MarginalResult", (), {"marginals": {"yes": 0.65, "no": 0.35}})()
                return type("MarginalResult", (), {"marginals": {"yes": 0.2, "no": 0.8}})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            unconditional_body = {
                "accountId": "acct_contextual_preview_guard",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            }
            unconditional_payload = server.normalize_probability_edit_payload("m1", unconditional_body)
            unconditional_preview = server.preview_unconditional_probability_edit(
                "m1",
                unconditional_payload,
                "acct_contextual_preview_guard",
            )

            contextual_payload = server.normalize_probability_edit_payload(
                "m1",
                {
                    "accountId": "acct_contextual_preview_guard",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.5},
                    "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
                },
            )
            command = server.materialize_probability_edit_command(
                market_id="m1",
                normalized_payload=contextual_payload,
                account_id="acct_contextual_preview_guard",
                command_id="cmd_contextual_preview_guard",
                submitted_at="2026-04-08T00:00:00Z",
            )
            order = server.create_probability_edit_order(command, preview=unconditional_preview)
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        expected_previous = {"yes": 0.2, "no": 0.8}
        expected_new = {"yes": 0.5, "no": 0.5}
        expected_impact = server.kl_divergence(expected_previous, expected_new)

        self.assertNotEqual(unconditional_preview["impactScore"], expected_impact)
        self.assertEqual(order["payload"]["context"], [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}])
        self.assertEqual(order["previousMarginals"], expected_previous)
        self.assertEqual(order["newMarginals"], expected_new)
        self.assertEqual(order["impactScore"], expected_impact)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.CONDITIONAL_MARGINALS["m1"]["btc_etf_approval_week=yes"], expected_new)
        self.assertEqual(
            stub_backend.contexts,
            [
                None,
                None,
                {"btc_etf_approval_week": "yes"},
                {"btc_etf_approval_week": "yes"},
            ],
        )

    def test_probability_edit_with_context_updates_account_risk(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )
        risk_payload, risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")

        self.assertEqual(status, 201)
        self.assertEqual(risk_status, 200)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - payload["order"]["impactScore"], 6),
        )
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)
        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(
            event["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
            risk_payload["account"]["risk"]["minAssets"]["overall"],
        )

    def test_probability_edit_normalizes_context_assignments(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [
                    {"variableId": " fed_rate_cut_mar_2026 ", "outcomeId": " no "},
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                ],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(
            payload["order"]["payload"]["context"],
            [
                {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
            ],
        )

    def test_context_state_key_canonicalizes_assignment_order(self):
        normalized_context = [
            {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
            {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
        ]
        reversed_context = list(reversed(normalized_context))

        self.assertEqual(
            server.context_state_key(normalized_context),
            "btc_etf_approval_week=yes|fed_rate_cut_mar_2026=no",
        )
        self.assertEqual(
            server.context_state_key(reversed_context),
            "btc_etf_approval_week=yes|fed_rate_cut_mar_2026=no",
        )

    def test_resolve_probability_edit_base_marginals_reuses_existing_conditional_slice_for_unordered_context(self):
        canonical_context = [
            {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
            {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
        ]
        expected_slice = {"yes": 0.8, "no": 0.2}
        server.CONDITIONAL_MARGINALS["m1"] = {
            server.context_state_key(canonical_context): deepcopy(expected_slice)
        }

        resolved = server.resolve_probability_edit_base_marginals("m1", list(reversed(canonical_context)))

        self.assertEqual(resolved, expected_slice)
        self.assertIsNot(
            resolved,
            server.CONDITIONAL_MARGINALS["m1"][server.context_state_key(canonical_context)],
        )

    def test_probability_edit_rejects_conflicting_context_assignments(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_test",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                    "context": [
                        {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                        {"variableId": "btc_etf_approval_week", "outcomeId": "no"},
                    ],
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_probability_edit")
        self.assertEqual(error.details["field"], "context[1].outcomeId")
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})

    def test_probability_edit_rejects_unknown_context_variable(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_test",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                    "context": [{"variableId": "unknown_variable", "outcomeId": "yes"}],
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_probability_edit")
        self.assertEqual(error.details["field"], "context[0].variableId")

    def test_probability_edit_requires_account_id(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                    "context": [],
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_probability_edit")
        self.assertEqual(error.details["field"], "accountId")

    def test_probability_edit_rejects_non_numeric_probability(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                {
                    "accountId": "acct_test",
                    "variableId": "eth_price_gt_3000_mar15",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": "0.8"},
                    "context": [],
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_probability_edit")
        self.assertEqual(error.details["field"], "target.probability")
        self.assertEqual(len(server.COMMANDS), 0)
        self.assertEqual(len(server.EVENTS), 0)
        self.assertEqual(len(server.ORDERS), 0)

    def test_probability_edit_echoes_idempotency_key(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_test",
                "idempotencyKey": "idem-123",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["idempotencyKey"], "idem-123")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-123")

    def test_probability_edit_replays_same_idempotency_key(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-123",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["order"]["id"], first_payload["order"]["id"])
        self.assertEqual(second_payload["order"]["commandId"], first_payload["order"]["commandId"])
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(len(server.ORDERS), 1)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})

    def test_probability_edit_idempotent_replay_skips_unconditional_preview(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-preview-gate",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        with patch.object(server, "preview_unconditional_probability_edit", autospec=True) as preview_mock:
            second_payload, second_status = server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                body,
            )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        preview_mock.assert_not_called()

    def test_account_risk_replay_does_not_double_count_capacity(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-123",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        risk_payload, risk_status = server.route_request("GET", "/v1/accounts/acct_test/risk")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(risk_status, 200)
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(
            risk_payload["account"]["risk"]["capacityIndicators"]["consumed"],
            round(first_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)

    def test_probability_edit_rejects_unconditional_min_asset_violation_without_side_effects(self):
        preview_delta, low_min_asset = seed_low_headroom_account("acct_low")
        with patch.object(server, "create_probability_edit_order", autospec=True) as create_order_mock:
            with patch.object(server, "sync_account_risk_state", autospec=True) as sync_risk_mock:
                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request(
                        "POST",
                        "/v1/markets/m1/orders/probability-edit",
                        {
                            "accountId": "acct_low",
                            "variableId": "eth_price_gt_3000_mar15",
                            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                            "context": [],
                        },
                    )

        assert_min_asset_violation_api_error(
            self,
            ctx.exception,
            account_id="acct_low",
            market_id="m1",
            preview_or_asset_delta=preview_delta,
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(
            server.ACCOUNT_RISK["acct_low"],
            expected_seeded_account_state("acct_low", low_min_asset),
        )
        create_order_mock.assert_not_called()
        sync_risk_mock.assert_not_called()
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})

    def test_probability_edit_accepts_unconditional_edit_at_zero_min_asset_boundary(self):
        preview_delta, exact_headroom = seed_exact_headroom_account("acct_edge")
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_edge",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(payload["order"]["impactScore"], preview_delta["impactScore"])
        self.assertEqual(payload["order"]["impactScore"], exact_headroom)
        self.assertEqual(
            server.EVENTS[payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": "acct_edge",
                "marketId": "m1",
                "beforeMinAsset": exact_headroom,
                "afterMinAsset": 0.0,
            },
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})
        self.assertEqual(len(server.ORDERS), 1)

    def test_probability_edit_rejects_repeated_unconditional_min_asset_violation_without_replay(self):
        preview_delta, low_min_asset = seed_low_headroom_account("acct_low")
        body = {
            "accountId": "acct_low",
            "idempotencyKey": "idem-low-headroom",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as first_ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                body,
            )
        with self.assertRaises(server.ApiError) as second_ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                body,
            )

        assert_min_asset_violation_api_error(
            self,
            first_ctx.exception,
            account_id="acct_low",
            market_id="m1",
            preview_or_asset_delta=preview_delta,
        )
        assert_min_asset_violation_api_error(
            self,
            second_ctx.exception,
            account_id="acct_low",
            market_id="m1",
            preview_or_asset_delta=preview_delta,
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.ACCOUNT_RISK["acct_low"]["minAsset"], low_min_asset)
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})
        self.assertNotIn(
            server.idempotency_scope_key("m1", "acct_low", "idem-low-headroom"),
            server.IDEMPOTENCY_KEYS,
        )

    def test_probability_edit_repeated_min_asset_violation_recomputes_preview(self):
        preview_delta, _ = seed_low_headroom_account("acct_low_replay_contract")
        body = {
            "accountId": "acct_low_replay_contract",
            "idempotencyKey": "idem-low-replay-contract",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        with self.assertRaises(server.ApiError) as first_ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                body,
            )
        with patch.object(
            server,
            "preview_unconditional_probability_edit",
            autospec=True,
            side_effect=server.preview_unconditional_probability_edit,
        ) as preview_mock:
            with self.assertRaises(server.ApiError) as second_ctx:
                server.route_request(
                    "POST",
                    "/v1/markets/m1/orders/probability-edit",
                    body,
                )

        self.assertGreater(preview_mock.call_count, 0)
        assert_min_asset_violation_api_error(
            self,
            first_ctx.exception,
            account_id="acct_low_replay_contract",
            market_id="m1",
            preview_or_asset_delta=preview_delta,
        )
        assert_min_asset_violation_api_error(
            self,
            second_ctx.exception,
            account_id="acct_low_replay_contract",
            market_id="m1",
            preview_or_asset_delta=preview_delta,
        )
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})

    def test_probability_edit_replays_rejected_idempotent_submission(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-resolved",
            "variableId": "fed_rate_cut_mar_2026",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
            "context": [],
        }

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            body,
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 409)
        self.assertEqual(second_status, 409)
        self.assertEqual(second_payload["result"]["status"], "rejected")
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(len(server.TERMINAL_OUTCOMES), 1)
        self.assertEqual(len(server.ORDERS), 0)

    def test_account_risk_rejected_submission_does_not_create_account_state(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            {
                "accountId": "acct_test",
                "idempotencyKey": "idem-resolved",
                "variableId": "fed_rate_cut_mar_2026",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                "context": [],
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_active")
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/accounts/acct_test/risk")

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "account_not_found")

    def test_probability_edit_rejects_idempotency_key_reuse_for_different_payload(self):
        body = {
            "accountId": "acct_test",
            "idempotencyKey": "idem-123",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        conflict_payload, conflict_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                **body,
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
            },
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict_payload["error"]["code"], "idempotency_conflict")
        self.assertEqual(conflict_payload["meta"]["idempotencyKeyEcho"], "idem-123")
        self.assertEqual(conflict_payload["error"]["details"]["existingCommandId"], first_payload["order"]["commandId"])
        self.assertEqual(len(server.ORDERS), 1)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})

    def test_probability_edit_rejects_non_active_market_with_terminal_result(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            {
                "accountId": "acct_test",
                "idempotencyKey": "idem-resolved",
                "variableId": "fed_rate_cut_mar_2026",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                "context": [],
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_active")
        self.assertEqual(payload["result"]["status"], "rejected")
        self.assertEqual(payload["result"]["eventType"], "CommandRejected")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-resolved")
        command = server.COMMANDS[payload["result"]["commandId"]]
        self.assertEqual(command["marketId"], "m3")
        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(event["payload"]["reasonCode"], "market_not_active")
        self.assertEqual(server.MARKETS["m3"]["marginals"], {"yes": 0.0, "no": 1.0})
        self.assertEqual(len(server.ORDERS), 0)

    def test_probability_edit_non_active_market_skips_unconditional_preview(self):
        with patch.object(server, "preview_unconditional_probability_edit", autospec=True) as preview_mock:
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m3/orders/probability-edit",
                {
                    "accountId": "acct_test",
                    "idempotencyKey": "idem-resolved-preview-gate",
                    "variableId": "fed_rate_cut_mar_2026",
                    "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                    "context": [],
                },
            )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_active")
        self.assertEqual(payload["result"]["reasonCode"], "market_not_active")
        preview_mock.assert_not_called()

    def test_market_resolution_accepts_admin_op_and_settles_account_exposure(self):
        account_id = "acct_resolve_settlement"
        first_order, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8),
        )
        conditional_order, conditional_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                **build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.7),
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )
        retained_order, retained_status = server.route_request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            build_unconditional_probability_edit_body(account_id, "m2", "yes", 0.4),
        )
        pre_resolution_risk, pre_resolution_risk_status = server.route_request("GET", f"/v1/accounts/{account_id}/risk")
        pre_resolution_account_state = deepcopy(server.ACCOUNT_RISK[account_id])

        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_admin", "yes", idempotency_key="idem-resolve-m1"),
        )
        post_resolution_risk, post_resolution_risk_status = server.route_request("GET", f"/v1/accounts/{account_id}/risk")

        self.assertEqual(first_status, 201)
        self.assertEqual(conditional_status, 201)
        self.assertEqual(retained_status, 201)
        self.assertEqual(pre_resolution_risk_status, 200)
        self.assertEqual(status, 201)
        self.assertEqual(post_resolution_risk_status, 200)
        self.assertEqual(payload["market"]["id"], "m1")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "yes")
        self.assertEqual(payload["market"]["resolutionProbabilities"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["market"]["marginals"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-resolve-m1")

        command = server.COMMANDS[payload["result"]["commandId"]]
        retained_market = post_resolution_risk["account"]["risk"]["minAssets"]["markets"][0]
        retained_impact_score = retained_order["order"]["impactScore"]
        expected_remaining_min_asset = round(100.0 - retained_impact_score, 6)
        self.assertEqual(command["commandType"], "AdminOp")
        self.assertEqual(command["payload"], expected_market_resolution_payload("m1", "yes"))
        self.assertNotIn("m1", server.CONDITIONAL_MARGINALS)
        self.assertEqual(post_resolution_risk["account"]["id"], account_id)
        self.assertEqual(post_resolution_risk["account"]["risk"]["minAssets"]["overall"], expected_remaining_min_asset)
        self.assertEqual(
            post_resolution_risk["account"]["risk"]["capacityIndicators"],
            {
                "limit": 100.0,
                "available": expected_remaining_min_asset,
                "consumed": retained_impact_score,
                "utilization": round(retained_impact_score / 100.0, 6),
                "status": "healthy",
            },
        )
        self.assertEqual(
            post_resolution_risk["account"]["risk"]["minAssets"]["markets"],
            [
                {
                    "marketId": "m2",
                    "minAsset": expected_remaining_min_asset,
                    "capacityConsumed": retained_impact_score,
                    "utilization": round(retained_impact_score / 100.0, 6),
                    "commandCount": 1,
                    "lastOrderId": retained_order["order"]["id"],
                    "lastCommandId": retained_order["order"]["commandId"],
                    "updatedAt": retained_order["order"]["filledAt"],
                }
            ],
        )
        self.assertEqual(post_resolution_risk["account"]["risk"]["updatedAt"], server.ACCOUNT_RISK[account_id]["updatedAt"])
        self.assertNotEqual(post_resolution_risk["account"]["risk"]["updatedAt"], pre_resolution_risk["account"]["risk"]["updatedAt"])
        self.assertEqual(set(server.ACCOUNT_RISK[account_id]["markets"]), {"m2"})
        self.assertEqual(server.ACCOUNT_RISK[account_id]["markets"]["m2"]["minAsset"], retained_market["minAsset"])
        self.assertNotEqual(server.ACCOUNT_RISK[account_id], pre_resolution_account_state)
        self.assertEqual(
            set(server.ACCOUNT_RISK[account_id]["lmsrState"]["slices"]),
            {
                server.account_lmsr_slice_key("m2", []),
            },
        )

        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(event["eventType"], "CommandAccepted")
        self.assertEqual(event["payload"]["resolution"]["outcomeId"], "yes")
        self.assertEqual(event["payload"]["resolution"]["finalProbabilities"], {"yes": 1.0, "no": 0.0})
        self.assertTrue(event["payload"]["resolution"]["resolvedAt"].endswith("Z"))
        self.assertEqual(
            event["payload"]["effects"]["marginalDelta"],
            [
                {
                    "variableId": "eth_price_gt_3000_mar15",
                    "outcomeId": "yes",
                    "before": 0.8,
                    "after": 1.0,
                },
                {
                    "variableId": "eth_price_gt_3000_mar15",
                    "outcomeId": "no",
                    "before": 0.2,
                    "after": 0.0,
                },
            ],
        )
        self.assertEqual(
            event["payload"]["effects"]["assetDelta"],
            [
                {
                    "accountId": account_id,
                    "marketId": "m1",
                    "beforeMinAsset": pre_resolution_risk["account"]["risk"]["minAssets"]["overall"],
                    "afterMinAsset": expected_remaining_min_asset,
                }
            ],
        )
        self.assertEqual(event["payload"]["pricing"], {"cost": 0.0, "fee": 0.0})
        self.assertEqual(event["payload"]["replayStateHash"], server.market_replay_state_hash("m1"))

    def test_market_resolution_accepts_closed_market(self):
        server.MARKETS["m1"]["status"] = "closed"

        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_admin", "yes", idempotency_key="idem-closed-resolve"),
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["market"]["id"], "m1")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "yes")
        self.assertEqual(payload["market"]["resolutionProbabilities"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["market"]["marginals"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(server.MARKETS["m1"]["status"], "resolved")
        self.assertEqual(server.MARKETS["m1"]["resolution"], "yes")
        self.assertEqual(server.MARKETS["m1"]["resolutionProbabilities"], {"yes": 1.0, "no": 0.0})

    def test_market_resolution_accepts_final_probabilities_body_and_canonicalizes_command_payload(self):
        final_probabilities = {"yes": 0.0, "no": 0.0, "delayed": 1.0}

        payload, status = server.route_request(
            "POST",
            "/v1/markets/m2/resolve",
            build_market_resolution_body("ops_admin", final_probabilities=final_probabilities),
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["market"]["id"], "m2")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "delayed")
        self.assertEqual(payload["market"]["resolutionProbabilities"], final_probabilities)
        self.assertEqual(payload["market"]["marginals"], final_probabilities)
        command = server.COMMANDS[payload["result"]["commandId"]]
        self.assertEqual(command["payload"], expected_market_resolution_payload("m2", "delayed"))
        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(event["payload"]["resolution"]["outcomeId"], "delayed")
        self.assertEqual(event["payload"]["resolution"]["finalProbabilities"], final_probabilities)

    def test_market_resolution_idempotency_replays_across_legacy_and_final_probability_shapes(self):
        legacy_body = build_market_resolution_body("ops_admin", "yes", idempotency_key="idem-resolve-shape")
        final_probabilities_body = build_market_resolution_body(
            "ops_admin",
            final_probabilities={"yes": 1.0, "no": 0.0},
            idempotency_key="idem-resolve-shape",
        )

        first_payload, first_status = server.route_request("POST", "/v1/markets/m1/resolve", legacy_body)
        second_payload, second_status = server.route_request("POST", "/v1/markets/m1/resolve", final_probabilities_body)

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)

    def test_market_resolution_rejects_non_point_mass_final_probabilities(self):
        before_state = snapshot_domain_state()

        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/resolve",
                build_market_resolution_body("ops_admin", final_probabilities={"yes": 0.6, "no": 0.4}),
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_market_resolution")
        self.assertEqual(error.message, "finalProbabilities must encode a point-mass distribution")
        self.assertEqual(
            error.details,
            {
                "field": "finalProbabilities",
                "marketId": "m1",
            },
        )
        assert_domain_state_unchanged(self, before_state)

    def test_market_resolution_rejects_final_probabilities_that_do_not_sum_to_one(self):
        before_state = snapshot_domain_state()

        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/resolve",
                build_market_resolution_body("ops_admin", final_probabilities={"yes": 0.7, "no": 0.31}),
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_market_resolution")
        self.assertEqual(error.message, "finalProbabilities must sum to 1.0")
        self.assertEqual(error.details["field"], "finalProbabilities")
        self.assertEqual(error.details["marketId"], "m1")
        self.assertAlmostEqual(error.details["sum"], 1.01)
        assert_domain_state_unchanged(self, before_state)

    def test_market_resolution_rejects_mismatched_outcome_id_and_final_probabilities(self):
        before_state = snapshot_domain_state()

        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/resolve",
                build_market_resolution_body(
                    "ops_admin",
                    "yes",
                    final_probabilities={"yes": 0.0, "no": 1.0},
                ),
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_market_resolution")
        self.assertEqual(error.message, "outcomeId must match finalProbabilities when both are provided")
        self.assertEqual(
            error.details,
            {
                "field": "outcomeId",
                "marketId": "m1",
                "received": "yes",
                "expected": "no",
            },
        )
        assert_domain_state_unchanged(self, before_state)

    def test_market_resolution_rejects_draft_market_with_terminal_result(self):
        server.MARKETS["m1"]["status"] = "draft"
        baseline_market = deepcopy(server.MARKETS["m1"])

        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_admin", "yes", idempotency_key="idem-draft-resolve"),
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_resolvable")
        self.assertEqual(payload["result"]["status"], "rejected")
        self.assertEqual(payload["result"]["eventType"], "CommandRejected")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-draft-resolve")
        self.assertEqual(
            payload["error"]["details"],
            {
                "marketId": "m1",
                "status": "draft",
                "allowedStatuses": ["active", "closed"],
                "commandId": payload["result"]["commandId"],
            },
        )
        self.assertEqual(server.MARKETS["m1"], baseline_market)
        self.assertEqual(server.ORDERS, {})
        command = server.COMMANDS[payload["result"]["commandId"]]
        self.assertEqual(command["commandType"], "AdminOp")
        self.assertEqual(command["payload"], expected_market_resolution_payload("m1", "yes"))

    def test_market_resolution_requires_account_id(self):
        cases = (
            ("missing", None),
            ("blank", "   "),
        )

        for label, account_id in cases:
            with self.subTest(label=label):
                body = build_market_resolution_body("ops_admin", "yes")
                if account_id is None:
                    del body["accountId"]
                else:
                    body["accountId"] = account_id
                before_state = snapshot_domain_state()

                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request("POST", "/v1/markets/m1/resolve", body)

                error = ctx.exception
                self.assertEqual(error.status, 400)
                self.assertEqual(error.code, "invalid_market_resolution")
                self.assertEqual(error.message, "accountId is required")
                self.assertEqual(error.details["field"], "accountId")
                assert_domain_state_unchanged(self, before_state)

    def test_market_resolution_requires_outcome_id(self):
        cases = (
            ("missing", None),
            ("blank", "   "),
        )

        for label, outcome_id in cases:
            with self.subTest(label=label):
                body = build_market_resolution_body("ops_admin", "yes")
                if outcome_id is None:
                    del body["outcomeId"]
                else:
                    body["outcomeId"] = outcome_id
                before_state = snapshot_domain_state()

                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request("POST", "/v1/markets/m1/resolve", body)

                error = ctx.exception
                self.assertEqual(error.status, 400)
                self.assertEqual(error.code, "invalid_market_resolution")
                self.assertEqual(error.message, "outcomeId is required")
                self.assertEqual(error.details["field"], "outcomeId")
                assert_domain_state_unchanged(self, before_state)

    def test_market_resolution_rejects_malformed_idempotency_key(self):
        invalid_values = ("", "   ", 123)

        for value in invalid_values:
            with self.subTest(value=value):
                body = build_market_resolution_body("ops_admin", "yes")
                body["idempotencyKey"] = value
                before_state = snapshot_domain_state()

                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request("POST", "/v1/markets/m1/resolve", body)

                error = ctx.exception
                self.assertEqual(error.status, 400)
                self.assertEqual(error.code, "invalid_market_resolution")
                self.assertEqual(error.message, "idempotencyKey must be a non-empty string when provided")
                self.assertEqual(error.details["field"], "idempotencyKey")
                assert_domain_state_unchanged(self, before_state)

    def test_create_market_returns_201_with_valid_payload(self):
        payload, status = server.route_request("POST", "/v1/markets", {
            "title": "Test Market",
            "description": "A test market",
            "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
            "expires_at": "2026-12-31T23:59:59Z",
        })
        self.assertEqual(status, 201)
        self.assertIn("market", payload)
        m = payload["market"]
        self.assertEqual(m["title"], "Test Market")
        self.assertEqual(m["status"], "active")
        self.assertEqual(len(m["outcomes"]), 2)
        self.assertAlmostEqual(m["marginals"]["yes"], 0.5, places=4)
        self.assertAlmostEqual(m["marginals"]["no"], 0.5, places=4)
        server.MARKETS.pop(m["id"], None)

    def test_create_market_rejects_missing_title(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", "/v1/markets", {
                "outcomes": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
                "expires_at": "2026-12-31T23:59:59Z",
            })
        self.assertEqual(ctx.exception.status, 400)

    def test_event_formula_normalizes_literals_and_preserves_clause_order(self):
        normalized = server.normalize_event_formula(
            [
                [
                    {"variableId": " fed_rate_cut_mar_2026 ", "outcomeId": " no "},
                    {"variableId": "btc_etf_approval_week", "outcomeId": " delayed ", "negated": True},
                ],
                [
                    {"variableId": " eth_price_gt_3000_mar15 ", "outcomeId": " yes "},
                ],
            ]
        )

        self.assertEqual(
            normalized,
            [
                [
                    {"variableId": "btc_etf_approval_week", "outcomeId": "delayed", "negated": True},
                    {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no", "negated": False},
                ],
                [
                    {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes", "negated": False},
                ],
            ],
        )

    def test_event_formula_rejects_duplicate_literals_after_normalization(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_event_formula(
                [
                    [
                        {"variableId": " eth_price_gt_3000_mar15 ", "outcomeId": " yes "},
                        {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes", "negated": False},
                    ]
                ]
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][1]")
        self.assertEqual(error.details["variableId"], "eth_price_gt_3000_mar15")
        self.assertEqual(error.details["outcomeId"], "yes")
        self.assertFalse(error.details["negated"])

    def test_event_formula_rejects_unknown_outcome_for_variable(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_event_formula(
                [
                    [
                        {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "delayed"},
                    ]
                ]
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0].outcomeId")
        self.assertEqual(error.details["variableId"], "eth_price_gt_3000_mar15")
        self.assertEqual(error.details["received"], "delayed")

    def test_event_formula_rejects_non_boolean_negated(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_event_formula(
                [
                    [
                        {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes", "negated": "true"},
                    ]
                ]
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0].negated")
        self.assertEqual(error.details["received"], "true")

    def test_event_formula_rejects_formula_with_too_many_clauses(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_event_formula(
                [
                    [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
                    for _ in range(server.MAX_EVENT_FORMULA_CLAUSES + 1)
                ]
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula")
        self.assertEqual(error.details["maximum"], server.MAX_EVENT_FORMULA_CLAUSES)
        self.assertEqual(error.details["received"], server.MAX_EVENT_FORMULA_CLAUSES + 1)

    def test_event_formula_rejects_unknown_variable_and_missing_fields(self):
        cases = (
            (
                "unknown variable",
                [[{"variableId": "missing_variable", "outcomeId": "yes"}]],
                "formula[0][0].variableId",
                {"received": "missing_variable"},
            ),
            (
                "missing variableId",
                [[{"outcomeId": "yes"}]],
                "formula[0][0].variableId",
                {},
            ),
            (
                "missing outcomeId",
                [[{"variableId": "eth_price_gt_3000_mar15"}]],
                "formula[0][0].outcomeId",
                {},
            ),
        )

        for label, formula, field, expected_details in cases:
            with self.subTest(label=label):
                with self.assertRaises(server.ApiError) as ctx:
                    server.normalize_event_formula(formula)

                error = ctx.exception
                self.assertEqual(error.status, 400)
                self.assertEqual(error.code, "invalid_event_formula")
                self.assertEqual(error.details["field"], field)
                for detail_key, detail_value in expected_details.items():
                    self.assertEqual(error.details[detail_key], detail_value)

    def test_event_formula_rejects_literals_with_unexpected_fields(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.normalize_event_formula(
                [
                    [
                        {
                            "variableId": "eth_price_gt_3000_mar15",
                            "outcomeId": "yes",
                            "negated": False,
                            "kind": "legacy",
                        }
                    ]
                ]
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0]")
        self.assertEqual(error.details["unexpected"], ["kind"])
        self.assertEqual(error.details["allowed"], sorted(server.formula_schema.EVENT_FORMULA_LITERAL_FIELDS))

    def test_event_formula_rejects_empty_inputs_and_clause_literal_cap(self):
        with self.subTest("empty formula"):
            with self.assertRaises(server.ApiError) as ctx:
                server.normalize_event_formula([])

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_formula")
            self.assertEqual(error.details["field"], "formula")

        with self.subTest("empty clause"):
            with self.assertRaises(server.ApiError) as ctx:
                server.normalize_event_formula([[]])

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_formula")
            self.assertEqual(error.details["field"], "formula[0]")

        with self.subTest("too many literals"):
            with self.assertRaises(server.ApiError) as ctx:
                server.normalize_event_formula(
                    [
                        [
                            {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}
                            for _ in range(server.MAX_EVENT_FORMULA_CLAUSE_LITERALS + 1)
                        ]
                    ]
                )

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_formula")
            self.assertEqual(error.details["field"], "formula[0]")
            self.assertEqual(error.details["maximum"], server.MAX_EVENT_FORMULA_CLAUSE_LITERALS)
            self.assertEqual(error.details["received"], server.MAX_EVENT_FORMULA_CLAUSE_LITERALS + 1)

    def test_event_formula_normalization_is_side_effect_free(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_formula",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")

        before_markets = deepcopy(server.MARKETS)
        before_conditionals = deepcopy(server.CONDITIONAL_MARGINALS)
        before_orders = deepcopy(server.ORDERS)
        before_commands = deepcopy(server.COMMANDS)
        before_events = deepcopy(server.EVENTS)
        before_terminal_outcomes = deepcopy(server.TERMINAL_OUTCOMES)
        before_risk = deepcopy(server.ACCOUNT_RISK)

        normalized = server.normalize_event_formula(
            [
                [
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
                    {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no", "negated": True},
                ]
            ]
        )

        self.assertEqual(
            normalized,
            [
                [
                    {"variableId": "btc_etf_approval_week", "outcomeId": "yes", "negated": False},
                    {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no", "negated": True},
                ]
            ],
        )
        self.assertEqual(server.MARKETS, before_markets)
        self.assertEqual(server.CONDITIONAL_MARGINALS, before_conditionals)
        self.assertEqual(server.ORDERS, before_orders)
        self.assertEqual(server.COMMANDS, before_commands)
        self.assertEqual(server.EVENTS, before_events)
        self.assertEqual(server.TERMINAL_OUTCOMES, before_terminal_outcomes)
        self.assertEqual(server.ACCOUNT_RISK, before_risk)


class BayesMarketEventTradeTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def test_event_trade_accepts_atomic_literal_without_mutating_market_or_risk_state(self):
        payload, status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body("acct_event_trade", "m1", "yes"),
        )
        stats_payload, stats_status = server.route_request("GET", "/v1/markets/m1/engine-stats")

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["type"], "EventTrade")
        self.assertEqual(payload["order"]["marketId"], "m1")
        self.assertEqual(payload["order"]["accountId"], "acct_event_trade")
        self.assertEqual(payload["order"]["status"], "filled")
        self.assertEqual(payload["order"]["payload"]["formula"], [[{"variableId": "m1", "outcomeId": "yes", "negated": False}]])
        self.assertEqual(payload["order"]["side"], "buy")
        self.assertEqual(payload["order"]["size"], 12.5)
        self.assertEqual(payload["order"]["price"], 0.65)
        self.assertEqual(payload["order"]["notional"], 8.125)
        self.assertEqual(payload["result"]["status"], "accepted")
        event = server.EVENTS[payload["result"]["eventId"]]
        self.assertEqual(event["payload"]["effects"], {"marginalDelta": [], "assetDelta": []})
        self.assertEqual(event["payload"]["pricing"], {"cost": 8.125, "fee": 0.0, "unitPrice": 0.65})
        self.assertEqual(
            event["payload"]["trade"],
            {
                "marketId": "m1",
                "outcomeId": "yes",
                "side": "buy",
                "size": 12.5,
                "price": 0.65,
                "notional": 8.125,
            },
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ACCOUNT_RISK, {})
        self.assertEqual(stats_status, 200)
        self.assertEqual(stats_payload["diagnostics"]["request_count"], 1)
        self.assertEqual(stats_payload["diagnostics"]["error_count"], 0)
        self.assertEqual(stats_payload["diagnostics"]["inference"]["count"], 1)
        self.assertIsNone(stats_payload["engine"]["compile_id"])
        self.assertIsNone(stats_payload["engine"]["compile_type"])
        self.assertIsNone(stats_payload["engine"]["source_state_hash"])
        self.assertNotIn("compile_time_ms", stats_payload["diagnostics"])

    def test_event_trade_acceptance_appends_after_existing_probability_edit_event(self):
        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body("acct_event_chain_setup", "m1", "yes", 0.8),
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            build_event_trade_body("acct_event_chain_trade", "m1", "yes"),
        )
        events_payload, events_status = server.route_request("GET", "/v1/markets/m1/events")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(events_status, 200)
        self.assertEqual(
            [event["eventId"] for event in events_payload["events"]],
            [first_payload["result"]["eventId"], second_payload["result"]["eventId"]],
        )
        self.assertEqual([event["seq"] for event in events_payload["events"]], [1, 2])
        self.assertEqual(events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(
            events_payload["events"][1]["prevEventHash"],
            events_payload["events"][0]["eventHash"],
        )
        self.assertEqual(
            events_payload["events"][1]["payload"]["trade"],
            {
                "marketId": "m1",
                "outcomeId": "yes",
                "side": "buy",
                "size": second_payload["order"]["size"],
                "price": second_payload["order"]["price"],
                "notional": second_payload["order"]["notional"],
            },
        )
        self.assertEqual(
            events_payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 2,
                "headHash": events_payload["events"][1]["eventHash"],
            },
        )

    def test_event_trade_prices_via_query_backend_adapter_with_internal_variable_id(self):
        class StubQueryBackend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, bool]] = []

            def query_atomic_event(
                self,
                compile_result: object,
                *,
                variable_id: str,
                outcome_id: str,
                negated: bool = False,
            ) -> object:
                self.calls.append((variable_id, outcome_id, negated))
                return type("AtomicResult", (), {"probability": 0.42})()

        original_backend = server.CURRENT_MODEL_QUERY_BACKEND
        stub_backend = StubQueryBackend()
        server.CURRENT_MODEL_QUERY_BACKEND = stub_backend

        try:
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m1/orders/event-trade",
                build_event_trade_body("acct_event_trade_adapter", "m1", "yes"),
            )
        finally:
            server.CURRENT_MODEL_QUERY_BACKEND = original_backend

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["price"], 0.42)
        self.assertEqual(payload["order"]["notional"], 5.25)
        self.assertEqual(
            stub_backend.calls,
            [(server.MARKETS["m1"]["variableId"], "yes", False)],
        )

    def test_event_trade_returns_501_for_multi_literal_clause(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/event-trade",
                {
                    "accountId": "acct_event_trade",
                    "formula": [
                        [
                            {"variableId": "m1", "outcomeId": "yes", "negated": False},
                            {"variableId": "m2", "outcomeId": "yes", "negated": False},
                        ]
                    ],
                    "size": 12.5,
                    "side": "buy",
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 501)
        self.assertEqual(error.code, "event_trade_inference_unavailable")

    def test_event_trade_returns_501_for_multi_clause_formula(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/event-trade",
                {
                    "accountId": "acct_event_trade",
                    "formula": [
                        [{"variableId": "m1", "outcomeId": "yes", "negated": False}],
                        [{"variableId": "m2", "outcomeId": "yes", "negated": False}],
                    ],
                    "size": 12.5,
                    "side": "buy",
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 501)
        self.assertEqual(error.code, "event_trade_inference_unavailable")

    def test_event_trade_returns_501_for_negated_literal(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/event-trade",
                {
                    "accountId": "acct_event_trade",
                    "formula": [[{"variableId": "m1", "outcomeId": "yes", "negated": True}]],
                    "size": 12.5,
                    "side": "buy",
                },
            )

        error = ctx.exception
        self.assertEqual(error.status, 501)
        self.assertEqual(error.code, "event_trade_inference_unavailable")

    def test_event_trade_rejects_market_literal_mismatch_and_internal_variable_ids(self):
        with self.subTest("market mismatch"):
            with self.assertRaises(server.ApiError) as ctx:
                server.route_request(
                    "POST",
                    "/v1/markets/m1/orders/event-trade",
                    build_event_trade_body("acct_event_trade", "m2", "yes"),
                )

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_trade")
            self.assertEqual(error.details["field"], "formula[0][0].variableId")
            self.assertEqual(error.details["expected"], "m1")
            self.assertEqual(error.details["received"], "m2")

        with self.subTest("internal variable id is rejected"):
            with self.assertRaises(server.ApiError) as ctx:
                server.route_request(
                    "POST",
                    "/v1/markets/m1/orders/event-trade",
                    {
                        "accountId": "acct_event_trade",
                        "formula": [[{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes", "negated": False}]],
                        "size": 12.5,
                        "side": "buy",
                    },
                )

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_formula")
            self.assertEqual(error.details["field"], "formula[0][0].variableId")
            self.assertEqual(error.details["received"], "eth_price_gt_3000_mar15")

    def test_event_trade_rejects_outcome_not_in_target_market(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/m1/orders/event-trade",
                build_event_trade_body("acct_event_trade", "m1", "delayed"),
            )

        error = ctx.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.code, "invalid_event_formula")
        self.assertEqual(error.details["field"], "formula[0][0].outcomeId")

    def test_event_trade_requires_known_market(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request(
                "POST",
                "/v1/markets/missing/orders/event-trade",
                build_event_trade_body("acct_event_trade", "missing", "yes"),
            )

        error = ctx.exception
        self.assertEqual(error.status, 404)
        self.assertEqual(error.code, "market_not_found")
        self.assertEqual(error.details["market_id"], "missing")

    def test_event_trade_route_is_method_not_allowed_for_get(self):
        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("GET", "/v1/markets/m1/orders/event-trade")

        error = ctx.exception
        self.assertEqual(error.status, 405)
        self.assertEqual(error.code, "method_not_allowed")
        self.assertEqual(error.details["method"], "GET")
        self.assertEqual(error.details["path"], "/v1/markets/m1/orders/event-trade")

    def test_event_trade_rejects_invalid_side_and_size(self):
        with self.subTest("invalid side"):
            with self.assertRaises(server.ApiError) as ctx:
                server.route_request(
                    "POST",
                    "/v1/markets/m1/orders/event-trade",
                    build_event_trade_body("acct_event_trade", "m1", "yes", side="hold"),
                )

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_trade")
            self.assertEqual(error.details["field"], "side")

        with self.subTest("invalid size"):
            with self.assertRaises(server.ApiError) as ctx:
                server.route_request(
                    "POST",
                    "/v1/markets/m1/orders/event-trade",
                    build_event_trade_body("acct_event_trade", "m1", "yes", size=0.0),
                )

            error = ctx.exception
            self.assertEqual(error.status, 400)
            self.assertEqual(error.code, "invalid_event_trade")
            self.assertEqual(error.details["field"], "size")

    def test_event_trade_replays_idempotent_submission(self):
        body = build_event_trade_body(
            "acct_event_trade",
            "m1",
            "yes",
            idempotency_key="idem-event-trade",
        )

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            body,
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m1/orders/event-trade",
            body,
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["order"]["id"], first_payload["order"]["id"])
        self.assertEqual(second_payload["order"]["commandId"], first_payload["order"]["commandId"])
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ACCOUNT_RISK, {})
        self.assertEqual(len(server.ORDERS), 1)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)

    def test_event_trade_rejection_appends_once_and_replays_without_double_append(self):
        body = build_event_trade_body(
            "acct_event_trade_reject",
            "m3",
            "yes",
            idempotency_key="idem-event-trade-reject",
        )

        first_payload, first_status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/event-trade",
            body,
        )
        second_payload, second_status = server.route_request(
            "POST",
            "/v1/markets/m3/orders/event-trade",
            body,
        )
        events_payload, events_status = server.route_request("GET", "/v1/markets/m3/events")

        self.assertEqual(first_status, 409)
        self.assertEqual(second_status, 409)
        self.assertEqual(events_status, 200)
        self.assertEqual(first_payload["error"]["code"], "market_not_active")
        self.assertEqual(first_payload["error"]["details"]["marketId"], "m3")
        self.assertEqual(first_payload["result"]["status"], "rejected")
        self.assertEqual(first_payload["result"]["eventType"], "CommandRejected")
        self.assertEqual(first_payload["result"]["reasonCode"], "market_not_active")
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)

        rejection_event = server.EVENTS[first_payload["result"]["eventId"]]
        self.assertEqual(rejection_event["seq"], 1)
        self.assertEqual(rejection_event["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(
            rejection_event["payload"],
            {
                "reasonCode": "market_not_active",
                "reason": "EventTrade is only allowed for active markets",
                "retryHint": "submit against an active market",
            },
        )
        self.assertEqual(events_payload["events"], [rejection_event])
        self.assertEqual(
            events_payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 1,
                "headHash": rejection_event["eventHash"],
            },
        )


class BayesMarketApiPropertyTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def test_unconditional_probability_edit_property_accepts_zero_or_positive_headroom(self):
        rng = random.Random(585)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(48):
            server.reset_state()
            market_id = rng.choice(active_market_ids)
            market = server.MARKETS[market_id]
            outcome_id = rng.choice([outcome["id"] for outcome in market["outcomes"]])
            probability = rng.choice(
                [candidate for candidate in PROPERTY_PROBABILITIES if candidate != market["marginals"][outcome_id]]
            )
            account_id = f"acct_property_accept_{case_index}"
            body = build_unconditional_probability_edit_body(account_id, market_id, outcome_id, probability)
            normalized_payload = server.normalize_probability_edit_payload(market_id, body)
            impact_score = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)["assetDelta"][
                "impactScore"
            ]
            starting_min_asset = server.round_risk_value(impact_score + (case_index % 4) * 0.25)
            seed_account_min_asset(account_id, starting_min_asset)
            seeded_preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)

            payload, status = server.route_request(
                "POST",
                f"/v1/markets/{market_id}/orders/probability-edit",
                body,
            )

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                outcome_id=outcome_id,
                probability=probability,
                impact_score=impact_score,
            ):
                self.assertEqual(status, 201)
                self.assertEqual(payload["result"]["status"], "accepted")
                self.assertGreaterEqual(payload["order"]["impactScore"], 0.0)
                self.assertEqual(payload["order"]["impactScore"], impact_score)
                self.assertEqual(
                    payload["order"]["newMarginals"][outcome_id],
                    normalized_payload["target"]["probability"],
                )
                event_asset_delta = server.EVENTS[payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0]
                self.assertEqual(
                    event_asset_delta["beforeMinAsset"],
                    seeded_preview["assetDelta"]["beforeMinAsset"],
                )
                self.assertEqual(
                    event_asset_delta["afterMinAsset"],
                    seeded_preview["assetDelta"]["afterMinAsset"],
                )
                self.assertGreaterEqual(event_asset_delta["afterMinAsset"], 0.0)
                self.assertGreaterEqual(server.ACCOUNT_RISK[account_id]["minAsset"], 0.0)

    def test_unconditional_probability_edit_property_debits_min_asset_by_preview_impact(self):
        rng = random.Random(589)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(30):
            server.reset_state()
            market_id = rng.choice(active_market_ids)
            market = server.MARKETS[market_id]
            outcome_id = rng.choice([outcome["id"] for outcome in market["outcomes"]])
            probability = pick_probability_distinct_from_current(market_id, outcome_id, rng)
            account_id = f"acct_property_debit_consistency_{case_index}"
            body = build_unconditional_probability_edit_body(account_id, market_id, outcome_id, probability)
            normalized_payload = server.normalize_probability_edit_payload(market_id, body)
            preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)

            payload, status = server.route_request(
                "POST",
                f"/v1/markets/{market_id}/orders/probability-edit",
                body,
            )
            risk_payload, risk_status = server.route_request("GET", f"/v1/accounts/{account_id}/risk")

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                outcome_id=outcome_id,
                probability=probability,
                impact_score=preview["assetDelta"]["impactScore"],
            ):
                self.assertEqual(status, 201)
                self.assertEqual(risk_status, 200)
                self.assertEqual(payload["result"]["status"], "accepted")

                event_asset_delta = server.EVENTS[payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0]
                before_min_asset = event_asset_delta["beforeMinAsset"]
                impact_score = payload["order"]["impactScore"]
                after_min_asset = event_asset_delta["afterMinAsset"]
                markets = risk_payload["account"]["risk"]["minAssets"]["markets"]

                self.assertEqual(impact_score, preview["assetDelta"]["impactScore"])
                self.assertEqual(before_min_asset, preview["assetDelta"]["beforeMinAsset"])
                self.assertEqual(after_min_asset, preview["assetDelta"]["afterMinAsset"])
                self.assertEqual(server.round_risk_value(before_min_asset - impact_score), after_min_asset)
                self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["overall"], after_min_asset)
                self.assertEqual(len(markets), 1)
                self.assertEqual(markets[0]["marketId"], market_id)
                self.assertEqual(markets[0]["minAsset"], after_min_asset)

    def test_unconditional_probability_edit_property_rejects_negative_headroom_without_side_effects(self):
        rng = random.Random(586)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(48):
            server.reset_state()
            market_id = rng.choice(active_market_ids)
            market = server.MARKETS[market_id]
            outcome_id = rng.choice([outcome["id"] for outcome in market["outcomes"]])
            probability = rng.choice(
                [candidate for candidate in PROPERTY_PROBABILITIES if candidate != market["marginals"][outcome_id]]
            )
            account_id = f"acct_property_reject_{case_index}"
            body = build_unconditional_probability_edit_body(account_id, market_id, outcome_id, probability)
            normalized_payload = server.normalize_probability_edit_payload(market_id, body)
            impact_score = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)["assetDelta"][
                "impactScore"
            ]
            shortfall = server.round_risk_value(impact_score / 2)
            starting_min_asset = server.round_risk_value(impact_score - shortfall)
            baseline_market = deepcopy(server.MARKETS[market_id]["marginals"])
            baseline_account = seed_account_min_asset(account_id, starting_min_asset)
            seeded_preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
            with self.assertRaises(server.ApiError) as ctx:
                server.route_request(
                    "POST",
                    f"/v1/markets/{market_id}/orders/probability-edit",
                    body,
                )

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                outcome_id=outcome_id,
                probability=probability,
                impact_score=impact_score,
            ):
                assert_min_asset_violation_api_error(
                    self,
                    ctx.exception,
                    account_id=account_id,
                    market_id=market_id,
                    preview_or_asset_delta=seeded_preview,
                )
                self.assertLess(ctx.exception.details["afterMinAsset"], 0.0)
                self.assertEqual(server.MARKETS[market_id]["marginals"], baseline_market)
                self.assertEqual(server.ACCOUNT_RISK[account_id], baseline_account)
                self.assertEqual(server.ORDERS, {})
                self.assertEqual(server.COMMANDS, {})
                self.assertEqual(server.EVENTS, {})
                self.assertEqual(server.TERMINAL_OUTCOMES, {})

    def test_conditional_probability_edit_property_bypasses_unconditional_guard_after_exact_zero_acceptance(self):
        rng = random.Random(587)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(48):
            server.reset_state()
            conditional_market_id = rng.choice(active_market_ids)
            setup_market_id = next(market_id for market_id in active_market_ids if market_id != conditional_market_id)

            setup_outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[setup_market_id]["outcomes"]])
            setup_probability = pick_probability_distinct_from_current(setup_market_id, setup_outcome_id, rng)
            account_id = f"acct_property_conditional_bypass_{case_index}"
            setup_body = build_unconditional_probability_edit_body(
                account_id,
                setup_market_id,
                setup_outcome_id,
                setup_probability,
            )
            setup_normalized = server.normalize_probability_edit_payload(setup_market_id, setup_body)
            setup_preview = server.preview_unconditional_probability_edit(setup_market_id, setup_normalized, account_id)
            seed_account_min_asset(account_id, setup_preview["impactScore"])

            setup_payload, setup_status = server.route_request(
                "POST",
                f"/v1/markets/{setup_market_id}/orders/probability-edit",
                setup_body,
            )
            setup_risk_payload, setup_risk_status = server.route_request("GET", f"/v1/accounts/{account_id}/risk")

            conditional_outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[conditional_market_id]["outcomes"]])
            conditional_probability = pick_probability_distinct_from_current(
                conditional_market_id,
                conditional_outcome_id,
                rng,
            )
            counterfactual_body = build_unconditional_probability_edit_body(
                account_id,
                conditional_market_id,
                conditional_outcome_id,
                conditional_probability,
            )
            counterfactual_normalized = server.normalize_probability_edit_payload(conditional_market_id, counterfactual_body)
            counterfactual_preview = server.preview_unconditional_probability_edit(
                conditional_market_id,
                counterfactual_normalized,
                account_id,
            )
            context_assignment = {
                "variableId": server.MARKETS[setup_market_id]["variableId"],
                "outcomeId": rng.choice([outcome["id"] for outcome in server.MARKETS[setup_market_id]["outcomes"]]),
            }
            conditional_body = {
                **counterfactual_body,
                "context": [context_assignment],
            }
            expected_context = [context_assignment]
            baseline_conditional_market = deepcopy(server.MARKETS[conditional_market_id]["marginals"])

            conditional_payload, conditional_status = server.route_request(
                "POST",
                f"/v1/markets/{conditional_market_id}/orders/probability-edit",
                conditional_body,
            )
            conditional_context_key = server.context_state_key(conditional_payload["order"]["payload"]["context"])

            with self.subTest(
                case_index=case_index,
                setup_market_id=setup_market_id,
                conditional_market_id=conditional_market_id,
                conditional_outcome_id=conditional_outcome_id,
                conditional_probability=conditional_probability,
            ):
                self.assertEqual(setup_status, 201)
                self.assertEqual(setup_payload["result"]["status"], "accepted")
                self.assertEqual(setup_risk_status, 200)
                self.assertEqual(
                    server.EVENTS[setup_payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
                    0.0,
                )
                self.assertEqual(setup_risk_payload["account"]["risk"]["minAssets"]["overall"], 0.0)
                self.assertGreater(counterfactual_preview["assetDelta"]["impactScore"], 0.0)
                self.assertEqual(counterfactual_preview["assetDelta"]["beforeMinAsset"], 0.0)
                self.assertLess(counterfactual_preview["assetDelta"]["afterMinAsset"], 0.0)
                self.assertEqual(conditional_status, 201)
                self.assertEqual(conditional_payload["result"]["status"], "accepted")
                self.assertEqual(conditional_payload["order"]["payload"]["context"], expected_context)
                self.assertEqual(server.MARKETS[conditional_market_id]["marginals"], baseline_conditional_market)
                self.assertEqual(
                    server.CONDITIONAL_MARGINALS[conditional_market_id][conditional_context_key],
                    conditional_payload["order"]["newMarginals"],
                )

    def test_unconditional_probability_edit_property_rejects_positive_follow_up_after_exact_zero_acceptance(self):
        rng = random.Random(588)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(48):
            server.reset_state()
            market_id = rng.choice(active_market_ids)
            first_outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[market_id]["outcomes"]])
            first_probability = pick_probability_distinct_from_current(market_id, first_outcome_id, rng)
            account_id = f"acct_property_strict_zero_{case_index}"
            first_body = build_unconditional_probability_edit_body(account_id, market_id, first_outcome_id, first_probability)
            first_normalized = server.normalize_probability_edit_payload(market_id, first_body)
            first_preview = server.preview_unconditional_probability_edit(market_id, first_normalized, account_id)
            seed_account_min_asset(account_id, first_preview["impactScore"])

            first_payload, first_status = server.route_request(
                "POST",
                f"/v1/markets/{market_id}/orders/probability-edit",
                first_body,
            )
            first_risk_payload, first_risk_status = server.route_request("GET", f"/v1/accounts/{account_id}/risk")
            post_first_market = deepcopy(server.MARKETS[market_id]["marginals"])
            post_first_account = deepcopy(server.ACCOUNT_RISK[account_id])
            post_first_command_count = len(server.COMMANDS)
            post_first_event_count = len(server.EVENTS)
            post_first_terminal_count = len(server.TERMINAL_OUTCOMES)

            follow_up_outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[market_id]["outcomes"]])
            follow_up_probability = pick_probability_distinct_from_current(market_id, follow_up_outcome_id, rng)
            follow_up_body = build_unconditional_probability_edit_body(
                account_id,
                market_id,
                follow_up_outcome_id,
                follow_up_probability,
            )
            follow_up_normalized = server.normalize_probability_edit_payload(market_id, follow_up_body)
            follow_up_preview = server.preview_unconditional_probability_edit(market_id, follow_up_normalized, account_id)

            with self.assertRaises(server.ApiError) as follow_up_ctx:
                server.route_request(
                    "POST",
                    f"/v1/markets/{market_id}/orders/probability-edit",
                    follow_up_body,
                )

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                first_outcome_id=first_outcome_id,
                follow_up_outcome_id=follow_up_outcome_id,
                follow_up_probability=follow_up_probability,
            ):
                self.assertEqual(first_status, 201)
                self.assertEqual(first_payload["result"]["status"], "accepted")
                self.assertEqual(first_risk_status, 200)
                self.assertEqual(
                    server.EVENTS[first_payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
                    0.0,
                )
                self.assertEqual(first_risk_payload["account"]["risk"]["minAssets"]["overall"], 0.0)
                self.assertGreater(follow_up_preview["assetDelta"]["impactScore"], 0.0)
                self.assertEqual(follow_up_preview["assetDelta"]["beforeMinAsset"], 0.0)
                self.assertLess(follow_up_preview["assetDelta"]["afterMinAsset"], 0.0)
                assert_min_asset_violation_api_error(
                    self,
                    follow_up_ctx.exception,
                    account_id=account_id,
                    market_id=market_id,
                    preview_or_asset_delta=follow_up_preview,
                )
                self.assertEqual(server.MARKETS[market_id]["marginals"], post_first_market)
                self.assertEqual(server.ACCOUNT_RISK[account_id], post_first_account)
                self.assertEqual(len(server.ORDERS), 1)
                self.assertEqual(len(server.COMMANDS), post_first_command_count)
                self.assertEqual(len(server.EVENTS), post_first_event_count)
                self.assertEqual(len(server.TERMINAL_OUTCOMES), post_first_terminal_count)

    def test_unconditional_probability_edit_property_preserves_valid_marginal_distribution(self):
        rng = random.Random(584001)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")
        accepted_count = 0
        rejected_count = 0

        for case_index in range(40):
            market_id = rng.choice(active_market_ids)
            market = server.MARKETS[market_id]
            outcome_id = rng.choice([outcome["id"] for outcome in market["outcomes"]])
            probability = pick_probability_distinct_from_current(market_id, outcome_id, rng)
            account_id = f"acct_property_distribution_{case_index}"
            body = build_unconditional_probability_edit_body(account_id, market_id, outcome_id, probability)
            baseline_marginals = deepcopy(server.MARKETS[market_id]["marginals"])
            should_reject = case_index % 2 == 1
            baseline_command_count = len(server.COMMANDS)
            baseline_event_count = len(server.EVENTS)
            baseline_terminal_count = len(server.TERMINAL_OUTCOMES)
            payload = None
            status = None
            preview = None
            rejection_error = None

            if should_reject:
                normalized_payload = server.normalize_probability_edit_payload(market_id, body)
                preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
                seed_account_min_asset(account_id, server.round_risk_value(preview["impactScore"] * 0.5))
                preview = server.preview_unconditional_probability_edit(market_id, normalized_payload, account_id)
                with self.assertRaises(server.ApiError) as ctx:
                    server.route_request(
                        "POST",
                        f"/v1/markets/{market_id}/orders/probability-edit",
                        body,
                    )
                rejection_error = ctx.exception
            else:
                payload, status = server.route_request(
                    "POST",
                    f"/v1/markets/{market_id}/orders/probability-edit",
                    body,
                )
            current_marginals = deepcopy(server.MARKETS[market_id]["marginals"])

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                outcome_id=outcome_id,
                probability=probability,
                should_reject=should_reject,
            ):
                if should_reject:
                    rejected_count += 1
                    assert_min_asset_violation_api_error(
                        self,
                        rejection_error,
                        account_id=account_id,
                        market_id=market_id,
                        preview_or_asset_delta=preview,
                    )
                    self.assertEqual(current_marginals, baseline_marginals)
                    self.assertEqual(len(server.COMMANDS), baseline_command_count)
                    self.assertEqual(len(server.EVENTS), baseline_event_count)
                    self.assertEqual(len(server.TERMINAL_OUTCOMES), baseline_terminal_count)
                else:
                    accepted_count += 1
                    self.assertEqual(status, 201)
                    self.assertEqual(payload["result"]["status"], "accepted")
                    self.assertEqual(current_marginals, payload["order"]["newMarginals"])

                self.assertAlmostEqual(sum(current_marginals.values()), 1.0, delta=1e-9)
                for marginal in current_marginals.values():
                    self.assertGreaterEqual(marginal, 0.0)
                    self.assertLessEqual(marginal, 1.0)

        self.assertGreater(accepted_count, 0)
        self.assertGreater(rejected_count, 0)

    def test_unconditional_probability_edit_property_accepted_order_impact_matches_kl_divergence(self):
        rng = random.Random(584002)
        active_market_ids = tuple(market_id for market_id, market in server.MARKETS.items() if market["status"] == "active")

        for case_index in range(30):
            server.reset_state()
            market_id = rng.choice(active_market_ids)
            outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[market_id]["outcomes"]])
            probability = pick_probability_distinct_from_current(market_id, outcome_id, rng)
            account_id = f"acct_property_impact_{case_index}"
            body = build_unconditional_probability_edit_body(account_id, market_id, outcome_id, probability)
            before_marginals = deepcopy(server.MARKETS[market_id]["marginals"])

            payload, status = server.route_request(
                "POST",
                f"/v1/markets/{market_id}/orders/probability-edit",
                body,
            )
            after_marginals = deepcopy(server.MARKETS[market_id]["marginals"])
            expected_impact = server.kl_divergence(before_marginals, after_marginals)

            with self.subTest(
                case_index=case_index,
                market_id=market_id,
                outcome_id=outcome_id,
                probability=probability,
            ):
                self.assertEqual(status, 201)
                self.assertEqual(payload["result"]["status"], "accepted")
                self.assertEqual(payload["order"]["previousMarginals"], before_marginals)
                self.assertEqual(payload["order"]["newMarginals"], after_marginals)
                self.assertEqual(payload["order"]["impactScore"], expected_impact)


class BayesMarketApiInferenceInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def test_invariant_probability_edit_matches_bruteforce_reference_on_tiny_nets(self):
        rng = random.Random(584007)
        active_market_ids = tuple(
            market_id for market_id, market in server.MARKETS.items() if market["status"] == "active"
        )

        for case_index in range(36):
            server.reset_state()
            reference_joint = build_reference_joint_distribution()
            target_market_id = rng.choice(active_market_ids)
            context = build_random_context(target_market_id, rng)
            baseline_unconditional = brute_force_conditional_marginals(reference_joint, target_market_id, [])
            before_marginals = brute_force_conditional_marginals(reference_joint, target_market_id, context)
            outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[target_market_id]["outcomes"]])
            probability = pick_probability_distinct_from_marginals(before_marginals, outcome_id, rng)
            expected_joint = brute_force_apply_probability_edit(
                reference_joint,
                target_market_id,
                outcome_id,
                probability,
                context,
            )
            expected_marginals = brute_force_conditional_marginals(expected_joint, target_market_id, context)
            body = build_unconditional_probability_edit_body(
                f"acct_invariant_reference_{case_index}",
                target_market_id,
                outcome_id,
                probability,
            )
            body["context"] = deepcopy(context)

            payload, status = server.route_request(
                "POST",
                f"/v1/markets/{target_market_id}/orders/probability-edit",
                body,
            )

            with self.subTest(
                case_index=case_index,
                target_market_id=target_market_id,
                outcome_id=outcome_id,
                probability=probability,
                context=context,
            ):
                self.assertEqual(status, 201)
                self.assertEqual(payload["result"]["status"], "accepted")
                assert_marginals_close(self, payload["order"]["previousMarginals"], before_marginals)
                assert_marginals_close(self, payload["order"]["newMarginals"], expected_marginals)
                self.assertEqual(
                    payload["order"]["impactScore"],
                    server.kl_divergence(payload["order"]["previousMarginals"], payload["order"]["newMarginals"]),
                )

                if context:
                    context_key = server.context_state_key(payload["order"]["payload"]["context"])
                    assert_marginals_close(
                        self,
                        server.CONDITIONAL_MARGINALS[target_market_id][context_key],
                        expected_marginals,
                    )
                    assert_marginals_close(self, server.MARKETS[target_market_id]["marginals"], baseline_unconditional)
                else:
                    assert_marginals_close(self, server.MARKETS[target_market_id]["marginals"], expected_marginals)

    def test_invariant_repeated_probability_edits_match_bruteforce_reference_on_same_slice(self):
        rng = random.Random(584008)
        scenarios = (
            ("m1", []),
            ("m1", [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}]),
            (
                "m2",
                [
                    {"variableId": "eth_price_gt_3000_mar15", "outcomeId": "no"},
                    {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
                ],
            ),
        )

        for scenario_index, (target_market_id, context) in enumerate(scenarios):
            server.reset_state()
            reference_joint = build_reference_joint_distribution()

            for step_index in range(3):
                before_marginals = brute_force_conditional_marginals(reference_joint, target_market_id, context)
                outcome_id = rng.choice([outcome["id"] for outcome in server.MARKETS[target_market_id]["outcomes"]])
                probability = pick_probability_distinct_from_marginals(before_marginals, outcome_id, rng)
                reference_joint = brute_force_apply_probability_edit(
                    reference_joint,
                    target_market_id,
                    outcome_id,
                    probability,
                    context,
                )
                expected_marginals = brute_force_conditional_marginals(reference_joint, target_market_id, context)
                body = build_unconditional_probability_edit_body(
                    f"acct_invariant_sequence_{scenario_index}_{step_index}",
                    target_market_id,
                    outcome_id,
                    probability,
                )
                body["context"] = deepcopy(context)

                payload, status = server.route_request(
                    "POST",
                    f"/v1/markets/{target_market_id}/orders/probability-edit",
                    body,
                )

                with self.subTest(
                    scenario_index=scenario_index,
                    step_index=step_index,
                    target_market_id=target_market_id,
                    outcome_id=outcome_id,
                    probability=probability,
                    context=context,
                ):
                    self.assertEqual(status, 201)
                    self.assertEqual(payload["result"]["status"], "accepted")
                    assert_marginals_close(self, payload["order"]["previousMarginals"], before_marginals)
                    assert_marginals_close(self, payload["order"]["newMarginals"], expected_marginals)
                    self.assertEqual(
                        payload["order"]["impactScore"],
                        server.kl_divergence(payload["order"]["previousMarginals"], payload["order"]["newMarginals"]),
                    )

                    if context:
                        context_key = server.context_state_key(payload["order"]["payload"]["context"])
                        assert_marginals_close(
                            self,
                            server.CONDITIONAL_MARGINALS[target_market_id][context_key],
                            expected_marginals,
                        )
                    else:
                        assert_marginals_close(self, server.MARKETS[target_market_id]["marginals"], expected_marginals)


class BayesMarketApiMarketInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        server.reset_state()

    def test_invariant_journal_chain_and_seq_monotonic_per_market(self):
        rng = random.Random(584003)
        market_id = "m1"
        market_path = f"/v1/markets/{market_id}/orders/probability-edit"
        event_ids: list[str] = []

        for index in range(12):
            probability = pick_probability_distinct_from_current(market_id, "yes", rng)
            body = build_unconditional_probability_edit_body(
                f"acct_market_chain_{index}",
                market_id,
                "yes",
                probability,
            )

            payload, status = server.route_request("POST", market_path, body)

            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")
            event_ids.append(payload["result"]["eventId"])

        events_payload, events_status = server.route_request("GET", f"/v1/markets/{market_id}/events")

        self.assertEqual(events_status, 200)
        self.assertEqual(len(events_payload["events"]), 12)
        self.assertEqual(events_payload["chain"]["genesisHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(events_payload["events"], [server.EVENTS[event_id] for event_id in event_ids])

        previous_event_hash = server.GENESIS_EVENT_HASH
        for expected_seq, event in enumerate(events_payload["events"], start=1):
            self.assertEqual(event["seq"], expected_seq)
            self.assertEqual(event["prevEventHash"], previous_event_hash)
            previous_event_hash = event["eventHash"]

        final_event = events_payload["events"][-1]
        self.assertEqual(events_payload["chain"]["headSeq"], final_event["seq"])
        self.assertEqual(events_payload["chain"]["headHash"], final_event["eventHash"])
        self.assertEqual(server.MARKET_EVENT_SEQUENCES[market_id], final_event["seq"])
        self.assertEqual(server.LAST_EVENT_HASHES[market_id], final_event["eventHash"])

    def test_invariant_interleaved_markets_keep_independent_journal_heads(self):
        rng = random.Random(584005)
        event_ids_by_market: dict[str, list[str]] = {"m1": [], "m2": []}
        operations = (
            ("m1", "yes"),
            ("m2", "yes"),
            ("m1", "no"),
            ("m2", "delayed"),
            ("m1", "yes"),
            ("m2", "no"),
        )

        for index, (market_id, outcome_id) in enumerate(operations):
            probability = pick_probability_distinct_from_current(market_id, outcome_id, rng)
            body = build_unconditional_probability_edit_body(
                f"acct_market_isolation_{market_id}_{index}",
                market_id,
                outcome_id,
                probability,
            )

            payload, status = server.route_request("POST", f"/v1/markets/{market_id}/orders/probability-edit", body)

            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")
            event_ids_by_market[market_id].append(payload["result"]["eventId"])

        for market_id, event_ids in event_ids_by_market.items():
            with self.subTest(market_id=market_id):
                events_payload, events_status = server.route_request("GET", f"/v1/markets/{market_id}/events")

                self.assertEqual(events_status, 200)
                self.assertEqual(events_payload["events"], [server.EVENTS[event_id] for event_id in event_ids])

                previous_event_hash = server.GENESIS_EVENT_HASH
                for expected_seq, event in enumerate(events_payload["events"], start=1):
                    self.assertEqual(event["seq"], expected_seq)
                    self.assertEqual(event["prevEventHash"], previous_event_hash)
                    previous_event_hash = event["eventHash"]

                final_event = events_payload["events"][-1]
                self.assertEqual(events_payload["chain"]["headSeq"], len(event_ids))
                self.assertEqual(events_payload["chain"]["headHash"], final_event["eventHash"])
                self.assertEqual(server.MARKET_EVENT_SEQUENCES[market_id], len(event_ids))
                self.assertEqual(server.LAST_EVENT_HASHES[market_id], final_event["eventHash"])

    def test_invariant_min_asset_api_error_preserves_market_and_account_state_without_journal_append(self):
        rng = random.Random(584004)
        market_id = "m1"
        market_path = f"/v1/markets/{market_id}/orders/probability-edit"

        setup_probability = pick_probability_distinct_from_current(market_id, "yes", rng)
        setup_body = build_unconditional_probability_edit_body(
            "acct_market_invariant_setup",
            market_id,
            "yes",
            setup_probability,
        )
        setup_payload, setup_status = server.route_request("POST", market_path, setup_body)

        self.assertEqual(setup_status, 201)
        self.assertEqual(setup_payload["result"]["status"], "accepted")

        rejecting_account_id = "acct_market_invariant_reject"
        rejecting_probability = pick_probability_distinct_from_current(market_id, "yes", rng)
        rejecting_body = build_unconditional_probability_edit_body(
            rejecting_account_id,
            market_id,
            "yes",
            rejecting_probability,
        )
        rejecting_normalized = server.normalize_probability_edit_payload(market_id, rejecting_body)
        rejecting_preview = server.preview_unconditional_probability_edit(
            market_id,
            rejecting_normalized,
            rejecting_account_id,
        )
        seeded_min_asset = server.round_risk_value(rejecting_preview["impactScore"] * 0.5)
        baseline_account = seed_account_min_asset(rejecting_account_id, seeded_min_asset)
        rejecting_preview = server.preview_unconditional_probability_edit(
            market_id,
            rejecting_normalized,
            rejecting_account_id,
        )
        baseline_market = deepcopy(server.MARKETS[market_id])
        baseline_event_count = len(server.EVENTS)
        baseline_head_seq = server.MARKET_EVENT_SEQUENCES[market_id]
        baseline_head_hash = server.LAST_EVENT_HASHES[market_id]

        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", market_path, rejecting_body)
        events_payload, events_status = server.route_request("GET", f"/v1/markets/{market_id}/events")

        self.assertEqual(events_status, 200)
        assert_min_asset_violation_api_error(
            self,
            ctx.exception,
            account_id=rejecting_account_id,
            market_id=market_id,
            preview_or_asset_delta=rejecting_preview,
        )
        self.assertEqual(server.MARKETS[market_id], baseline_market)
        self.assertEqual(server.ACCOUNT_RISK[rejecting_account_id], baseline_account)
        self.assertEqual(len(server.EVENTS), baseline_event_count)
        self.assertEqual(server.MARKET_EVENT_SEQUENCES[market_id], baseline_head_seq)
        self.assertEqual(server.LAST_EVENT_HASHES[market_id], baseline_head_hash)
        self.assertEqual(len(events_payload["events"]), baseline_event_count)
        self.assertEqual(events_payload["events"][-1], server.EVENTS[setup_payload["result"]["eventId"]])
        self.assertEqual(events_payload["chain"]["headSeq"], baseline_head_seq)
        self.assertEqual(events_payload["chain"]["headHash"], baseline_head_hash)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.TERMINAL_OUTCOMES), 1)

    def test_invariant_first_market_min_asset_api_error_leaves_journal_empty(self):
        market_id = "m2"
        market_path = f"/v1/markets/{market_id}/orders/probability-edit"
        account_id = "acct_market_empty_journal_reject"
        rejecting_probability = 0.8
        rejecting_body = build_unconditional_probability_edit_body(account_id, market_id, "yes", rejecting_probability)
        rejecting_normalized = server.normalize_probability_edit_payload(market_id, rejecting_body)
        rejecting_preview = server.preview_unconditional_probability_edit(
            market_id,
            rejecting_normalized,
            account_id,
        )
        seeded_min_asset = server.round_risk_value(rejecting_preview["impactScore"] * 0.5)
        baseline_account = seed_account_min_asset(account_id, seeded_min_asset)
        rejecting_preview = server.preview_unconditional_probability_edit(
            market_id,
            rejecting_normalized,
            account_id,
        )
        baseline_market = deepcopy(server.MARKETS[market_id])

        with self.assertRaises(server.ApiError) as ctx:
            server.route_request("POST", market_path, rejecting_body)
        events_payload, events_status = server.route_request("GET", f"/v1/markets/{market_id}/events")

        self.assertEqual(events_status, 200)
        assert_min_asset_violation_api_error(
            self,
            ctx.exception,
            account_id=account_id,
            market_id=market_id,
            preview_or_asset_delta=rejecting_preview,
        )
        self.assertEqual(server.MARKETS[market_id], baseline_market)
        self.assertEqual(server.ACCOUNT_RISK[account_id], baseline_account)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})
        self.assertEqual(events_payload["events"], [])
        self.assertEqual(
            events_payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 0,
                "headHash": server.GENESIS_EVENT_HASH,
            },
        )
        self.assertEqual(server.MARKET_EVENT_SEQUENCES.get(market_id, 0), 0)
        self.assertEqual(server.LAST_EVENT_HASHES.get(market_id, server.GENESIS_EVENT_HASH), server.GENESIS_EVENT_HASH)


    def test_invariant_canonical_json_hash_is_deterministic_and_order_independent(self):
        payload = {
            "marketId": "m1",
            "effects": {
                "assetDelta": [
                    {
                        "accountId": "acct_hash",
                        "marketId": "m1",
                        "beforeMinAsset": 100.0,
                        "afterMinAsset": 99.812345,
                    }
                ],
                "marginalDelta": [
                    {
                        "variableId": "eth_price_gt_3000_mar15",
                        "outcomeId": "yes",
                        "before": 0.65,
                        "after": 0.8,
                    }
                ],
            },
            "pricing": {
                "fee": 0.0,
                "cost": 0.187655,
            },
        }
        reordered_payload = {
            "pricing": {
                "cost": 0.187655,
                "fee": 0.0,
            },
            "effects": {
                "marginalDelta": [
                    {
                        "after": 0.8,
                        "before": 0.65,
                        "outcomeId": "yes",
                        "variableId": "eth_price_gt_3000_mar15",
                    }
                ],
                "assetDelta": [
                    {
                        "afterMinAsset": 99.812345,
                        "beforeMinAsset": 100.0,
                        "marketId": "m1",
                        "accountId": "acct_hash",
                    }
                ],
            },
            "marketId": "m1",
        }
        mutated_payload = deepcopy(payload)
        mutated_payload["pricing"]["cost"] = 0.187656

        first_hash = server.canonical_json_hash(payload)
        repeated_hashes = [server.canonical_json_hash(payload) for _ in range(10)]
        reordered_hash = server.canonical_json_hash(reordered_payload)
        mutated_hash = server.canonical_json_hash(mutated_payload)

        self.assertTrue(first_hash.startswith("sha256:"))
        self.assertEqual(repeated_hashes, [first_hash] * 10)
        self.assertEqual(reordered_hash, first_hash)
        self.assertNotEqual(mutated_hash, first_hash)

    def test_invariant_distinct_event_hashes_command_ids_and_event_ids_across_market_events(self):
        rng = random.Random(584006)
        outcome_ids = [outcome["id"] for outcome in server.MARKETS["m1"]["outcomes"]]
        result_event_ids: list[str] = []
        result_command_ids: list[str] = []

        for case_index in range(10):
            outcome_id = rng.choice(outcome_ids)
            probability = pick_probability_distinct_from_current("m1", outcome_id, rng)
            body = build_unconditional_probability_edit_body(
                f"acct_market_invariant_{case_index}",
                "m1",
                outcome_id,
                probability,
            )
            payload, status = server.route_request(
                "POST",
                "/v1/markets/m1/orders/probability-edit",
                body,
            )

            with self.subTest(
                case_index=case_index,
                account_id=body["accountId"],
                outcome_id=outcome_id,
                probability=probability,
            ):
                self.assertEqual(status, 201)
                self.assertEqual(payload["result"]["status"], "accepted")

            result_event_ids.append(payload["result"]["eventId"])
            result_command_ids.append(payload["result"]["commandId"])

        events_payload, events_status = server.route_request("GET", "/v1/markets/m1/events")
        events = events_payload["events"]

        self.assertEqual(events_status, 200)
        self.assertEqual(len(events), 10)
        self.assertEqual(result_event_ids, [event["eventId"] for event in events])
        self.assertEqual(result_command_ids, [event["commandId"] for event in events])
        self.assertEqual(len({event["eventHash"] for event in events}), 10)
        self.assertEqual(len({event["commandId"] for event in events}), 10)
        self.assertEqual(len({event["eventId"] for event in events}), 10)


class BayesMarketApiConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server.reset_state()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.BayesHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    def setUp(self) -> None:
        server.reset_state()

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = 5,
        headers: dict[str, str] | None = None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        payload = None if body is None else json.dumps(body)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=payload, headers=request_headers)
            response = conn.getresponse()
            response_body = response.read().decode()
        finally:
            conn.close()
        return response.status, json.loads(response_body)

    def probability_edit(self, market_id: str, body: dict, *, timeout: float = 5):
        return self.request(
            "POST",
            f"/v1/markets/{market_id}/orders/probability-edit",
            body,
            timeout=timeout,
        )

    def event_trade(self, market_id: str, body: dict, *, timeout: float = 5):
        return self.request(
            "POST",
            f"/v1/markets/{market_id}/orders/event-trade",
            body,
            timeout=timeout,
        )

    def market_events(self, market_id: str, *, timeout: float = 5):
        return self.request("GET", f"/v1/markets/{market_id}/events", timeout=timeout)

    def account_risk(self, account_id: str, *, timeout: float = 5):
        return self.request("GET", f"/v1/accounts/{account_id}/risk", timeout=timeout)

    def run_concurrent_probability_edits(
        self,
        operations: list[tuple[str, dict[str, object]]],
        *,
        hash_delay: float = 0.0,
        timeout: float = 5,
    ) -> list[tuple[int, dict[str, object]]]:
        return self.run_concurrent_requests(
            self.probability_edit,
            operations,
            hash_delay=hash_delay,
            timeout=timeout,
        )

    def run_concurrent_event_trades(
        self,
        operations: list[tuple[str, dict[str, object]]],
        *,
        hash_delay: float = 0.0,
        timeout: float = 5,
    ) -> list[tuple[int, dict[str, object]]]:
        return self.run_concurrent_requests(
            self.event_trade,
            operations,
            hash_delay=hash_delay,
            timeout=timeout,
        )

    def run_concurrent_requests(
        self,
        request_fn,
        operations: list[tuple[str, dict[str, object]]],
        *,
        hash_delay: float = 0.0,
        timeout: float = 5,
    ) -> list[tuple[int, dict[str, object]]]:
        original_hash = server.canonical_json_hash
        if hash_delay > 0:
            def delayed_hash(data: object) -> str:
                time.sleep(hash_delay)
                return original_hash(data)

            server.canonical_json_hash = delayed_hash

        barrier = threading.Barrier(len(operations))
        results: list[tuple[int, dict[str, object]] | None] = [None] * len(operations)
        errors: list[str] = []

        def worker(index: int, market_id: str, body: dict[str, object]) -> None:
            try:
                barrier.wait(timeout=timeout)
                results[index] = request_fn(market_id, body, timeout=timeout)
            except Exception as exc:
                errors.append(f"{index}: {exc!r}")

        threads = [
            threading.Thread(target=worker, args=(index, market_id, body), daemon=True)
            for index, (market_id, body) in enumerate(operations)
        ]

        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=timeout + 2)
        finally:
            server.canonical_json_hash = original_hash

        if errors:
            self.fail(f"concurrent requests failed: {errors}")
        if any(thread.is_alive() for thread in threads):
            self.fail("concurrent requests did not complete before timeout")
        if any(result is None for result in results):
            self.fail("concurrent requests completed without producing full results")

        return [result for result in results if result is not None]

    def test_concurrent_duplicate_probability_edit_idempotency_key_replays_without_double_append(self):
        operations = [
            (
                "m1",
                build_unconditional_probability_edit_body(
                    "acct_concurrency_idem_probability",
                    "m1",
                    "yes",
                    0.8,
                    idempotency_key="idem-concurrency-probability",
                ),
            )
            for _ in range(2)
        ]

        responses = self.run_concurrent_probability_edits(operations, hash_delay=0.01, timeout=10)
        replayed_count = sum(1 for _, payload in responses if payload["meta"].get("replayed"))

        for status, payload in responses:
            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")

        self.assertEqual(replayed_count, 1)
        self.assertEqual({payload["order"]["id"] for _, payload in responses}, {next(iter(server.ORDERS))})
        self.assertEqual({payload["result"]["commandId"] for _, payload in responses}, set(server.COMMANDS))
        self.assertEqual({payload["result"]["eventId"] for _, payload in responses}, set(server.EVENTS))
        self.assertEqual(len(server.ORDERS), 1)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(len(server.TERMINAL_OUTCOMES), 1)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})

        risk_status, risk_payload = self.account_risk("acct_concurrency_idem_probability", timeout=10)
        events_status, events_payload = self.market_events("m1", timeout=10)

        self.assertEqual(risk_status, 200)
        self.assertEqual(events_status, 200)
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)
        self.assertEqual(events_payload["pagination"]["returned"], 1)
        self.assertEqual(events_payload["chain"]["headSeq"], 1)
        self.assertEqual(events_payload["events"][0]["seq"], 1)
        self.assertEqual(events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(events_payload["chain"]["headHash"], events_payload["events"][0]["eventHash"])

    def test_concurrent_duplicate_event_trade_idempotency_key_replays_without_double_append(self):
        operations = [
            (
                "m1",
                build_event_trade_body(
                    "acct_concurrency_idem_event_trade",
                    "m1",
                    "yes",
                    idempotency_key="idem-concurrency-event-trade",
                ),
            )
            for _ in range(2)
        ]

        responses = self.run_concurrent_event_trades(operations, hash_delay=0.01, timeout=10)
        replayed_count = sum(1 for _, payload in responses if payload["meta"].get("replayed"))

        for status, payload in responses:
            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")

        self.assertEqual(replayed_count, 1)
        self.assertEqual({payload["order"]["id"] for _, payload in responses}, {next(iter(server.ORDERS))})
        self.assertEqual({payload["result"]["commandId"] for _, payload in responses}, set(server.COMMANDS))
        self.assertEqual({payload["result"]["eventId"] for _, payload in responses}, set(server.EVENTS))
        self.assertEqual(len(server.ORDERS), 1)
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(len(server.TERMINAL_OUTCOMES), 1)
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ACCOUNT_RISK, {})

        events_status, events_payload = self.market_events("m1", timeout=10)

        self.assertEqual(events_status, 200)
        self.assertEqual(events_payload["pagination"]["returned"], 1)
        self.assertEqual(events_payload["chain"]["headSeq"], 1)
        self.assertEqual(events_payload["events"][0]["seq"], 1)
        self.assertEqual(events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(events_payload["chain"]["headHash"], events_payload["events"][0]["eventHash"])

    def test_concurrent_same_market_probability_edits_keep_contiguous_seq_and_chain_links(self):
        operations = [
            (
                "m1",
                build_unconditional_probability_edit_body(
                    f"acct_concurrency_m1_{index}",
                    "m1",
                    "yes" if index % 2 == 0 else "no",
                    0.8 if index % 2 == 0 else 0.2,
                ),
            )
            for index in range(12)
        ]

        responses = self.run_concurrent_probability_edits(operations, hash_delay=0.01, timeout=10)

        for status, payload in responses:
            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")

        events_status, events_payload = self.market_events("m1", timeout=10)
        events = events_payload["events"]

        self.assertEqual(events_status, 200)
        self.assertEqual(len(events), len(operations))
        self.assertEqual([event["seq"] for event in events], list(range(1, len(operations) + 1)))

        previous_event_hash = server.GENESIS_EVENT_HASH
        for event in events:
            self.assertEqual(event["prevEventHash"], previous_event_hash)
            previous_event_hash = event["eventHash"]

        response_event_ids = {payload["result"]["eventId"] for _, payload in responses}
        response_command_ids = {payload["result"]["commandId"] for _, payload in responses}
        self.assertEqual({event["eventId"] for event in events}, response_event_ids)
        self.assertEqual(len(response_command_ids), len(operations))
        self.assertEqual(len(response_event_ids), len(operations))
        self.assertEqual(events_payload["chain"]["headSeq"], len(operations))
        self.assertEqual(events_payload["chain"]["headHash"], events[-1]["eventHash"])

    def test_concurrent_split_markets_keep_independent_journal_heads(self):
        operations = []
        for index in range(6):
            operations.extend(
                [
                    (
                        "m1",
                        build_unconditional_probability_edit_body(
                            f"acct_concurrency_m1_{index}",
                            "m1",
                            "yes" if index % 2 == 0 else "no",
                            0.8 if index % 2 == 0 else 0.2,
                        ),
                    ),
                    (
                        "m2",
                        build_unconditional_probability_edit_body(
                            f"acct_concurrency_m2_{index}",
                            "m2",
                            "yes" if index % 2 == 0 else "delayed",
                            0.35 if index % 2 == 0 else 0.25,
                        ),
                    ),
                ]
            )

        responses = self.run_concurrent_probability_edits(operations, hash_delay=0.01, timeout=10)

        for status, payload in responses:
            self.assertEqual(status, 201)
            self.assertEqual(payload["result"]["status"], "accepted")

        expected_event_ids_by_market = {
            market_id: {
                payload["result"]["eventId"]
                for (response_market_id, _), (_, payload) in zip(operations, responses)
                if response_market_id == market_id
            }
            for market_id in ("m1", "m2")
        }

        for market_id in ("m1", "m2"):
            events_status, events_payload = self.market_events(market_id, timeout=10)
            events = events_payload["events"]
            expected_count = sum(1 for response_market_id, _ in operations if response_market_id == market_id)

            with self.subTest(market_id=market_id):
                self.assertEqual(events_status, 200)
                self.assertEqual(len(events), expected_count)
                self.assertEqual([event["seq"] for event in events], list(range(1, expected_count + 1)))
                self.assertEqual({event["eventId"] for event in events}, expected_event_ids_by_market[market_id])
                self.assertEqual(events_payload["chain"]["headSeq"], expected_count)
                self.assertEqual(events_payload["chain"]["headHash"], events[-1]["eventHash"])

                previous_event_hash = server.GENESIS_EVENT_HASH
                for event in events:
                    self.assertEqual(event["prevEventHash"], previous_event_hash)
                    previous_event_hash = event["eventHash"]


class BayesMarketApiAuthRateLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server.reset_state()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.BayesHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    def setUp(self) -> None:
        server.reset_state()
        self._original_auth_require_agent_id = server.AUTH_REQUIRE_AGENT_ID
        self._original_rate_limit_per_min = server.RATE_LIMIT_PER_MIN
        self._create_market_title_index = 0

    def tearDown(self) -> None:
        server.AUTH_REQUIRE_AGENT_ID = self._original_auth_require_agent_id
        server.RATE_LIMIT_PER_MIN = self._original_rate_limit_per_min
        server.reset_rate_limit_state()

    def request_with_headers(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = 5,
        headers: dict[str, str] | None = None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        payload = None if body is None else json.dumps(body)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=payload, headers=request_headers)
            response = conn.getresponse()
            response_body = response.read().decode()
            response_headers = {key: value for key, value in response.getheaders()}
        finally:
            conn.close()
        return response.status, json.loads(response_body), response_headers

    def request_raw(
        self,
        method: str,
        path: str,
        body: str | bytes | None = None,
        *,
        timeout: float = 5,
        headers: dict[str, str] | None = None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        request_headers = dict(headers or {})
        request_body = body.encode("utf-8") if isinstance(body, str) else body
        if request_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=request_body, headers=request_headers)
            response = conn.getresponse()
            response_body = response.read().decode()
            response_headers = {key: value for key, value in response.getheaders()}
        finally:
            conn.close()
        return response.status, json.loads(response_body), response_headers

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = 5,
        headers: dict[str, str] | None = None,
    ):
        status, payload, _ = self.request_with_headers(method, path, body, timeout=timeout, headers=headers)
        return status, payload

    def _headers_with_agent_id(self, agent_id: str | None = None) -> dict[str, str]:
        return {} if agent_id is None else {server.AGENT_ID_HEADER: agent_id}

    def _next_create_market_title(self) -> str:
        self._create_market_title_index += 1
        return f"HTTP Auth Create Market {self._create_market_title_index}"

    def create_market(
        self,
        *,
        title: str | None = None,
        description: str = "A test market",
        outcomes: list[dict[str, str]] | None = None,
        expires_at: str = "2026-12-31T23:59:59Z",
        liquidity: float = 10000.0,
        agent_id: str | None = None,
    ):
        status, payload, _ = self.create_market_with_headers(
            title=title,
            description=description,
            outcomes=outcomes,
            expires_at=expires_at,
            liquidity=liquidity,
            agent_id=agent_id,
        )
        return status, payload

    def create_market_with_headers(
        self,
        *,
        title: str | None = None,
        description: str = "A test market",
        outcomes: list[dict[str, str]] | None = None,
        expires_at: str = "2026-12-31T23:59:59Z",
        liquidity: float = 10000.0,
        agent_id: str | None = None,
    ):
        return self.request_with_headers(
            "POST",
            "/v1/markets",
            build_create_market_body(
                title=self._next_create_market_title() if title is None else title,
                description=description,
                outcomes=outcomes,
                expires_at=expires_at,
                liquidity=liquidity,
            ),
            headers=self._headers_with_agent_id(agent_id),
        )

    def probability_edit(
        self,
        probability: float,
        *,
        account_id: str = "acct_http_auth",
        agent_id: str | None = None,
    ):
        status, payload, _ = self.probability_edit_with_headers(
            probability,
            account_id=account_id,
            agent_id=agent_id,
        )
        return status, payload

    def probability_edit_with_headers(
        self,
        probability: float,
        *,
        account_id: str = "acct_http_auth",
        agent_id: str | None = None,
    ):
        return self.request_with_headers(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body(account_id, "m1", "yes", probability),
            headers=self._headers_with_agent_id(agent_id),
        )

    def comment_post(
        self,
        *,
        market_id: str = "m1",
        account_id: str = "acct_http_auth_comment",
        comment_body: str = "HTTP auth comment",
        agent_id: str | None = None,
    ):
        status, payload, _ = self.comment_post_with_headers(
            market_id=market_id,
            account_id=account_id,
            comment_body=comment_body,
            agent_id=agent_id,
        )
        return status, payload

    def comment_post_with_headers(
        self,
        *,
        market_id: str = "m1",
        account_id: str = "acct_http_auth_comment",
        comment_body: str = "HTTP auth comment",
        agent_id: str | None = None,
    ):
        return self.request_with_headers(
            "POST",
            f"/v1/markets/{market_id}/comments",
            {"accountId": account_id, "body": comment_body},
            headers=self._headers_with_agent_id(agent_id),
        )

    def event_trade(
        self,
        *,
        market_id: str = "m1",
        outcome_id: str = "yes",
        account_id: str = "acct_http_auth_trade",
        size: float = 12.5,
        side: str = "buy",
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ):
        status, payload, _ = self.event_trade_with_headers(
            market_id=market_id,
            outcome_id=outcome_id,
            account_id=account_id,
            size=size,
            side=side,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
        )
        return status, payload

    def event_trade_with_headers(
        self,
        *,
        market_id: str = "m1",
        outcome_id: str = "yes",
        account_id: str = "acct_http_auth_trade",
        size: float = 12.5,
        side: str = "buy",
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ):
        return self.request_with_headers(
            "POST",
            f"/v1/markets/{market_id}/orders/event-trade",
            build_event_trade_body(
                account_id,
                market_id,
                outcome_id,
                size=size,
                side=side,
                idempotency_key=idempotency_key,
            ),
            headers=self._headers_with_agent_id(agent_id),
        )

    def market_resolution_with_headers(
        self,
        *,
        market_id: str = "m2",
        account_id: str = "ops_http_auth",
        outcome_id: str = "delayed",
        final_probabilities: dict[str, float] | None = None,
        agent_id: str | None = None,
    ):
        return self.request_with_headers(
            "POST",
            f"/v1/markets/{market_id}/resolve",
            build_market_resolution_body(account_id, outcome_id, final_probabilities=final_probabilities),
            headers=self._headers_with_agent_id(agent_id),
        )

    def assert_rate_limit_headers(self, headers: dict[str, str], *, limit: int, remaining: int) -> None:
        self.assertEqual(headers.get("X-RateLimit-Limit"), str(limit))
        self.assertEqual(headers.get("X-RateLimit-Remaining"), str(remaining))
        self.assertEqual(headers.get("X-RateLimit-Policy"), server.RATE_LIMIT_POLICY_VERSION)
        reset_epoch = int(headers["X-RateLimit-Reset"])
        now_epoch = int(time.time())
        self.assertGreaterEqual(reset_epoch, now_epoch)
        self.assertLessEqual(reset_epoch, now_epoch + server.RATE_LIMIT_WINDOW_SECONDS + 1)

    def assert_rate_limit_headers_absent(self, headers: dict[str, str]) -> None:
        self.assertNotIn("X-RateLimit-Limit", headers)
        self.assertNotIn("X-RateLimit-Remaining", headers)
        self.assertNotIn("X-RateLimit-Reset", headers)
        self.assertNotIn("X-RateLimit-Policy", headers)
        self.assertNotIn("Retry-After", headers)

    def assert_agent_id_error(
        self,
        status: int,
        payload: dict[str, object],
        *,
        code: str,
        category: str,
        reason: str | None = None,
    ) -> None:
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(payload["error"]["details"]["header"], server.AGENT_ID_HEADER)
        self.assertEqual(payload["error"]["details"]["category"], category)
        if reason is None:
            self.assertNotIn("reason", payload["error"]["details"])
        else:
            self.assertEqual(payload["error"]["details"]["reason"], reason)

    def test_probability_edit_http_allows_missing_agent_id_by_default(self):
        server.RATE_LIMIT_PER_MIN = 1

        first_status, first_payload = self.probability_edit(0.8, account_id="acct_http_default_1")
        second_status, second_payload = self.probability_edit(0.7, account_id="acct_http_default_2")

        self.assertEqual(first_status, 201)
        self.assertEqual(first_payload["result"]["status"], "accepted")
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["result"]["status"], "accepted")
        self.assertEqual(len(server.ORDERS), 2)
        self.assertEqual(len(server.EVENTS), 2)

    def test_probability_edit_http_emits_rate_limit_headers_on_success(self):
        server.RATE_LIMIT_PER_MIN = 2

        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_headers_success",
            agent_id="agent-header-success",
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assert_rate_limit_headers(response_headers, limit=2, remaining=1)

    def test_comment_post_http_returns_accepted_comment_contract_with_rate_limit_headers(self):
        server.RATE_LIMIT_PER_MIN = 2

        status, payload, response_headers = self.comment_post_with_headers(
            market_id="m1",
            account_id="acct_http_headers_comment_contract",
            comment_body="HTTP auth comment contract",
            agent_id="agent-header-comment-contract",
        )

        self.assertEqual(status, 201)
        self.assertEqual(set(payload), {"comment", "meta"})
        self.assertEqual(
            set(payload["comment"]),
            {"commentId", "marketId", "seq", "accountId", "body", "createdAt"},
        )
        self.assertEqual(payload["comment"]["marketId"], "m1")
        self.assertEqual(payload["comment"]["seq"], 1)
        self.assertEqual(payload["comment"]["accountId"], "acct_http_headers_comment_contract")
        self.assertEqual(payload["comment"]["body"], "HTTP auth comment contract")
        self.assertTrue(payload["comment"]["commentId"])
        self.assertTrue(payload["comment"]["createdAt"].endswith("Z"))
        self.assertEqual(payload["meta"].keys(), {"timestamp"})
        self.assertTrue(payload["meta"]["timestamp"].endswith("Z"))
        self.assert_rate_limit_headers(response_headers, limit=2, remaining=1)

        self.assertEqual(server.MARKET_COMMENT_SEQUENCES["m1"], 1)
        self.assertEqual(len(server.COMMENTS), 1)
        self.assertEqual(server.COMMENTS[payload["comment"]["commentId"]], payload["comment"])

    def test_protected_post_routes_emit_rate_limit_headers_on_first_success(self):
        server.RATE_LIMIT_PER_MIN = 2

        route_requests = (
            (
                "create-market",
                lambda agent_id: self.create_market_with_headers(agent_id=agent_id),
            ),
            (
                "probability-edit",
                lambda agent_id: self.probability_edit_with_headers(
                    0.8,
                    account_id="acct_http_headers_breadth_probability",
                    agent_id=agent_id,
                ),
            ),
            (
                "market-resolve",
                lambda agent_id: self.market_resolution_with_headers(
                    market_id="m2",
                    account_id="ops_http_headers_breadth_resolve",
                    outcome_id="delayed",
                    agent_id=agent_id,
                ),
            ),
            (
                "comment-post",
                lambda agent_id: self.comment_post_with_headers(
                    market_id="m1",
                    account_id="acct_http_headers_breadth_comment",
                    comment_body="HTTP auth breadth comment",
                    agent_id=agent_id,
                ),
            ),
            (
                "event-trade",
                lambda agent_id: self.event_trade_with_headers(
                    market_id="m1",
                    outcome_id="yes",
                    account_id="acct_http_headers_breadth_trade",
                    agent_id=agent_id,
                ),
            ),
        )

        for label, request in route_requests:
            with self.subTest(label=label):
                status, _, response_headers = request(f"agent-header-breadth-{label}")

                self.assertEqual(status, 201)
                self.assert_rate_limit_headers(response_headers, limit=2, remaining=1)

    def test_probability_edit_http_decrements_remaining_quota_headers_per_agent_id(self):
        server.RATE_LIMIT_PER_MIN = 3

        first_status, _, first_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_headers_remaining_1",
            agent_id="agent-header-remaining",
        )
        second_status, _, second_headers = self.probability_edit_with_headers(
            0.7,
            account_id="acct_http_headers_remaining_2",
            agent_id="agent-header-remaining",
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assert_rate_limit_headers(first_headers, limit=3, remaining=2)
        self.assert_rate_limit_headers(second_headers, limit=3, remaining=1)

    def test_probability_edit_http_omits_rate_limit_headers_when_limiter_disabled(self):
        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_headers_disabled",
            agent_id="agent-header-disabled",
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assert_rate_limit_headers_absent(response_headers)

    def test_probability_edit_http_omits_rate_limit_headers_without_agent_id(self):
        server.RATE_LIMIT_PER_MIN = 1

        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_headers_anonymous",
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assert_rate_limit_headers_absent(response_headers)

    def test_probability_edit_http_requires_agent_id_when_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 1

        status, payload = self.probability_edit(0.8)
        retry_status, retry_payload = self.probability_edit(0.7, account_id="acct_http_auth_retry", agent_id="agent-auth-required")
        limited_status, limited_payload = self.probability_edit(
            0.6,
            account_id="acct_http_auth_retry_limited",
            agent_id="agent-auth-required",
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "missing_agent_id")
        self.assertEqual(payload["error"]["details"]["header"], server.AGENT_ID_HEADER)
        self.assertEqual(retry_status, 201)
        self.assertEqual(retry_payload["result"]["status"], "accepted")
        self.assertEqual(limited_status, 429)
        self.assertEqual(limited_payload["error"]["code"], "rate_limit_exceeded")
        self.assertEqual(limited_payload["error"]["details"]["agentId"], "agent-auth-required")
        self.assertEqual(len(server.COMMANDS), 1)
        self.assertEqual(len(server.EVENTS), 1)
        self.assertEqual(len(server.ORDERS), 1)

    def test_probability_edit_http_missing_agent_id_error_omits_retry_after_and_quota_headers(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 1

        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_auth_missing_headers",
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "missing_agent_id")
        self.assertEqual(payload["error"]["details"]["header"], server.AGENT_ID_HEADER)
        self.assert_rate_limit_headers_absent(response_headers)

    def test_probability_edit_http_rejects_blank_agent_id_when_required(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        before_state = snapshot_domain_state()

        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_auth_blank",
            agent_id="   ",
        )

        self.assert_agent_id_error(status, payload, code="blank_agent_id", category=server.TRADE_WRITE_CATEGORY)
        self.assert_rate_limit_headers_absent(response_headers)
        assert_domain_state_unchanged(self, before_state)

    def test_probability_edit_http_rejects_malformed_agent_id_when_required(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        before_state = snapshot_domain_state()

        status, payload, response_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_auth_invalid",
            agent_id="agent invalid",
        )

        self.assert_agent_id_error(
            status,
            payload,
            code="invalid_agent_id",
            category=server.TRADE_WRITE_CATEGORY,
            reason="invalid_format",
        )
        self.assert_rate_limit_headers_absent(response_headers)
        assert_domain_state_unchanged(self, before_state)

    def test_probability_edit_http_accepts_agent_id_when_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        bad_json_status, bad_json_payload, _ = self.request_raw(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            '{"accountId": "acct_http_bad_json"',
        )
        market_status, market_payload = self.request("GET", "/v1/markets/m1")

        status, payload = self.probability_edit(0.8, agent_id="agent-auth-ok")

        self.assertEqual(bad_json_status, 400)
        self.assertEqual(bad_json_payload["error"]["code"], "invalid_json")
        self.assertEqual(market_status, 200)
        self.assertEqual(market_payload["market"]["id"], "m1")
        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(len(server.ORDERS), 1)

    def test_market_resolve_http_requires_valid_agent_id_when_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 1

        missing_status, missing_payload, missing_headers = self.market_resolution_with_headers(
            account_id="ops_http_auth_missing",
        )
        blank_status, blank_payload, blank_headers = self.market_resolution_with_headers(
            account_id="ops_http_auth_blank",
            agent_id="   ",
        )
        invalid_status, invalid_payload, invalid_headers = self.market_resolution_with_headers(
            account_id="ops_http_auth_invalid",
            agent_id="ops admin",
        )

        self.assert_agent_id_error(
            missing_status,
            missing_payload,
            code="missing_agent_id",
            category=server.MARKET_ADMIN_WRITE_CATEGORY,
        )
        self.assert_rate_limit_headers_absent(missing_headers)
        self.assert_agent_id_error(
            blank_status,
            blank_payload,
            code="blank_agent_id",
            category=server.MARKET_ADMIN_WRITE_CATEGORY,
        )
        self.assert_rate_limit_headers_absent(blank_headers)
        self.assert_agent_id_error(
            invalid_status,
            invalid_payload,
            code="invalid_agent_id",
            category=server.MARKET_ADMIN_WRITE_CATEGORY,
            reason="invalid_format",
        )
        self.assert_rate_limit_headers_absent(invalid_headers)
        self.assertEqual(server.MARKETS["m2"]["status"], "active")

    def test_market_resolve_http_omits_rate_limit_headers_when_limiter_disabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True

        status, payload, response_headers = self.market_resolution_with_headers(
            market_id="m2",
            account_id="ops_http_auth_valid",
            outcome_id="delayed",
            agent_id="agent-admin-valid",
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["market"]["id"], "m2")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "delayed")
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assert_rate_limit_headers_absent(response_headers)
        self.assertEqual(server.MARKETS["m2"]["status"], "resolved")

    def test_probability_edit_http_emits_retry_after_and_quota_headers_on_429(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 1

        first_status, _, first_headers = self.probability_edit_with_headers(
            0.8,
            account_id="acct_http_headers_retry_1",
            agent_id="agent-header-retry",
        )
        second_status, second_payload, second_headers = self.probability_edit_with_headers(
            0.7,
            account_id="acct_http_headers_retry_2",
            agent_id="agent-header-retry",
        )

        self.assertEqual(first_status, 201)
        self.assert_rate_limit_headers(first_headers, limit=1, remaining=0)
        self.assertEqual(second_status, 429)
        self.assertEqual(second_payload["error"]["code"], "rate_limit_exceeded")
        self.assertEqual(
            second_headers.get("Retry-After"),
            str(second_payload["error"]["details"]["retryAfterSeconds"]),
        )
        self.assert_rate_limit_headers(second_headers, limit=1, remaining=0)

    def test_probability_edit_http_rate_limits_per_agent_id(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 3
        server.reset_rate_limit_state()
        self.addCleanup(server.reset_rate_limit_state)

        first_status, _ = self.probability_edit(0.8, account_id="acct_rl_1", agent_id="agent-rate-limit")
        second_status, _ = self.probability_edit(0.7, account_id="acct_rl_2", agent_id="agent-rate-limit")
        third_status, _ = self.probability_edit(0.6, account_id="acct_rl_3", agent_id="agent-rate-limit")
        fourth_status, fourth_payload = self.probability_edit(0.55, account_id="acct_rl_4", agent_id="agent-rate-limit")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(third_status, 201)
        self.assertEqual(fourth_status, 429)
        self.assertEqual(fourth_payload["error"]["code"], "rate_limit_exceeded")
        self.assertEqual(fourth_payload["error"]["details"]["agentId"], "agent-rate-limit")
        self.assertEqual(fourth_payload["error"]["details"]["limit"], 3)
        self.assertEqual(fourth_payload["error"]["details"]["windowSeconds"], 60)
        self.assertGreaterEqual(fourth_payload["error"]["details"]["retryAfterSeconds"], 1)
        self.assertEqual(len(server.ORDERS), 3)
        self.assertEqual(len(server.EVENTS), 3)

    def test_probability_edit_http_keeps_quota_windows_isolated_by_agent_id(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        server.RATE_LIMIT_PER_MIN = 2
        server.reset_rate_limit_state()
        self.addCleanup(server.reset_rate_limit_state)

        first_status, _ = self.probability_edit(0.8, account_id="acct_iso_a1", agent_id="agent-a")
        second_status, _ = self.probability_edit(0.7, account_id="acct_iso_a2", agent_id="agent-a")
        third_status, _ = self.probability_edit(0.6, account_id="acct_iso_b1", agent_id="agent-b")
        fourth_status, fourth_payload = self.probability_edit(0.55, account_id="acct_iso_a3", agent_id="agent-a")
        fifth_status, _ = self.probability_edit(0.45, account_id="acct_iso_b2", agent_id="agent-b")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(third_status, 201)
        self.assertEqual(fourth_status, 429)
        self.assertEqual(fourth_payload["error"]["code"], "rate_limit_exceeded")
        self.assertEqual(fourth_payload["error"]["details"]["agentId"], "agent-a")
        self.assertEqual(fifth_status, 201)
        self.assertEqual(len(server.ORDERS), 4)
        self.assertEqual(len(server.EVENTS), 4)

    def test_create_market_http_requires_agent_id_when_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        market_title = "HTTP Auth Create Market"

        unauthorized_status, unauthorized_payload = self.create_market(title=market_title)
        authorized_status, authorized_payload = self.create_market(
            title=market_title,
            agent_id="agent-create-auth",
        )

        self.assertEqual(unauthorized_status, 401)
        self.assertEqual(unauthorized_payload["error"]["code"], "missing_agent_id")
        self.assertEqual(unauthorized_payload["error"]["details"]["header"], server.AGENT_ID_HEADER)
        self.assertEqual(authorized_status, 201)
        self.assertEqual(authorized_payload["market"]["title"], market_title)
        self.assertEqual(len(server.MARKETS), len(server.INITIAL_MARKETS) + 1)

    def test_market_resolve_http_requires_agent_id_when_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        body = build_market_resolution_body("ops_http_auth", "yes")

        unauthorized_status, unauthorized_payload = self.request("POST", "/v1/markets/m1/resolve", body)
        authorized_status, authorized_payload = self.request(
            "POST",
            "/v1/markets/m1/resolve",
            body,
            headers={server.AGENT_ID_HEADER: "agent-resolve-auth"},
        )

        self.assertEqual(unauthorized_status, 401)
        self.assertEqual(unauthorized_payload["error"]["code"], "missing_agent_id")
        self.assertEqual(unauthorized_payload["error"]["details"]["header"], server.AGENT_ID_HEADER)
        self.assertEqual(authorized_status, 201)
        self.assertEqual(authorized_payload["market"]["status"], "resolved")
        self.assertEqual(authorized_payload["market"]["resolution"], "yes")

    def test_resolve_write_request_agent_rejects_duplicate_header_lines_when_required(self):
        server.AUTH_REQUIRE_AGENT_ID = True
        headers = Message()
        headers.add_header(server.AGENT_ID_HEADER, "agent-dup-a")
        headers.add_header(server.AGENT_ID_HEADER, "agent-dup-b")

        with self.assertRaises(server.ApiError) as raised:
            server.resolve_write_request_agent("POST", "/v1/markets/m1/orders/probability-edit", headers)

        error = raised.exception
        self.assertEqual(error.status, 401)
        self.assertEqual(error.code, "invalid_agent_id")
        self.assertEqual(error.details["header"], server.AGENT_ID_HEADER)
        self.assertEqual(error.details["category"], server.TRADE_WRITE_CATEGORY)
        self.assertEqual(error.details["reason"], "multiple_values")

    def test_unsupported_post_route_stays_router_not_found_when_auth_enabled(self):
        server.AUTH_REQUIRE_AGENT_ID = True

        status, payload, response_headers = self.request_with_headers(
            "POST",
            "/v1/orders/probability-edit",
            build_unconditional_probability_edit_body("acct_http_legacy", "m1", "yes", 0.8),
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["details"]["path"], "/v1/orders/probability-edit")
        self.assert_rate_limit_headers_absent(response_headers)


class BayesMarketApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server.reset_state()
        cls.httpd = server.HTTPServer(("127.0.0.1", 0), server.BayesHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    def setUp(self) -> None:
        server.reset_state()

    def request_with_headers(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = None if body is None else json.dumps(body)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=payload, headers=request_headers)
            response = conn.getresponse()
            response_body = response.read().decode()
            response_headers = {key: value for key, value in response.getheaders()}
        finally:
            conn.close()
        return response.status, json.loads(response_body), response_headers

    def request_raw(
        self,
        method: str,
        path: str,
        body: str | bytes | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = dict(headers or {})
        request_body = body.encode("utf-8") if isinstance(body, str) else body
        if request_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=request_body, headers=request_headers)
            response = conn.getresponse()
            response_body = response.read()
            response_headers = {key: value for key, value in response.getheaders()}
        finally:
            conn.close()
        return response.status, response_body, response_headers

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        status, payload, _ = self.request_with_headers(method, path, body, headers=headers)
        return status, payload

    def test_legacy_health_http_routes_return_service_payload(self):
        timestamp_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"

        for path in ("/health", "/healthz"):
            with self.subTest(path=path):
                status, payload = self.request("GET", path)

                self.assertEqual(status, 200)
                self.assertEqual(set(payload), {"service", "status", "timestamp"})
                self.assertEqual(payload["service"], "bayes-market")
                self.assertEqual(payload["status"], "ok")
                self.assertIsInstance(payload["timestamp"], str)
                self.assertRegex(payload["timestamp"], timestamp_pattern)

    def test_v1_health_http_returns_versioned_service_payload(self):
        status, payload = self.request("GET", "/v1/health")

        self.assertEqual(status, 200)
        self.assertEqual(
            set(payload),
            {"service", "status", "timestamp", "version", "uptime_seconds", "components"},
        )
        self.assertEqual(payload["service"], "bayes-market")
        self.assertEqual(payload["status"], "ok")
        self.assertIsInstance(payload["timestamp"], str)
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
        self.assertEqual(payload["version"], server.ENGINE_CONFIG.version)
        self.assertIsInstance(payload["uptime_seconds"], float)
        self.assertIsInstance(payload["components"], dict)
        self.assertEqual(set(payload["components"]), {"db", "inference", "auth"})

    def test_create_market_http_returns_created_market_and_collection_entry(self):
        body = build_create_market_body(
            title="Solana ETF Approval in April",
            description="Will a new Solana ETF be approved in April 2026?",
            liquidity=42000.0,
        )

        status, payload = self.request("POST", "/v1/markets", body)
        detail_status, detail_payload = self.request("GET", f"/v1/markets/{payload['market']['id']}")
        list_status, list_payload = self.request("GET", "/v1/markets")

        self.assertEqual(status, 201)
        self.assertEqual(detail_status, 200)
        self.assertEqual(list_status, 200)
        self.assertEqual(payload["market"]["id"], "m4")
        self.assertEqual(payload["market"]["title"], body["title"])
        self.assertEqual(payload["market"]["description"], body["description"])
        self.assertEqual(payload["market"]["variableId"], "solana_etf_approval_in_april")
        self.assertEqual(payload["market"]["status"], "active")
        self.assertEqual(payload["market"]["marginals"], {"yes": 0.5, "no": 0.5})
        self.assertEqual(payload["market"]["liquidity"], 42000.0)
        self.assertEqual(payload["market"]["volume"], 0.0)
        self.assertEqual(detail_payload["market"], payload["market"])
        self.assertEqual(list_payload["count"], len(server.INITIAL_MARKETS) + 1)
        self.assertIn("m4", {market["id"] for market in list_payload["markets"]})

    def test_create_market_http_rejects_invalid_payloads_without_side_effects(self):
        cases = (
            (
                "missing_title",
                {
                    "description": "A test market",
                    "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
                    "expires_at": "2026-12-31T23:59:59Z",
                },
                "title is required and must be a string",
            ),
            (
                "duplicate_outcome_ids",
                build_create_market_body(
                    outcomes=[{"id": "yes", "name": "Yes"}, {"id": "yes", "name": "Still Yes"}],
                ),
                "outcome IDs must be unique",
            ),
            (
                "missing_expires_at",
                {
                    "title": "No Expiry Market",
                    "description": "A test market",
                    "outcomes": [{"id": "yes", "name": "Yes"}, {"id": "no", "name": "No"}],
                },
                "expires_at is required (ISO 8601 string)",
            ),
        )

        for label, body, expected_message in cases:
            with self.subTest(label=label):
                before_state = snapshot_domain_state()

                status, payload = self.request("POST", "/v1/markets", body)

                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_payload")
                self.assertEqual(payload["error"]["message"], expected_message)
                assert_domain_state_unchanged(self, before_state)

    def test_create_market_http_rejects_duplicate_market_variable_id(self):
        body = build_create_market_body(title="Duplicate Collision Market")

        first_status, first_payload = self.request("POST", "/v1/markets", body)
        second_status, second_payload = self.request("POST", "/v1/markets", deepcopy(body))
        list_status, list_payload = self.request("GET", "/v1/markets")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 409)
        self.assertEqual(list_status, 200)
        self.assertEqual(second_payload["error"]["code"], "market_already_exists")
        self.assertEqual(second_payload["error"]["message"], "A market with this title already exists")
        self.assertEqual(
            second_payload["error"]["details"],
            {
                "title": body["title"],
                "variableId": first_payload["market"]["variableId"],
                "existingMarketId": first_payload["market"]["id"],
            },
        )
        self.assertEqual(list_payload["count"], len(server.INITIAL_MARKETS) + 1)

    def test_frontend_spa_routes_serve_index_html(self):
        status, body, headers = self.request_raw("GET", "/markets/m1")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn(b'<div id="root"></div>', body)
        self.assertIn(b'/assets/index-', body)

    def test_frontend_market_routes_emit_market_preview_meta_tags(self):
        status, body, headers = self.request_raw(
            "GET",
            "/markets/m1",
            headers={"Host": "share.example", "X-Forwarded-Proto": "https"},
        )
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html")
        self.assertIn("<title>ETH Price &gt; $3000 on March 15</title>", html)
        self.assertIn(
            '<meta name="description" content="Will ETH trade above $3000 at any point on March 15, 2026?" />',
            html,
        )
        self.assertIn(
            '<meta property="og:title" content="ETH Price &gt; $3000 on March 15" />',
            html,
        )
        self.assertIn(
            '<meta property="og:url" content="https://share.example/markets/m1" />',
            html,
        )

    def test_missing_market_frontend_route_keeps_generic_meta_tags(self):
        status, body, _ = self.request_raw(
            "GET",
            "/markets/missing-market",
            headers={"Host": "share.example", "X-Forwarded-Proto": "https"},
        )
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn(f"<title>{server.SITE_NAME}</title>", html)
        self.assertIn(
            '<meta property="og:url" content="https://share.example/markets/missing-market" />',
            html,
        )
        self.assertIn(
            f'<meta name="description" content="{server.SITE_DESCRIPTION}" />',
            html,
        )

    def test_market_meta_http_route_uses_request_origin_when_unconfigured(self):
        status, payload = self.request(
            "GET",
            "/v1/markets/m1/meta",
            headers={"Host": "share.example:4444", "X-Forwarded-Proto": "https"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["preview"]["marketId"], "m1")
        self.assertEqual(payload["preview"]["url"], "https://share.example:4444/markets/m1")

    def test_frontend_asset_requests_serve_bundles_with_immutable_cache_headers(self):
        asset_path = next((server.FRONTEND_DIST / "assets").glob("*.js"))

        status, body, headers = self.request_raw("GET", f"/assets/{asset_path.name}")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/javascript")
        self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(body, asset_path.read_bytes())

    def test_missing_frontend_asset_does_not_fall_back_to_index_html(self):
        status, body, headers = self.request_raw("GET", "/assets/does-not-exist.js")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_frontend_static_handler_blocks_path_traversal_outside_dist(self):
        probe_path = server.FRONTEND_DIST.parent / f"{server.FRONTEND_DIST.name}-escape-probe.txt"
        probe_path.write_text("static-traversal-probe", encoding="utf-8")
        self.addCleanup(lambda: probe_path.unlink(missing_ok=True))

        status, body, headers = self.request_raw("GET", f"/../{probe_path.name}")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertNotIn(b"static-traversal-probe", body)

    def test_market_detail_http_returns_conditional_marginals_for_context_query(self):
        context = [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}]
        post_status, post_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http_conditional_market_read",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": deepcopy(context),
            },
        )
        unconditional_status, unconditional_payload = self.request("GET", "/v1/markets/m1")
        contextual_status, contextual_payload = self.request(
            "GET",
            f"/v1/markets/m1?{build_market_context_query_string(context)}",
        )

        self.assertEqual(post_status, 201)
        self.assertEqual(unconditional_status, 200)
        self.assertEqual(contextual_status, 200)
        self.assertEqual(unconditional_payload["market"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(contextual_payload["market"]["marginals"], post_payload["order"]["newMarginals"])
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(
            server.CONDITIONAL_MARGINALS["m1"][server.context_state_key(context)],
            post_payload["order"]["newMarginals"],
        )

    def test_market_detail_http_canonicalizes_context_query_order(self):
        canonical_context = [
            {"variableId": "btc_etf_approval_week", "outcomeId": "yes"},
            {"variableId": "fed_rate_cut_mar_2026", "outcomeId": "no"},
        ]
        server.CONDITIONAL_MARGINALS["m1"] = {
            server.context_state_key(canonical_context): {"yes": 0.91, "no": 0.09}
        }

        status, payload = self.request(
            "GET",
            "/v1/markets/m1?"
            + build_market_context_query_string(list(reversed(canonical_context))),
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["market"]["marginals"], {"yes": 0.91, "no": 0.09})
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})

    def test_market_detail_http_rejects_malformed_context_query(self):
        status, payload = self.request("GET", "/v1/markets/m1?context=btc_etf_approval_week")

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_query")
        self.assertEqual(payload["error"]["details"]["parameter"], "context")
        self.assertEqual(payload["error"]["details"]["index"], 0)
        self.assertEqual(payload["error"]["details"]["received"], "btc_etf_approval_week")

    def test_probability_edit_route_uses_market_scoped_path(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["marketId"], "m1")
        self.assertEqual(payload["order"]["type"], "ProbabilityEdit")
        self.assertEqual(payload["order"]["accountId"], "acct_http")
        self.assertTrue(payload["order"]["commandId"].startswith("cmd_"))
        self.assertTrue(payload["order"]["submittedAt"].endswith("Z"))

    def test_market_resolve_route_uses_market_scoped_path(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_http", "yes"),
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["market"]["id"], "m1")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "yes")
        self.assertEqual(payload["market"]["resolutionProbabilities"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["market"]["marginals"], {"yes": 1.0, "no": 0.0})
        self.assertEqual(payload["result"]["status"], "accepted")
        command = server.COMMANDS[payload["result"]["commandId"]]
        self.assertEqual(command["commandType"], "AdminOp")
        self.assertEqual(command["payload"], expected_market_resolution_payload("m1", "yes"))

    def test_market_resolve_route_accepts_final_probabilities_body(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m2/resolve",
            build_market_resolution_body(
                "ops_http",
                final_probabilities={"yes": 0.0, "no": 0.0, "delayed": 1.0},
            ),
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["market"]["id"], "m2")
        self.assertEqual(payload["market"]["status"], "resolved")
        self.assertEqual(payload["market"]["resolution"], "delayed")
        self.assertEqual(payload["market"]["resolutionProbabilities"], {"yes": 0.0, "no": 0.0, "delayed": 1.0})
        self.assertEqual(payload["market"]["marginals"], {"yes": 0.0, "no": 0.0, "delayed": 1.0})
        command = server.COMMANDS[payload["result"]["commandId"]]
        self.assertEqual(command["payload"], expected_market_resolution_payload("m2", "delayed"))

    def test_market_resolve_route_is_method_not_allowed_for_get(self):
        status, payload = self.request("GET", "/v1/markets/m1/resolve")

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")
        self.assertEqual(payload["error"]["details"]["method"], "GET")
        self.assertEqual(payload["error"]["details"]["path"], "/v1/markets/m1/resolve")

    def test_market_resolve_http_requires_account_id(self):
        cases = (
            ("missing", None),
            ("blank", "   "),
        )

        for label, account_id in cases:
            with self.subTest(label=label):
                body = build_market_resolution_body("ops_http", "yes")
                if account_id is None:
                    del body["accountId"]
                else:
                    body["accountId"] = account_id
                before_state = snapshot_domain_state()

                status, payload = self.request("POST", "/v1/markets/m1/resolve", body)

                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_market_resolution")
                self.assertEqual(payload["error"]["message"], "accountId is required")
                self.assertEqual(payload["error"]["details"]["field"], "accountId")
                assert_domain_state_unchanged(self, before_state)

    def test_market_resolve_http_requires_outcome_id(self):
        cases = (
            ("missing", None),
            ("blank", "   "),
        )

        for label, outcome_id in cases:
            with self.subTest(label=label):
                body = build_market_resolution_body("ops_http", "yes")
                if outcome_id is None:
                    del body["outcomeId"]
                else:
                    body["outcomeId"] = outcome_id
                before_state = snapshot_domain_state()

                status, payload = self.request("POST", "/v1/markets/m1/resolve", body)

                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_market_resolution")
                self.assertEqual(payload["error"]["message"], "outcomeId is required")
                self.assertEqual(payload["error"]["details"]["field"], "outcomeId")
                assert_domain_state_unchanged(self, before_state)

    def test_market_resolve_http_rejects_malformed_idempotency_key(self):
        invalid_values = ("", "   ", 123)

        for value in invalid_values:
            with self.subTest(value=value):
                body = build_market_resolution_body("ops_http", "yes")
                body["idempotencyKey"] = value
                before_state = snapshot_domain_state()

                status, payload = self.request("POST", "/v1/markets/m1/resolve", body)

                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_market_resolution")
                self.assertEqual(
                    payload["error"]["message"],
                    "idempotencyKey must be a non-empty string when provided",
                )
                self.assertEqual(payload["error"]["details"]["field"], "idempotencyKey")
                assert_domain_state_unchanged(self, before_state)

    def test_market_resolve_http_replays_same_idempotency_key(self):
        body = build_market_resolution_body("ops_http", "yes", idempotency_key="idem-http-resolve")

        first_status, first_payload = self.request("POST", "/v1/markets/m1/resolve", body)
        second_status, second_payload = self.request("POST", "/v1/markets/m1/resolve", body)
        events_status, events_payload = self.request("GET", "/v1/markets/m1/events")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(events_status, 200)
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(events_payload["events"], [server.EVENTS[first_payload["result"]["eventId"]]])
        self.assertEqual(events_payload["chain"]["headSeq"], 1)

    def test_market_resolve_http_rejects_already_resolved_market(self):
        body = build_market_resolution_body("ops_http", "no", idempotency_key="idem-http-resolved")

        first_status, first_payload = self.request("POST", "/v1/markets/m3/resolve", body)
        second_status, second_payload = self.request("POST", "/v1/markets/m3/resolve", body)

        self.assertEqual(first_status, 409)
        self.assertEqual(second_status, 409)
        self.assertEqual(first_payload["error"]["code"], "market_already_resolved")
        self.assertEqual(first_payload["error"]["details"]["currentResolution"], "no")
        self.assertEqual(first_payload["result"]["eventType"], "CommandRejected")
        self.assertEqual(first_payload["meta"]["idempotencyKeyEcho"], "idem-http-resolved")
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(server.MARKETS["m3"]["marginals"], {"yes": 0.0, "no": 1.0})

    def test_market_resolve_http_rejects_unknown_outcome_id(self):
        before_state = snapshot_domain_state()

        status, payload = self.request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_http", "maybe"),
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_market_resolution")
        self.assertEqual(payload["error"]["message"], "outcomeId must match a known market outcome")
        self.assertEqual(
            payload["error"]["details"],
            {
                "field": "outcomeId",
                "marketId": "m1",
                "received": "maybe",
                "allowed": ["no", "yes"],
            },
        )
        assert_domain_state_unchanged(self, before_state)

    def test_market_resolve_http_settles_account_exposure(self):
        account_id = "acct_http_resolve_risk"
        post_status, post_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8),
        )
        pre_resolution_risk_status, pre_resolution_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
        pre_resolution_account_state = deepcopy(server.ACCOUNT_RISK[account_id])
        resolve_status, resolve_payload = self.request(
            "POST",
            "/v1/markets/m1/resolve",
            build_market_resolution_body("ops_http", "yes"),
        )
        risk_status, risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")

        self.assertEqual(post_status, 201)
        self.assertEqual(resolve_status, 201)
        self.assertEqual(pre_resolution_risk_status, 200)
        self.assertEqual(risk_status, 200)
        self.assertEqual(resolve_payload["market"]["status"], "resolved")
        self.assertEqual(risk_payload["account"]["id"], account_id)
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"],
            {
                "overall": 100.0,
                "markets": [],
            },
        )
        self.assertEqual(
            risk_payload["account"]["risk"]["capacityIndicators"],
            {
                "limit": 100.0,
                "available": 100.0,
                "consumed": 0.0,
                "utilization": 0.0,
                "status": "healthy",
            },
        )
        self.assertEqual(risk_payload["account"]["risk"]["updatedAt"], server.ACCOUNT_RISK[account_id]["updatedAt"])
        self.assertNotEqual(risk_payload["account"]["risk"]["updatedAt"], pre_resolution_risk_payload["account"]["risk"]["updatedAt"])
        self.assertEqual(server.ACCOUNT_RISK[account_id]["markets"], {})
        self.assertEqual(
            server.ACCOUNT_RISK[account_id]["lmsrState"],
            {
                "version": server.ACCOUNT_LMSR_LEDGER_VERSION,
                "riskReadModel": server.ACCOUNT_LMSR_RISK_READ_MODEL,
                "slices": {},
            },
        )
        self.assertNotEqual(server.ACCOUNT_RISK[account_id], pre_resolution_account_state)
        event = server.EVENTS[resolve_payload["result"]["eventId"]]
        self.assertEqual(
            event["payload"]["effects"]["assetDelta"],
            [
                {
                    "accountId": account_id,
                    "marketId": "m1",
                    "beforeMinAsset": pre_resolution_risk_payload["account"]["risk"]["minAssets"]["overall"],
                    "afterMinAsset": 100.0,
                }
            ],
        )

    def test_probability_edit_legacy_route_is_not_found(self):
        status, payload = self.request(
            "POST",
            "/v1/orders/probability-edit",
            {
                "market_id": "m1",
                "probabilities": [0.8, 0.2],
            },
        )

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_probability_edit_validation_errors_use_structured_contract(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes"},
                "context": [],
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_probability_edit")
        self.assertEqual(payload["error"]["details"]["field"], "target.probability")

    def test_probability_edit_http_surfaces_structure_preserving_validator_failure(self):
        malformed_market_id = "m2_http_malformed"
        server.MARKETS[malformed_market_id] = deepcopy(server.MARKETS["m2"])
        server.MARKETS[malformed_market_id]["id"] = malformed_market_id
        server.MARKETS[malformed_market_id]["variableId"] = "btc_etf_approval_week_http_malformed"
        server.MARKETS[malformed_market_id]["marginals"] = {"yes": 1.0, "no": -0.2, "delayed": 0.2}

        status, payload = self.request(
            "POST",
            f"/v1/markets/{malformed_market_id}/orders/probability-edit",
            build_unconditional_probability_edit_body("acct_http", malformed_market_id, "yes", 0.4),
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_structure_preserving_edit")
        self.assertEqual(payload["error"]["details"]["marketId"], malformed_market_id)
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_probability_edit_http_surfaces_structure_preserving_failure_for_existing_conditional_slice(self):
        context = [{"variableId": "eth_price_gt_3000_mar15", "outcomeId": "yes"}]
        server.CONDITIONAL_MARGINALS["m2"] = {
            server.context_state_key(context): {"yes": 1.0, "no": -0.2, "delayed": 0.2}
        }

        status, payload = self.request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "btc_etf_approval_week",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                "context": deepcopy(context),
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_structure_preserving_edit")
        self.assertEqual(payload["error"]["details"]["marketId"], "m2")
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(server.EVENTS, {})

    def test_probability_edit_http_rejects_missing_account_id(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_probability_edit")
        self.assertEqual(payload["error"]["details"]["field"], "accountId")

    def test_probability_edit_http_rejects_non_numeric_probability(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": "0.8"},
                "context": [],
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_probability_edit")
        self.assertEqual(payload["error"]["details"]["field"], "target.probability")

    def test_probability_edit_http_echoes_idempotency_key(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "idempotencyKey": "idem-http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["order"]["idempotencyKey"], "idem-http")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-http")

    def test_probability_edit_http_replays_same_idempotency_key(self):
        body = {
            "accountId": "acct_http",
            "idempotencyKey": "idem-http",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_payload["order"]["id"], first_payload["order"]["id"])
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertTrue(second_payload["meta"]["replayed"])

    def test_probability_edit_http_replay_preserves_order_risk_and_journal_state(self):
        account_id = "acct_http_replay_full_chain"
        body = {
            "accountId": account_id,
            "idempotencyKey": "idem-http-full-chain",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_status, first_payload = self.request("POST", "/v1/markets/m1/orders/probability-edit", body)
        first_risk_status, first_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
        first_events_status, first_events_payload = self.request("GET", "/v1/markets/m1/events")

        second_status, second_payload = self.request("POST", "/v1/markets/m1/orders/probability-edit", body)
        second_risk_status, second_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
        second_events_status, second_events_payload = self.request("GET", "/v1/markets/m1/events")

        self.assertEqual(first_status, 201)
        self.assertEqual(first_risk_status, 200)
        self.assertEqual(first_events_status, 200)
        self.assertEqual(second_status, 201)
        self.assertEqual(second_risk_status, 200)
        self.assertEqual(second_events_status, 200)
        self.assertEqual(first_payload["result"]["status"], "accepted")
        self.assertEqual(second_payload["order"]["id"], first_payload["order"]["id"])
        self.assertEqual(second_payload["order"]["commandId"], first_payload["order"]["commandId"])
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(first_risk_payload["account"]["risk"], second_risk_payload["account"]["risk"])
        self.assertEqual(first_risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)
        self.assertEqual(
            first_risk_payload["account"]["risk"]["minAssets"]["markets"][0]["lastOrderId"],
            first_payload["order"]["id"],
        )
        self.assertEqual(first_events_payload["events"], second_events_payload["events"])
        self.assertEqual(first_events_payload["chain"], second_events_payload["chain"])
        self.assertEqual(len(first_events_payload["events"]), 1)
        self.assertEqual(first_events_payload["events"][0]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(first_events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(first_events_payload["chain"]["headSeq"], 1)
        self.assertEqual(first_events_payload["chain"]["headHash"], first_events_payload["events"][0]["eventHash"])

    def test_probability_edit_http_rejects_non_active_market(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            {
                "accountId": "acct_http",
                "idempotencyKey": "idem-resolved",
                "variableId": "fed_rate_cut_mar_2026",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                "context": [],
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "market_not_active")
        self.assertEqual(payload["result"]["status"], "rejected")
        self.assertEqual(payload["result"]["eventType"], "CommandRejected")
        self.assertEqual(payload["meta"]["idempotencyKeyEcho"], "idem-resolved")

    def test_probability_edit_http_returns_plain_422_for_unconditional_min_asset_violation(self):
        preview_delta, low_min_asset = seed_low_headroom_account("acct_http_low")
        body = {
            "accountId": "acct_http_low",
            "idempotencyKey": "idem-http-low-headroom",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 422)
        self.assertEqual(second_status, 422)
        self.assertEqual(first_payload["error"]["code"], "min_asset_violation")
        self.assertEqual(
            first_payload["error"]["details"],
            expected_min_asset_violation_details("acct_http_low", "m1", preview_delta),
        )
        self.assertEqual(first_payload["error"], second_payload["error"])
        self.assertNotIn("result", first_payload)
        self.assertNotIn("result", second_payload)
        self.assertEqual(set(first_payload["meta"]), {"timestamp"})
        self.assertEqual(set(second_payload["meta"]), {"timestamp"})
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(server.ORDERS, {})
        self.assertEqual(
            server.ACCOUNT_RISK["acct_http_low"],
            expected_seeded_account_state("acct_http_low", low_min_asset),
        )
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})
        self.assertNotIn(
            server.idempotency_scope_key("m1", "acct_http_low", "idem-http-low-headroom"),
            server.IDEMPOTENCY_KEYS,
        )

    def test_probability_edit_http_repeated_min_asset_violation_omits_terminal_replay_metadata(self):
        preview_delta, _ = seed_low_headroom_account("acct_http_low_replay_contract")
        body = {
            "accountId": "acct_http_low_replay_contract",
            "idempotencyKey": "idem-http-low-replay-contract",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 422)
        self.assertEqual(second_status, 422)
        self.assertEqual(
            first_payload["error"]["details"],
            expected_min_asset_violation_details("acct_http_low_replay_contract", "m1", preview_delta),
        )
        self.assertEqual(second_payload["error"], first_payload["error"])
        self.assertNotIn("result", first_payload)
        self.assertNotIn("result", second_payload)
        self.assertEqual(set(first_payload["meta"]), {"timestamp"})
        self.assertEqual(set(second_payload["meta"]), {"timestamp"})
        self.assertEqual(server.COMMANDS, {})
        self.assertEqual(server.EVENTS, {})
        self.assertEqual(server.TERMINAL_OUTCOMES, {})

    def test_probability_edit_http_replays_rejected_idempotency_key(self):
        body = {
            "accountId": "acct_http",
            "idempotencyKey": "idem-resolved",
            "variableId": "fed_rate_cut_mar_2026",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
            "context": [],
        }

        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            body,
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            body,
        )

        self.assertEqual(first_status, 409)
        self.assertEqual(second_status, 409)
        self.assertEqual(second_payload["result"]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(second_payload["result"]["commandId"], first_payload["result"]["commandId"])
        self.assertTrue(second_payload["meta"]["replayed"])

    def test_probability_edit_http_fresh_account_min_asset_violation_preserves_state_without_replay(self):
        account_id = "acct_http_reject_full_chain"
        market_path = "/v1/markets/m1/orders/probability-edit"
        market_status, market_payload = self.request("GET", "/v1/markets/m1")

        self.assertEqual(market_status, 200)

        accepted_count = 0
        last_successful_risk_payload = None
        last_successful_market_payload = None
        last_successful_events_payload = None
        first_rejection_status = None
        first_rejection_payload = None
        rejected_body = None

        for index in range(32):
            current_yes_probability = market_payload["market"]["marginals"]["yes"]
            target_probability = 0.001 if current_yes_probability > 0.5 else 0.999
            body = {
                "accountId": account_id,
                "idempotencyKey": f"idem-http-deplete-{index}",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": target_probability},
                "context": [],
            }

            status, payload = self.request("POST", market_path, body)
            if status == 201:
                risk_status, risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
                market_status, market_payload = self.request("GET", "/v1/markets/m1")
                events_status, events_payload = self.request("GET", "/v1/markets/m1/events")

                self.assertEqual(risk_status, 200)
                self.assertEqual(market_status, 200)
                self.assertEqual(events_status, 200)
                self.assertEqual(payload["result"]["status"], "accepted")
                self.assertEqual(market_payload["market"]["marginals"], payload["order"]["newMarginals"])
                self.assertEqual(events_payload["events"][-1]["eventId"], payload["result"]["eventId"])

                accepted_count += 1
                last_successful_risk_payload = risk_payload
                last_successful_market_payload = market_payload
                last_successful_events_payload = events_payload
                continue

            first_rejection_status = status
            first_rejection_payload = payload
            rejected_body = body
            break

        self.assertGreater(accepted_count, 0)
        self.assertIsNotNone(last_successful_risk_payload)
        self.assertIsNotNone(last_successful_market_payload)
        self.assertIsNotNone(last_successful_events_payload)
        self.assertIsNotNone(first_rejection_status, "expected deterministic unconditional rejection")
        self.assertIsNotNone(first_rejection_payload)
        self.assertIsNotNone(rejected_body)

        post_rejection_risk_status, post_rejection_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
        post_rejection_market_status, post_rejection_market_payload = self.request("GET", "/v1/markets/m1")
        post_rejection_events_status, post_rejection_events_payload = self.request("GET", "/v1/markets/m1/events")
        replay_status, replay_payload = self.request("POST", market_path, rejected_body)
        replay_risk_status, replay_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")
        replay_market_status, replay_market_payload = self.request("GET", "/v1/markets/m1")
        replay_events_status, replay_events_payload = self.request("GET", "/v1/markets/m1/events")

        self.assertEqual(first_rejection_status, 422)
        self.assertEqual(post_rejection_risk_status, 200)
        self.assertEqual(post_rejection_market_status, 200)
        self.assertEqual(post_rejection_events_status, 200)
        self.assertEqual(replay_status, 422)
        self.assertEqual(replay_risk_status, 200)
        self.assertEqual(replay_market_status, 200)
        self.assertEqual(replay_events_status, 200)
        self.assertEqual(first_rejection_payload["error"]["code"], "min_asset_violation")
        self.assertNotIn("result", first_rejection_payload)
        self.assertGreater(first_rejection_payload["error"]["details"]["impactScore"], 0.0)
        self.assertEqual(
            first_rejection_payload["error"]["details"]["beforeMinAsset"],
            last_successful_risk_payload["account"]["risk"]["minAssets"]["overall"],
        )
        self.assertLess(first_rejection_payload["error"]["details"]["afterMinAsset"], 0.0)
        self.assertEqual(post_rejection_risk_payload["account"]["risk"], last_successful_risk_payload["account"]["risk"])
        self.assertEqual(
            post_rejection_market_payload["market"]["marginals"],
            last_successful_market_payload["market"]["marginals"],
        )
        self.assertEqual(post_rejection_events_payload["events"], last_successful_events_payload["events"])
        self.assertEqual(post_rejection_events_payload["chain"], last_successful_events_payload["chain"])
        self.assertEqual(replay_payload["error"], first_rejection_payload["error"])
        self.assertNotIn("result", replay_payload)
        self.assertEqual(set(first_rejection_payload["meta"]), {"timestamp"})
        self.assertEqual(set(replay_payload["meta"]), {"timestamp"})
        self.assertEqual(replay_risk_payload["account"]["risk"], post_rejection_risk_payload["account"]["risk"])
        self.assertEqual(
            replay_market_payload["market"]["marginals"],
            post_rejection_market_payload["market"]["marginals"],
        )
        self.assertEqual(replay_events_payload["events"], post_rejection_events_payload["events"])
        self.assertEqual(replay_events_payload["chain"], post_rejection_events_payload["chain"])

    def test_probability_edit_http_accepts_zero_min_asset_boundary(self):
        preview_delta, exact_headroom = seed_exact_headroom_account("acct_http_edge")
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http_edge",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["result"]["status"], "accepted")
        self.assertEqual(payload["order"]["impactScore"], preview_delta["impactScore"])
        self.assertEqual(payload["order"]["impactScore"], exact_headroom)
        self.assertEqual(
            server.EVENTS[payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": "acct_http_edge",
                "marketId": "m1",
                "beforeMinAsset": exact_headroom,
                "afterMinAsset": 0.0,
            },
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.8, "no": 0.2})
        self.assertEqual(len(server.ORDERS), 1)

    def test_probability_edit_http_journals_conditional_bypass_after_zero_boundary_acceptance(self):
        account_id = "acct_http_conditional_bypass"
        _, setup_headroom = seed_exact_headroom_account(account_id, market_id="m2", probability=0.4)
        setup_status, setup_payload = self.request(
            "POST",
            "/v1/markets/m2/orders/probability-edit",
            {
                "accountId": account_id,
                "variableId": "btc_etf_approval_week",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.4},
                "context": [],
            },
        )
        setup_risk_status, setup_risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")

        counterfactual_body = build_unconditional_probability_edit_body(account_id, "m1", "yes", 0.8)
        counterfactual_normalized = server.normalize_probability_edit_payload("m1", counterfactual_body)
        counterfactual_preview = server.preview_unconditional_probability_edit("m1", counterfactual_normalized, account_id)
        conditional_context = [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}]
        conditional_status, conditional_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                **counterfactual_body,
                "context": conditional_context,
            },
        )
        events_status, events_payload = self.request("GET", "/v1/markets/m1/events")
        risk_status, risk_payload = self.request("GET", f"/v1/accounts/{account_id}/risk")

        self.assertEqual(setup_status, 201)
        self.assertEqual(setup_payload["order"]["impactScore"], setup_headroom)
        self.assertEqual(setup_risk_status, 200)
        self.assertEqual(setup_risk_payload["account"]["risk"]["minAssets"]["overall"], 0.0)
        self.assertEqual(
            server.EVENTS[setup_payload["result"]["eventId"]]["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
            0.0,
        )
        self.assertEqual(counterfactual_preview["assetDelta"]["beforeMinAsset"], 0.0)
        self.assertLess(counterfactual_preview["assetDelta"]["afterMinAsset"], 0.0)
        self.assertEqual(conditional_status, 201)
        self.assertEqual(conditional_payload["result"]["status"], "accepted")
        self.assertEqual(conditional_payload["order"]["payload"]["context"], conditional_context)
        self.assertEqual(conditional_payload["order"]["impactScore"], counterfactual_preview["assetDelta"]["impactScore"])
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(events_status, 200)
        self.assertEqual([event["seq"] for event in events_payload["events"]], [1])
        self.assertEqual(events_payload["events"][0], server.EVENTS[conditional_payload["result"]["eventId"]])
        self.assertEqual(events_payload["events"][0]["eventType"], "CommandAccepted")
        self.assertEqual(events_payload["events"][0]["payload"]["effects"]["marginalDelta"][0]["context"], conditional_context)
        self.assertEqual(
            events_payload["events"][0]["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": account_id,
                "marketId": "m1",
                "beforeMinAsset": 0.0,
                "afterMinAsset": counterfactual_preview["assetDelta"]["afterMinAsset"],
            },
        )
        self.assertEqual(events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(
            events_payload["chain"],
            {
                "genesisHash": server.GENESIS_EVENT_HASH,
                "headSeq": 1,
                "headHash": events_payload["events"][0]["eventHash"],
            },
        )
        self.assertEqual(
            events_payload["pagination"],
            {
                "fromSeq": 1,
                "limit": 100,
                "returned": 1,
                "nextFromSeq": None,
            },
        )
        self.assertEqual(risk_status, 200)
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            counterfactual_preview["assetDelta"]["afterMinAsset"],
        )
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["marketId"], "m1")
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)

    def test_probability_edit_http_accepts_non_empty_context(self):
        status, payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
            },
        )

        self.assertEqual(status, 201)
        self.assertEqual(
            payload["order"]["payload"]["context"],
            [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
        )
        self.assertEqual(server.MARKETS["m1"]["marginals"], {"yes": 0.65, "no": 0.35})
        self.assertEqual(
            server.COMMANDS[payload["order"]["commandId"]]["payload"]["context"],
            [{"variableId": "btc_etf_approval_week", "outcomeId": "yes"}],
        )

    def test_probability_edit_http_happy_path_updates_market_events_and_account_risk(self):
        post_status, post_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http_chain",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        market_status, market_payload = self.request("GET", "/v1/markets/m1")
        events_status, events_payload = self.request("GET", "/v1/markets/m1/events")
        risk_status, risk_payload = self.request("GET", "/v1/accounts/acct_http_chain/risk")

        self.assertEqual(post_status, 201)
        self.assertEqual(market_status, 200)
        self.assertEqual(events_status, 200)
        self.assertEqual(risk_status, 200)
        self.assertEqual(post_payload["result"]["status"], "accepted")
        self.assertEqual(market_payload["market"]["id"], "m1")
        self.assertEqual(market_payload["market"]["variableId"], "eth_price_gt_3000_mar15")
        self.assertEqual(market_payload["market"]["marginals"], post_payload["order"]["newMarginals"])
        self.assertEqual(events_payload["marketId"], "m1")
        self.assertEqual(events_payload["pagination"], {"fromSeq": 1, "limit": 100, "returned": 1, "nextFromSeq": None})
        self.assertEqual(events_payload["chain"]["genesisHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(events_payload["chain"]["headSeq"], 1)

        event = events_payload["events"][0]
        self.assertEqual(event["eventId"], post_payload["result"]["eventId"])
        self.assertEqual(event["commandId"], post_payload["order"]["commandId"])
        self.assertEqual(event["eventType"], "CommandAccepted")
        self.assertEqual(event["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(events_payload["chain"]["headHash"], event["eventHash"])
        self.assertEqual(
            event["payload"]["effects"]["marginalDelta"],
            [
                {
                    "variableId": "eth_price_gt_3000_mar15",
                    "outcomeId": "yes",
                    "before": 0.65,
                    "after": 0.8,
                }
            ],
        )
        self.assertEqual(
            event["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": "acct_http_chain",
                "marketId": "m1",
                "beforeMinAsset": 100.0,
                "afterMinAsset": risk_payload["account"]["risk"]["minAssets"]["overall"],
            },
        )
        self.assertEqual(
            event["payload"]["pricing"],
            {
                "cost": post_payload["order"]["impactScore"],
                "fee": 0.0,
            },
        )
        self.assertEqual(event["payload"]["replayStateHash"], server.market_replay_state_hash("m1"))
        self.assertEqual(risk_payload["account"]["id"], "acct_http_chain")
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - post_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["markets"],
            [
                {
                    "marketId": "m1",
                    "minAsset": round(100.0 - post_payload["order"]["impactScore"], 6),
                    "capacityConsumed": round(post_payload["order"]["impactScore"], 6),
                    "utilization": round(post_payload["order"]["impactScore"] / 100.0, 6),
                    "commandCount": 1,
                    "lastOrderId": post_payload["order"]["id"],
                    "lastCommandId": post_payload["order"]["commandId"],
                    "updatedAt": post_payload["order"]["filledAt"],
                }
            ],
        )

    def test_probability_edit_http_happy_path_accumulates_event_chain_and_risk_state(self):
        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http_chain",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http_chain",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.7},
                "context": [],
            },
        )
        market_status, market_payload = self.request("GET", "/v1/markets/m1")
        events_status, events_payload = self.request("GET", "/v1/markets/m1/events")
        risk_status, risk_payload = self.request("GET", "/v1/accounts/acct_http_chain/risk")

        first_after_min_asset = round(100.0 - first_payload["order"]["impactScore"], 6)
        second_after_min_asset = round(first_after_min_asset - second_payload["order"]["impactScore"], 6)

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(market_status, 200)
        self.assertEqual(events_status, 200)
        self.assertEqual(risk_status, 200)
        self.assertEqual(market_payload["market"]["marginals"], second_payload["order"]["newMarginals"])
        self.assertEqual([event["seq"] for event in events_payload["events"]], [1, 2])
        self.assertEqual(events_payload["chain"]["headSeq"], 2)
        self.assertEqual(events_payload["pagination"], {"fromSeq": 1, "limit": 100, "returned": 2, "nextFromSeq": None})
        self.assertEqual(events_payload["events"][0]["eventId"], first_payload["result"]["eventId"])
        self.assertEqual(events_payload["events"][1]["eventId"], second_payload["result"]["eventId"])
        self.assertEqual(events_payload["events"][0]["prevEventHash"], server.GENESIS_EVENT_HASH)
        self.assertEqual(
            events_payload["events"][1]["prevEventHash"],
            events_payload["events"][0]["eventHash"],
        )
        self.assertEqual(events_payload["chain"]["headHash"], events_payload["events"][1]["eventHash"])
        self.assertEqual(
            events_payload["events"][0]["payload"]["effects"]["assetDelta"][0]["afterMinAsset"],
            first_after_min_asset,
        )
        self.assertEqual(
            events_payload["events"][1]["payload"]["effects"]["assetDelta"][0],
            {
                "accountId": "acct_http_chain",
                "marketId": "m1",
                "beforeMinAsset": first_after_min_asset,
                "afterMinAsset": second_after_min_asset,
            },
        )
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["overall"], second_after_min_asset)
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["markets"],
            [
                {
                    "marketId": "m1",
                    "minAsset": second_after_min_asset,
                    "capacityConsumed": round(first_payload["order"]["impactScore"] + second_payload["order"]["impactScore"], 6),
                    "utilization": round(
                        (first_payload["order"]["impactScore"] + second_payload["order"]["impactScore"]) / 100.0,
                        6,
                    ),
                    "commandCount": 2,
                    "lastOrderId": second_payload["order"]["id"],
                    "lastCommandId": second_payload["order"]["commandId"],
                    "updatedAt": second_payload["order"]["filledAt"],
                }
            ],
        )

    def test_account_risk_http_reads_after_write(self):
        post_status, post_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            {
                "accountId": "acct_http",
                "variableId": "eth_price_gt_3000_mar15",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
                "context": [],
            },
        )
        status, payload = self.request("GET", "/v1/accounts/acct_http/risk")

        self.assertEqual(post_status, 201)
        self.assertEqual(status, 200)
        self.assertEqual(payload["account"]["id"], "acct_http")
        self.assertEqual(
            payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - post_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(
            payload["account"]["risk"]["capacityIndicators"]["consumed"],
            round(post_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(payload["account"]["risk"]["minAssets"]["markets"][0]["marketId"], "m1")
        self.assertEqual(payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)

    def test_account_risk_http_replayed_write_does_not_double_count_capacity(self):
        body = {
            "accountId": "acct_http",
            "idempotencyKey": "idem-http-risk",
            "variableId": "eth_price_gt_3000_mar15",
            "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.8},
            "context": [],
        }

        first_status, first_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        second_status, second_payload = self.request(
            "POST",
            "/v1/markets/m1/orders/probability-edit",
            body,
        )
        risk_status, risk_payload = self.request("GET", "/v1/accounts/acct_http/risk")

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(risk_status, 200)
        self.assertTrue(second_payload["meta"]["replayed"])
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["overall"],
            round(100.0 - first_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(
            risk_payload["account"]["risk"]["capacityIndicators"]["consumed"],
            round(first_payload["order"]["impactScore"], 6),
        )
        self.assertEqual(risk_payload["account"]["risk"]["minAssets"]["markets"][0]["commandCount"], 1)
        self.assertEqual(
            risk_payload["account"]["risk"]["minAssets"]["markets"][0]["lastCommandId"],
            first_payload["order"]["commandId"],
        )

    def test_account_risk_http_rejected_write_does_not_create_account_state(self):
        post_status, post_payload = self.request(
            "POST",
            "/v1/markets/m3/orders/probability-edit",
            {
                "accountId": "acct_http",
                "idempotencyKey": "idem-http-rejected",
                "variableId": "fed_rate_cut_mar_2026",
                "target": {"kind": "marginal", "outcomeId": "yes", "probability": 0.2},
                "context": [],
            },
        )
        status, payload = self.request("GET", "/v1/accounts/acct_http/risk")

        self.assertEqual(post_status, 409)
        self.assertEqual(post_payload["error"]["code"], "market_not_active")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "account_not_found")
        self.assertEqual(payload["error"]["details"]["accountId"], "acct_http")

    def test_account_risk_http_unknown_account_returns_structured_error(self):
        status, payload = self.request("GET", "/v1/accounts/acct_missing/risk")

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "account_not_found")
        self.assertEqual(payload["error"]["details"]["accountId"], "acct_missing")

    def test_account_risk_http_rejects_non_get_methods(self):
        status, payload = self.request("POST", "/v1/accounts/acct_http/risk", {})

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")
        self.assertEqual(payload["error"]["details"]["method"], "POST")
        self.assertEqual(payload["error"]["details"]["path"], "/v1/accounts/acct_http/risk")


if __name__ == "__main__":
    unittest.main()
