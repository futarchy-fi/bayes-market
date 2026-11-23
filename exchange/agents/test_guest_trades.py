"""Unit tests for scripts/dwarkesh/execute_guest_trades.py via httpx.MockTransport."""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from exchange.venues.joint.msr import stake_for_edit

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "dwarkesh"
    / "execute_guest_trades.py"
)


def _load_guest_trades_module():
    spec = importlib.util.spec_from_file_location("execute_guest_trades", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gt = _load_guest_trades_module()


class MockExchange:
    """Stateful fake futarchy-exchange using real log-MSR staking math."""

    def __init__(
        self,
        markets: dict[str, dict],
        *,
        admin_key: str = "admin-secret-key",
        default_b: Decimal = Decimal("50"),
    ) -> None:
        self.admin_key = admin_key
        self.default_b = default_b
        # market_id -> mutable market dict
        self.markets: dict[str, dict] = {
            mid: {
                "id": mid,
                "variableId": info["variableId"],
                "title": info.get("title", f"Market {mid}"),
                "status": info.get("status", "open"),
                "marginals": dict(info.get("marginals", {"yes": 0.5, "no": 0.5})),
                "b": Decimal(str(info.get("b", default_b))),
            }
            for mid, info in markets.items()
        }
        self.var_to_mid = {m["variableId"]: mid for mid, m in self.markets.items()}
        self.accounts: dict[str, dict] = {}       # username -> account record
        self.key_to_user: dict[str, str] = {}     # raw_api_key -> username
        self.next_account_id = 10
        self.next_order_id = 1
        self.requests: list[tuple[str, str, dict | None]] = []
        self.order_log: list[dict] = []
        self.preview_log: list[dict] = []

    def _auth_user(self, request: httpx.Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return self.key_to_user.get(auth[7:])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))

        if request.method == "GET" and path == "/v1/net/markets":
            return httpx.Response(200, json={
                "markets": [
                    {
                        "id": m["id"],
                        "variableId": m["variableId"],
                        "title": m["title"],
                        "status": m["status"],
                        "marginals": dict(m["marginals"]),
                        "liquidity": float(m["b"]),
                    }
                    for m in self.markets.values()
                ],
                "count": len(self.markets),
            })

        if request.method == "GET" and path.startswith("/v1/net/markets/"):
            mid = path.rsplit("/", 1)[-1]
            m = self.markets.get(mid)
            if m is None:
                return httpx.Response(404, json={"error": {"code": "unknown_market"}})
            return httpx.Response(200, json={
                "id": m["id"],
                "variableId": m["variableId"],
                "title": m["title"],
                "status": m["status"],
                "marginals": dict(m["marginals"]),
                "liquidity": float(m["b"]),
            })

        if request.method == "POST" and path == "/v1/admin/service-accounts":
            if request.headers.get("authorization") != f"Bearer {self.admin_key}":
                return httpx.Response(401, json={"error": {"code": "admin_required"}})
            username = body["username"]
            if username in self.accounts and not body.get("rotate_if_exists"):
                return httpx.Response(409, json={"error": {"code": "username_taken"}})
            raw_key = f"secret_key_{username}_{self.next_account_id}"
            if username in self.accounts:
                acc = self.accounts[username]
                self.key_to_user = {
                    k: u for k, u in self.key_to_user.items() if u != username
                }
                acc["api_key"] = raw_key
                self.key_to_user[raw_key] = username
            else:
                acc_id = self.next_account_id
                self.next_account_id += 1
                credits = Decimal(str(body.get("initial_credits") or "0"))
                acc = {
                    "account_id": acc_id,
                    "username": username,
                    "display_name": body.get("display_name"),
                    "is_service_account": body.get("is_service_account", True),
                    "initial": credits,
                    "available": credits,
                    "frozen": Decimal("0"),
                    "api_key": raw_key,
                }
                self.accounts[username] = acc
                self.key_to_user[raw_key] = username
            return httpx.Response(200, json={
                "account_id": acc["account_id"],
                "username": username,
                "api_key": acc["api_key"],
                "display_name": acc["display_name"],
                "is_service_account": acc["is_service_account"],
            })

        if request.method == "GET" and path == "/v1/me":
            username = self._auth_user(request)
            if not username:
                return httpx.Response(401, json={"error": {"code": "auth_required"}})
            acc = self.accounts[username]
            return httpx.Response(200, json={
                "account_id": acc["account_id"],
                "available": str(acc["available"]),
                "frozen": str(acc["frozen"]),
                "total": str(acc["available"] + acc["frozen"]),
            })

        if request.method == "POST" and path in ("/v1/net/orders/preview", "/v1/net/orders"):
            username = self._auth_user(request)
            if not username:
                return httpx.Response(401, json={"error": {"code": "auth_required"}})
            acc = self.accounts[username]
            var_id = body["variableId"]
            outcome_id = body["outcomeId"]
            target = float(body["target"])
            mid = self.var_to_mid.get(var_id)
            if mid is None:
                return httpx.Response(404, json={"error": {"code": "unknown_market"}})
            m = self.markets[mid]
            before = float(m["marginals"][outcome_id])
            stake = stake_for_edit(m["b"], before, target)

            if path == "/v1/net/orders/preview":
                self.preview_log.append({
                    "username": username,
                    "variableId": var_id,
                    "before": before,
                    "target": target,
                    "stake": str(stake),
                })
                return httpx.Response(200, json={
                    "stake": str(stake),
                    "before": before,
                    "after": target,
                    "b": str(m["b"]),
                })

            # Place order
            if stake > acc["available"]:
                return httpx.Response(400, json={"error": {"code": "insufficient_credits"}})
            acc["available"] -= stake
            acc["frozen"] += stake
            m["marginals"][outcome_id] = target
            if outcome_id == "yes" and "no" in m["marginals"]:
                m["marginals"]["no"] = round(1.0 - target, 6)
            order_id = f"ord-{self.next_order_id}"
            self.next_order_id += 1
            record = {
                "orderId": order_id,
                "accountId": acc["account_id"],
                "username": username,
                "variableId": var_id,
                "outcomeId": outcome_id,
                "target": target,
                "before": before,
                "after": target,
                "stake": str(stake),
                "status": "open",
                "balance": {
                    "available": str(acc["available"]),
                    "frozen": str(acc["frozen"]),
                },
            }
            self.order_log.append(record)
            return httpx.Response(200, json=record)

        return httpx.Response(404, json={"error": {"code": "not_found"}})


