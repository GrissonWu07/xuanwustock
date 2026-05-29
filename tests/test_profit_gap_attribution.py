from app.quant_sim.profit_gap_attribution import build_profit_gap_attributions, build_profit_gap_attributions_from_runs
from app.quant_sim.db import QuantSimReplayDB


def test_labels_size_too_small_when_entry_matches_but_amount_is_low():
    rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 41119.0,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 95156.0,
            }
        ],
        drill=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 18023.59,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 24321.29,
                "buy_tiers": ["strong_buy"],
                "lifecycle_gate_modes": ["recovery_probe_confirmed"],
            }
        ],
    )

    assert rows[0]["stock_code"] == "301666"
    assert rows[0]["attribution_labels"] == ["size_too_small"]
    assert rows[0]["primary_label"] == "size_too_small"
    assert rows[0]["sub_reason"] == "recovery_probe_cap"
    assert rows[0]["severity"] == "high"
    assert rows[0]["actionable"] is True
    assert rows[0]["recommended_action"]
    assert rows[0]["primary_reason"] == "entry matched but drill sizing was materially lower"


def test_labels_entry_too_late_and_bad_extra_buy():
    rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "300736",
                "stock_name": "百邦科技",
                "total_pnl": 10992.0,
                "first_buy_at": "2026-01-06T02:00:00Z",
                "first_buy_price": 16.06,
                "buy_amount": 96566.0,
            }
        ],
        drill=[
            {
                "stock_code": "300736",
                "stock_name": "百邦科技",
                "total_pnl": -1814.38,
                "first_buy_at": "2026-03-27T02:00:00Z",
                "first_buy_price": 22.92,
                "buy_amount": 22926.88,
            },
            {
                "stock_code": "600768",
                "stock_name": "宁波富邦",
                "total_pnl": -2996.98,
                "first_buy_at": "2026-02-24T02:00:00Z",
                "first_buy_price": 19.0,
                "buy_amount": 38011.4,
            },
        ],
    )

    by_code = {row["stock_code"]: row for row in rows}
    assert "entry_too_late" in by_code["300736"]["attribution_labels"]
    assert by_code["300736"]["sub_reason"] == "candidate_discovered_late"
    assert by_code["600768"]["attribution_labels"] == ["bad_extra_buy"]
    assert by_code["600768"]["sub_reason"] == "acceptable_exploration_loss"


def test_labels_repeat_probe_loss_sell_blocked_and_drill_better():
    rows = build_profit_gap_attributions(
        historical=[
            {"stock_code": "301183", "stock_name": "东田微", "total_pnl": -235.0, "first_buy_at": "2026-01-09T07:00:00Z", "first_buy_price": 154.0, "buy_amount": 154933.0},
            {"stock_code": "300488", "stock_name": "恒锋工具", "total_pnl": -2445.0, "first_buy_at": "2026-01-19T02:00:00Z", "first_buy_price": 21.0, "buy_amount": 80000.0},
        ],
        drill=[
            {
                "stock_code": "301183",
                "stock_name": "东田微",
                "total_pnl": -2648.08,
                "first_buy_at": "2026-01-22T07:00:00Z",
                "first_buy_price": 154.0,
                "buy_amount": 49658.89,
                "diagnostic_labels": ["repeat_probe_loss", "sell_blocked_or_late"],
            },
            {"stock_code": "300488", "stock_name": "恒锋工具", "total_pnl": 9150.89, "first_buy_at": "2026-02-26T02:00:00Z", "first_buy_price": 22.0, "buy_amount": 50000.0},
        ],
    )

    by_code = {row["stock_code"]: row for row in rows}
    assert "repeat_probe_loss" in by_code["301183"]["attribution_labels"]
    assert "sell_blocked_or_late" in by_code["301183"]["attribution_labels"]
    assert by_code["301183"]["primary_label"] == "sell_blocked_or_late"
    assert by_code["301183"]["sub_reason"] in {"hard_sell_not_executed", "sell_signal_late"}
    assert by_code["300488"]["attribution_labels"] == ["drill_better"]
    assert by_code["300488"]["actionable"] is False


def test_replay_db_replaces_and_lists_profit_gap_attributions(tmp_path):
    db = QuantSimReplayDB(tmp_path / "replay.db")
    first_rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 41119.0,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 95156.0,
            }
        ],
        drill=[
            {
                "stock_code": "301666",
                "stock_name": "大普微-UW",
                "total_pnl": 18023.59,
                "first_buy_at": "2026-04-28T02:00:00Z",
                "first_buy_price": 243.14,
                "buy_amount": 24321.29,
                "buy_tiers": ["strong_buy"],
            }
        ],
    )
    db.replace_profit_gap_attributions(10, 20, first_rows)

    rows = db.list_profit_gap_attributions(10, 20)
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "301666"
    assert rows[0]["attribution_labels"] == ["size_too_small"]
    assert rows[0]["primary_label"] == "size_too_small"
    assert rows[0]["sub_reason"] == "weak_or_normal_tier_cap"
    assert rows[0]["evidence_json"]["buy_tiers"] == ["strong_buy"]

    db.replace_profit_gap_attributions(
        10,
        20,
        [
            {
                "stock_code": "600768",
                "stock_name": "宁波富邦",
                "historical_total_pnl": 0,
                "drill_total_pnl": -2996.98,
                "pnl_gap": 2996.98,
                "attribution_labels": ["bad_extra_buy"],
                "primary_label": "bad_extra_buy",
                "sub_reason": "acceptable_exploration_loss",
                "severity": "medium",
                "actionable": True,
                "recommended_action": "Review extra drill-only buy before widening auto-entry.",
                "primary_reason": "drill bought a losing stock that historical replay did not buy",
                "evidence_json": {"blocked_reasons": ["cash"]},
                "historical_trade_path_json": [],
                "drill_trade_path_json": [],
                "entry_timeline_json": {},
                "sizing_cap_chain_json": [],
                "sell_diagnostics_json": [],
            }
        ],
    )

    rows = db.list_profit_gap_attributions(10, 20)
    assert [row["stock_code"] for row in rows] == ["600768"]
    assert rows[0]["evidence_json"] == {"blocked_reasons": ["cash"]}
    assert rows[0]["sub_reason"] == "acceptable_exploration_loss"
    assert rows[0]["actionable"] is True
    assert db.list_profit_gap_attributions(10, 20, label="bad_extra_buy")[0]["stock_code"] == "600768"
    assert db.list_profit_gap_attributions(10, 20, sub_reason="acceptable_exploration_loss")[0]["stock_code"] == "600768"
    assert db.list_profit_gap_attributions(10, 20, severity="medium")[0]["stock_code"] == "600768"
    assert db.list_profit_gap_attributions(10, 20, actionable=True)[0]["stock_code"] == "600768"
    assert db.list_profit_gap_attributions(10, 20, min_abs_gap=1000)[0]["stock_code"] == "600768"


