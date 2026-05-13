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
    assert by_code["600768"]["attribution_labels"] == ["bad_extra_buy"]


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
    assert by_code["300488"]["attribution_labels"] == ["drill_better"]


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
                "primary_reason": "drill bought a losing stock that historical replay did not buy",
                "evidence_json": {"blocked_reasons": ["cash"]},
            }
        ],
    )

    rows = db.list_profit_gap_attributions(10, 20)
    assert [row["stock_code"] for row in rows] == ["600768"]
    assert rows[0]["evidence_json"] == {"blocked_reasons": ["cash"]}


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
                            "execution_sizing_plan": {"primary_cap_reason": "recovery_probe_max_position_pct"},
                        },
                    }
                ]
            return []

        def replace_profit_gap_attributions(self, historical_run_id, drill_run_id, rows):
            self.persisted = (historical_run_id, drill_run_id, rows)

    db = FakeRunDB()

    rows = build_profit_gap_attributions_from_runs(db, historical_run_id=1, drill_run_id=2)

    assert rows[0]["stock_code"] == "301666"
    assert rows[0]["attribution_labels"] == ["size_too_small"]
    assert rows[0]["evidence_json"]["buy_tiers"] == ["strong_buy"]
    assert db.persisted[0:2] == (1, 2)