def test_round_robin_execution_and_shared_market_interaction(tmp_path):
    mock = MockExchange({
        "m1": {"variableId": "agi_2030", "title": "AGI by 2030", "marginals": {"yes": 0.40, "no": 0.60}, "b": 50},
        "m2": {"variableId": "compute_10x", "title": "10x Compute", "marginals": {"yes": 0.50, "no": 0.50}, "b": 50},
        "m3": {"variableId": "policy_bill", "title": "AI Policy Bill", "marginals": {"yes": 0.30, "no": 0.70}, "b": 50},
    })
    manifest = {
        "traders": [
            {
                "username": "guest_bull",
                "display_name": "Bullish Guest",
                "trades": [
                    {
                        "variable_id": "agi_2030",
                        "target_prob": 0.85,
                        "conviction": "high",
                        "rationale": "Scaling continues",
                        "quote": "We hit AGI by 2030.",
                    },
                    {
                        "variable_id": "compute_10x",
                        "target_prob": 0.80,
                        "conviction": "medium",
                        "rationale": "Capex surge",
                        "quote": "Clusters keep growing.",
                    },
                ],
            },
            {
                "username": "guest_bear",
                "display_name": "Skeptical Guest",
                "trades": [
                    {
                        "variable_id": "agi_2030",
                        "target_prob": 0.10,
                        "conviction": "high",
                        "rationale": "Data bottleneck",
                        "quote": "Not by 2030.",
                    },
                    {
                        "variable_id": "policy_bill",
                        "target_prob": 0.70,
                        "conviction": "low",
                        "rationale": "Congress acts",
                        "quote": "Likely legislation.",
                    },
                ],
            },
        ]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            execute=True,
        ),
        manifest_label="test_manifest.json",
        transport=httpx.MockTransport(mock),
    )

    # Exact round-robin order: round 0 (bull, bear), round 1 (bull, bear)
    order_seq = [(o["username"], o["variableId"]) for o in mock.order_log]
    assert order_seq == [
        ("guest_bull", "agi_2030"),
        ("guest_bear", "agi_2030"),
        ("guest_bull", "compute_10x"),
        ("guest_bear", "policy_bill"),
    ]

    # Bear in round 0 saw the live marginal moved by Bull (0.40 -> 0.54)
    bull_r0, bear_r0 = mock.order_log[0], mock.order_log[1]
    assert bull_r0["before"] == pytest.approx(0.40)
    assert bull_r0["after"] == pytest.approx(0.54)  # high alpha=0.5 * 0.45 = 0.225 clamped to +0.14
    assert bear_r0["before"] == pytest.approx(0.54)
    assert bear_r0["after"] == pytest.approx(0.40)  # high alpha=0.5 * -0.44 = -0.22 clamped to -0.14

    # Both accounts created with is_service_account=False and display_name
    assert mock.accounts["guest_bull"]["is_service_account"] is False
    assert mock.accounts["guest_bull"]["display_name"] == "Bullish Guest"
    assert mock.accounts["guest_bear"]["is_service_account"] is False
    assert mock.accounts["guest_bear"]["display_name"] == "Skeptical Guest"

    # Receipt schema and zero secret leakage
    assert receipt["dry_run"] is False
    assert receipt["summary"]["guests_created"] == 2
    assert receipt["summary"]["orders_placed"] == 4
    required_keys = {
        "guest_name", "username", "market_id", "variable_id", "title",
        "before", "after", "target_prob", "stake", "order_id",
        "conviction", "rationale", "quote",
    }
    for trade in receipt["trades"]:
        assert required_keys.issubset(trade.keys())

    receipt_path = tmp_path / "receipt.json"
    gt.write_receipt(receipt, receipt_path)
    raw_receipt_text = receipt_path.read_text(encoding="utf-8")
    summary_text = gt.format_summary(receipt)
    for acc in mock.accounts.values():
        assert acc["api_key"] not in raw_receipt_text
        assert acc["api_key"] not in summary_text
    assert "admin-secret-key" not in raw_receipt_text
    assert "admin-secret-key" not in summary_text