def test_build_profit_gap_from_runs_uses_trades_positions_and_signal_diagnostics():
    class FakeRunDB:
        def __init__(self):
            self.persisted = None

        def get_sim_run_trades(self, run_id):
            if run_id == 1:
                return [
                    {
                        "id": 1,
                        "stock_code": "301666",
                        "stock_name": "大普微-UW",
                        "action": "BUY",
                        "executed_at": "2026-04-28T02:00:00Z",
                        "price": 243.14,
                        "net_amount": 95000,
                    },
                    {
                        "id": 2,
                        "stock_code": "301666",
                        "stock_name": "大普微-UW",
                        "action": "SELL",
                        "executed_at": "2026-05-08T02:00:00Z",
                        "price": 280,
                        "realized_pnl": 20000,
                    },
                ]
            return [
                {
                    "id": 3,
                    "stock_code": "301666",
                    "stock_name": "大普微-UW",
                    "action": "BUY",
                    "executed_at": "2026-04-28T02:00:00Z",
                    "price": 243.14,
                    "net_amount": 24000,
                }
            ]

        def get_sim_run_positions(self, run_id):
            return [{"stock_code": "301666", "stock_name": "大普微-UW", "unrealized_pnl": 1000 if run_id == 1 else 500}]

        def get_sim_run_signals(self, run_id, include_strategy_profile=False):
            if run_id == 2:
                return [
                    {
                        "stock_code": "301666",
                        "stock_name": "大普微-UW",
                        "action": "BUY",
                        "strategy_profile": {
                            "portfolio_execution_guard": {"buy_tier": "strong_buy"},
                            "lifecycle_gate": {"mode": "recovery_probe_confirmed"},
                            "execution_sizing_plan": {
                                "primary_cap_reason": "recovery_probe_max_position_pct",
                                "cap_chain": [{"cap": "recovery_probe_max_position_pct", "budget": 24000}],
                            },
                        },
                    }
                ]
            return []

        def list_sim_run_candidate_events(self, run_id, **kwargs):
            return {"items": [{"stock_code": "301666", "checkpoint_at": "2026-04-28 10:00:00", "source_type": "manual_seed", "status": "consumed"}]}

        def list_sim_run_quant_events(self, run_id, **kwargs):
            return {"items": [{"stock_code": "301666", "checkpoint_at": "2026-04-28 10:00:00", "from_status": "cooling", "to_status": "trial", "reason_code": "cooling_review_confirmed"}]}

        def list_sim_run_quant_states(self, run_id, **kwargs):
            return {"items": [{"stock_code": "301666", "checkpoint_at": "2026-04-28 10:00:00", "quant_status": "trial", "health_score": 75}]}

        def replace_profit_gap_attributions(self, historical_run_id, drill_run_id, rows):
            self.persisted = (historical_run_id, drill_run_id, rows)

    db = FakeRunDB()

    rows = build_profit_gap_attributions_from_runs(db, historical_run_id=1, drill_run_id=2)

    assert rows[0]["stock_code"] == "301666"
    assert rows[0]["attribution_labels"] == ["size_too_small"]
    assert rows[0]["evidence_json"]["buy_tiers"] == ["strong_buy"]
    assert rows[0]["sizing_cap_chain_json"] == [{"cap": "recovery_probe_max_position_pct", "budget": 24000}]
    assert rows[0]["historical_trade_path_json"][0]["action"] == "BUY"
    assert rows[0]["drill_trade_path_json"][0]["action"] == "BUY"
    assert db.persisted[0:2] == (1, 2)


def test_large_gap_unclassified_gets_missing_evidence_sub_reason():
    rows = build_profit_gap_attributions(
        historical=[
            {
                "stock_code": "300106",
                "stock_name": "西部牧业",
                "total_pnl": 2000.0,
                "first_buy_at": "2026-01-09T02:00:00Z",
                "first_buy_price": 8.0,
                "buy_amount": 20000.0,
            }
        ],
        drill=[
            {
                "stock_code": "300106",
                "stock_name": "西部牧业",
                "total_pnl": 0.0,
                "first_buy_at": "2026-01-09T02:00:00Z",
                "first_buy_price": 8.0,
                "buy_amount": 20000.0,
            }
        ],
    )

    assert rows[0]["pnl_gap"] == 2000.0
    assert rows[0]["attribution_labels"] != ["unclassified"]
    assert rows[0]["primary_label"] == "same_entry_exit_gap"
    assert rows[0]["sub_reason"] == "same_entry_exit_gap"