def test_stake_capping_and_eight_step_bisection_shrink():
    # High liquidity b=800: moving 0.50 -> 0.64 costs ~800 * ln(0.50 / 0.36) = ~262.8 > 120!
    mock = MockExchange({
        "m_hi": {"variableId": "high_liq", "title": "High Liquidity", "marginals": {"yes": 0.50, "no": 0.50}, "b": 800},
    })
    manifest = {
        "traders": [{
            "username": "guest_bisect",
            "display_name": "Bisection Guest",
            "trades": [{
                "variable_id": "high_liq",
                "target_prob": 0.90,
                "conviction": "high",
                "rationale": "Strong belief",
                "quote": "Very likely.",
            }],
        }]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            max_stake_per_trade=Decimal("120"),
            min_buffer=Decimal("100"),
            execute=True,
        ),
        transport=httpx.MockTransport(mock),
    )

    # 1 initial preview + 8 bisection previews = 9 previews total
    assert len(mock.preview_log) == 9
    assert Decimal(mock.preview_log[0]["stake"]) > Decimal("120")

    assert receipt["summary"]["orders_placed"] == 1
    placed = mock.order_log[0]
    stake = Decimal(placed["stake"])
    assert Decimal("0") < stake <= Decimal("120")
    # Should have found a near-maximal feasible move within 1/256 precision
    assert stake > Decimal("110")
    assert 0.508 <= placed["after"] < 0.64


def test_infeasible_stake_after_bisection_is_skipped():
    # Extreme liquidity b=50000: even a 0.008 move costs > 800 credits >> max_stake=120
    mock = MockExchange({
        "m_huge": {"variableId": "huge_liq", "marginals": {"yes": 0.50, "no": 0.50}, "b": 50000},
    })
    manifest = {
        "traders": [{
            "username": "guest_skip",
            "display_name": "Skipped Guest",
            "trades": [{
                "variable_id": "huge_liq",
                "target_prob": 0.90,
                "conviction": "high",
            }],
        }]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            max_stake_per_trade=Decimal("120"),
            execute=True,
        ),
        transport=httpx.MockTransport(mock),
    )

    assert receipt["summary"]["orders_placed"] == 0
    assert len(mock.order_log) == 0
    assert len(receipt["skipped"]) == 1
    assert receipt["skipped"][0]["reason"] in {
        "infeasible_stake",
        "step_too_small_after_bisection",
    }


def test_min_buffer_and_credit_conservation():
    # Guest starts with 300 credits, min_buffer=100 -> max spendable total is 200.
    # Each move on b=400 costs ~120 (bisected to <=120 on trade 1, <=80 on trade 2, 0 left on trades 3-5).
    mock = MockExchange({
        f"m{i}": {"variableId": f"v{i}", "marginals": {"yes": 0.50, "no": 0.50}, "b": 400}
        for i in range(5)
    })
    manifest = {
        "traders": [{
            "username": "guest_budget",
            "display_name": "Budgeted Guest",
            "initial_credits": "300",
            "trades": [
                {"variable_id": f"v{i}", "target_prob": 0.90, "conviction": "high"}
                for i in range(5)
            ],
        }]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            max_stake_per_trade=Decimal("120"),
            min_buffer=Decimal("100"),
            execute=True,
        ),
        transport=httpx.MockTransport(mock),
    )

    acc = mock.accounts["guest_budget"]
    # Credit conservation & buffer invariants
    assert acc["available"] >= Decimal("100")
    assert acc["available"] + acc["frozen"] == Decimal("300")

    stakes = [Decimal(t["stake"]) for t in receipt["trades"]]
    assert all(Decimal("0") < s <= Decimal("120") for s in stakes)
    assert sum(stakes, Decimal("0")) == acc["frozen"]
    assert Decimal(receipt["summary"]["total_volume"]) == acc["frozen"]

    guest_summary = receipt["summary"]["per_guest"][0]
    assert Decimal(guest_summary["total_staked"]) == acc["frozen"]
    assert Decimal(guest_summary["remaining_balance"]) == acc["available"]
    assert len(receipt["trades"]) >= 2
    assert len(receipt["skipped"]) >= 1


def test_deadband_missing_and_closed_markets_skipped():
    mock = MockExchange({
        "m_close": {"variableId": "v_close", "marginals": {"yes": 0.50, "no": 0.50}, "b": 50},
        "m_resolved": {"variableId": "v_resolved", "status": "resolved", "marginals": {"yes": 1.0, "no": 0.0}, "b": 50},
    })
    manifest = {
        "traders": [{
            "username": "guest_edge",
            "display_name": "Edge Guest",
            "trades": [
                {"variable_id": "v_close", "target_prob": 0.51, "conviction": "high"},       # |diff|=0.01 < 0.015
                {"variable_id": "v_missing", "target_prob": 0.80, "conviction": "high"},     # missing
                {"variable_id": "v_resolved", "target_prob": 0.20, "conviction": "high"},    # closed
            ],
        }]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            execute=True,
        ),
        transport=httpx.MockTransport(mock),
    )

    assert receipt["summary"]["orders_placed"] == 0
    assert len(mock.preview_log) == 0
    assert len(mock.order_log) == 0
    reasons = [s["reason"] for s in receipt["skipped"]]
    assert reasons == ["within_deadband", "market_not_found", "market_closed"]


def test_dry_run_makes_zero_post_requests():
    mock = MockExchange({
        "m1": {"variableId": "v1", "marginals": {"yes": 0.40, "no": 0.60}, "b": 50},
    })
    manifest = {
        "traders": [
            {
                "username": "g1",
                "display_name": "Guest One",
                "trades": [{"variable_id": "v1", "target_prob": 0.80, "conviction": "high"}],
            },
            {
                "username": "g2",
                "display_name": "Guest Two",
                "trades": [{"variable_id": "v1", "target_prob": 0.20, "conviction": "medium"}],
            },
        ]
    }

    # No admin_key required in dry-run!
    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(api_url="http://exchange.test", execute=False),
        transport=httpx.MockTransport(mock),
    )

    assert receipt["dry_run"] is True
    assert receipt["summary"]["guests_created"] == 0
    assert receipt["summary"]["orders_placed"] == 0
    assert receipt["summary"]["trades_planned"] == 2
    assert not any(method == "POST" for method, _path, _body in mock.requests)
    # Second simulated trade saw the simulated price updated by the first
    assert receipt["trades"][0]["before"] == pytest.approx(0.40)
    assert receipt["trades"][1]["before"] == pytest.approx(receipt["trades"][0]["after"])


def test_top_15_moves_capped_and_sorted():
    mock = MockExchange({
        f"m{i}": {"variableId": f"v{i}", "marginals": {"yes": 0.50, "no": 0.50}, "b": 20}
        for i in range(18)
    })
    # Give different target_probs so deltas are distinct
    trades = [
        {
            "variable_id": f"v{i}",
            "target_prob": min(0.95, 0.54 + i * 0.02),
            "conviction": "medium",
        }
        for i in range(18)
    ]
    manifest = {
        "traders": [{
            "username": "g_many",
            "display_name": "Many Trades Guest",
            "initial_credits": "5000",
            "trades": trades,
        }]
    }

    receipt = gt.run_guest_trades(
        manifest,
        gt.RunnerConfig(
            api_url="http://exchange.test",
            admin_key="admin-secret-key",
            execute=True,
        ),
        transport=httpx.MockTransport(mock),
    )

    assert receipt["summary"]["orders_placed"] == 18
    top_moves = receipt["summary"]["top_moves"]
    assert len(top_moves) == 15
    abs_deltas = [m["abs_delta"] for m in top_moves]
    assert abs_deltas == sorted(abs_deltas, reverse=True)
    summary = gt.format_summary(receipt)
    assert "Top 15 biggest probability moves:" in summary
    assert "Orders placed:   18" in summary


def test_end_to_end_against_real_exchange_app_and_leaderboard(tmp_path, monkeypatch):
    """Drive execute_guest_trades against the real FastAPI app + JointVenue."""
    import asyncio
    from httpx import ASGITransport, AsyncClient

    import exchange.core.api as api_module
    import exchange.core.middleware as mw
    from exchange.core.models import reset_counters
    from exchange.venues.joint.test_venue import TINY_SEEDS

    reset_counters()
    seeds_path = tmp_path / "seeds.json"
    seeds_path.write_text(json.dumps(TINY_SEEDS), encoding="utf-8")
    state_path = tmp_path / "e2e_state.json"

    monkeypatch.setenv("EXCHANGE_SEEDS_PATH", str(seeds_path))
    monkeypatch.setattr(api_module, "STATE_PATH", str(state_path))
    monkeypatch.setattr(mw, "ADMIN_KEY", "e2e-admin-key")
    mw.rate_limiter.buckets.clear()

    manifest = {
        "traders": [
            {
                "username": "dwarkesh_p1",
                "display_name": "Guest One",
                "trades": [
                    {
                        "variable_id": "gcx_a",
                        "target_prob": 0.85,
                        "conviction": "high",
                        "rationale": "Strong signal",
                        "quote": "Very bullish on A.",
                    },
                    {
                        "variable_id": "gcx_b",
                        "target_prob": 0.80,
                        "conviction": "medium",
                        "rationale": "Follow-on",
                        "quote": "B follows A.",
                    },
                ],
            },
            {
                "username": "dwarkesh_p2",
                "display_name": "Guest Two",
                "trades": [
                    {
                        "variable_id": "gcx_a",
                        "target_prob": 0.20,
                        "conviction": "medium",
                        "rationale": "Skeptical",
                        "quote": "More cautious on A.",
                    },
                ],
            },
        ]
    }

    loop = asyncio.new_event_loop()
    lifespan_cm = api_module.lifespan(api_module.app)
    async_client = AsyncClient(
        transport=ASGITransport(app=api_module.app),
        base_url="http://testserver",
    )
    loop.run_until_complete(lifespan_cm.__aenter__())
    loop.run_until_complete(async_client.__aenter__())
    try:
        def _dispatch(request: httpx.Request) -> httpx.Response:
            r = loop.run_until_complete(
                async_client.request(
                    request.method,
                    str(request.url.raw_path.decode("ascii")),
                    headers=dict(request.headers),
                    content=request.content,
                )
            )
            return httpx.Response(
                r.status_code,
                headers=dict(r.headers),
                content=r.content,
            )

        receipt = gt.run_guest_trades(
            manifest,
            gt.RunnerConfig(
                api_url="http://testserver",
                admin_key="e2e-admin-key",
                max_stake_per_trade=Decimal("120"),
                min_buffer=Decimal("100"),
                execute=True,
            ),
            transport=httpx.MockTransport(_dispatch),
        )

        assert receipt["summary"]["guests_created"] == 2
        assert receipt["summary"]["orders_placed"] == 3
        assert Decimal(receipt["summary"]["total_volume"]) > Decimal("0")

        lb = loop.run_until_complete(async_client.get("/v1/leaderboard"))
        assert lb.status_code == 200
        entries = lb.json()["entries"]
        by_login = {e["login"]: e for e in entries}
        assert "dwarkesh_p1" in by_login
        assert "dwarkesh_p2" in by_login
        assert by_login["dwarkesh_p1"]["displayName"] == "Guest One"
        assert by_login["dwarkesh_p1"]["netOrders"] == 2
        assert Decimal(by_login["dwarkesh_p1"]["netVolume"]) > Decimal("0")
        assert by_login["dwarkesh_p2"]["displayName"] == "Guest Two"
        assert by_login["dwarkesh_p2"]["netOrders"] == 1
        assert Decimal(by_login["dwarkesh_p2"]["netVolume"]) > Decimal("0")
        # Guest One placed 2 orders and Guest Two placed 1; both tie on total=1000
        # so Guest One (higher netVolume) ranks first.
        assert entries[0]["login"] == "dwarkesh_p1"
        assert entries[1]["login"] == "dwarkesh_p2"
    finally:
        loop.run_until_complete(async_client.__aexit__(None, None, None))
        loop.run_until_complete(lifespan_cm.__aexit__(None, None, None))
        loop.close()
