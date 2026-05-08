import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db.bootstrap import bootstrap_database_runtime
from app.quant_kernel.config import StrategyScoringConfig
from app.quant_sim.db import QuantSimDB, QuantSimReplayDB


def _resolve_profile(payload: dict, profile_kind: str) -> dict:
    scoring = StrategyScoringConfig(
        schema_version=str(payload["schema_version"]),
        base=payload["base"],
        profiles=payload["profiles"],
    )
    return scoring.resolve(profile_kind)


def _piecewise_score(value: float, bands: list[float], scores: list[float]) -> float:
    idx = 0
    for band in bands:
        if value <= band:
            break
        idx += 1
    idx = min(idx, len(scores) - 1)
    return float(scores[idx])


def _table_names(db_file) -> set[str]:
    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def test_quant_sim_db_does_not_create_historical_replay_tables(tmp_path):
    db_file = tmp_path / "quant_sim.db"

    QuantSimDB(db_file)

    tables = _table_names(db_file)
    assert "strategy_signals" in tables
    assert "sim_trades" in tables
    assert "sim_positions" in tables
    assert not any(name.startswith("sim_run_") for name in tables)
    assert "sim_runs" not in tables


def test_quant_sim_db_does_not_clean_legacy_historical_replay_tables(tmp_path):
    db_file = tmp_path / "quant_sim.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("CREATE TABLE sim_runs (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE sim_run_signals (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE sim_run_signal_details (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    QuantSimDB(db_file)

    tables = _table_names(db_file)
    assert "sim_runs" in tables
    assert "sim_run_signals" in tables
    assert "sim_run_signal_details" in tables


def test_quant_replay_db_only_creates_replay_tables(tmp_path):
    db_file = tmp_path / "quant_sim_replay.db"

    QuantSimReplayDB(db_file)

    assert _table_names(db_file) == {
        "sim_runs",
        "sim_run_checkpoints",
        "sim_run_events",
        "sim_run_trades",
        "sim_run_snapshots",
        "sim_run_positions",
        "sim_run_signals",
        "sim_run_signal_details",
    }


def test_quant_replay_db_resolves_runtime_replay_store_path(tmp_path):
    runtime = bootstrap_database_runtime({}, data_dir=tmp_path)

    db = QuantSimReplayDB(db_runtime=runtime)

    assert Path(db.db_file) == runtime.replay_path


def test_quant_replay_db_write_batch_defers_inner_commits(tmp_path):
    db_file = tmp_path / "quant_sim_replay.db"
    db = QuantSimReplayDB(db_file, pin_connection=True)

    with db.write_batch():
        run_id = db.create_sim_run(
            mode="historical_range",
            timeframe="30m",
            market="CN",
            start_datetime="2026-04-01 09:30:00",
            end_datetime="2026-04-01 15:00:00",
            initial_cash=50000,
            status="running",
        )
        reader = sqlite3.connect(db_file)
        try:
            visible_count = reader.execute("SELECT COUNT(*) FROM sim_runs WHERE id = ?", (run_id,)).fetchone()[0]
        finally:
            reader.close()

        assert visible_count == 0

    reader = sqlite3.connect(db_file)
    try:
        committed_count = reader.execute("SELECT COUNT(*) FROM sim_runs WHERE id = ?", (run_id,)).fetchone()[0]
    finally:
        reader.close()

    assert committed_count == 1


def test_quant_db_reuses_initialized_schema_when_database_is_locked(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    QuantSimDB(db_file)

    lock_conn = sqlite3.connect(db_file, timeout=0.1)
    try:
        lock_conn.execute("BEGIN EXCLUSIVE")

        QuantSimDB(db_file)
    finally:
        lock_conn.rollback()
        lock_conn.close()


def test_quant_db_skips_schema_init_for_existing_locked_database(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    QuantSimDB(db_file)
    cache_key = QuantSimDB._cache_key(db_file)
    QuantSimDB._initialized_db_files.discard(cache_key)

    lock_conn = sqlite3.connect(db_file, timeout=0.1)
    try:
        lock_conn.execute("BEGIN EXCLUSIVE")

        QuantSimDB(db_file)
    finally:
        lock_conn.rollback()
        lock_conn.close()


def test_quant_db_enables_wal_for_file_database(tmp_path):
    db_file = tmp_path / "app.quant_sim.db"
    db = QuantSimDB(db_file)

    conn = db._connect()  # noqa: SLF001 - verifies persistence mode on the real connection
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    assert journal_mode.lower() == "wal"


def test_add_signal_sets_created_and_updated_at_as_utc_iso_z(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "HOLD",
            "confidence": 70,
            "reasoning": "观察",
            "position_size_pct": 0,
            "status": "observed",
        }
    )
    signal = db.get_signals(limit=1)[0]

    assert signal["id"] == signal_id
    assert signal["created_at"] == signal["updated_at"]
    assert signal["created_at"].endswith("Z")
    assert "T" in signal["created_at"]
    parsed = datetime.fromisoformat(signal["created_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo == timezone.utc


def test_quant_db_reads_during_uncommitted_writer_in_wal_mode(tmp_path):
    db_file = tmp_path / "quant_sim_replay.db"
    db = QuantSimReplayDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-01 15:00:00",
        initial_cash=50000,
        status="running",
    )

    writer = sqlite3.connect(db_file, timeout=0.1)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute("UPDATE sim_runs SET status = ? WHERE id = ?", ("running", run_id))

        rows = db.get_sim_runs(limit=1)
    finally:
        writer.rollback()
        writer.close()

    assert rows[0]["id"] == run_id


def test_add_candidate_records_source_and_status(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    candidate_id = db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "main_force",
            "latest_price": 10.52,
        }
    )

    rows = db.get_candidates()

    assert candidate_id > 0
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600000"
    assert rows[0]["stock_name"] == "浦发银行"
    assert rows[0]["source"] == "main_force"
    assert rows[0]["status"] == "active"
    assert rows[0]["sources"] == ["main_force"]


def test_add_candidate_preserves_multiple_sources(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "main_force",
            "latest_price": 10.52,
        }
    )
    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "value_stock",
            "latest_price": 10.88,
        }
    )

    rows = db.get_candidates()

    assert len(rows) == 1
    assert rows[0]["source"] == "main_force"
    assert rows[0]["latest_price"] == 10.88
    assert rows[0]["sources"] == ["main_force", "value_stock"]


def test_delete_candidate_removes_candidate(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.add_candidate(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "source": "main_force",
            "latest_price": 10.52,
        }
    )

    db.delete_candidate("600000")

    assert db.get_candidate("600000") is None
    assert db.get_candidates() == []


def test_scheduler_config_persists_strategy_mode(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    config = db.get_scheduler_config()
    assert config["strategy_mode"] == "auto"

    db.update_scheduler_config(strategy_mode="defensive")
    config = db.get_scheduler_config()
    assert config["strategy_mode"] == "defensive"


def test_builtin_strategy_profiles_rebalance_fusion_gates_by_strategy(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    configs = db._build_builtin_strategy_profile_configs()
    aggressive_position = _resolve_profile(configs["aggressive"], "position")
    stable_candidate = _resolve_profile(configs["stable"], "candidate")
    stable_position = _resolve_profile(configs["stable"], "position")
    conservative_candidate = _resolve_profile(configs["conservative"], "candidate")
    conservative_position = _resolve_profile(configs["conservative"], "position")

    assert configs["aggressive"]["profiles"]["candidate"]["dual_track"]["fusion_buy_threshold"] == 0.35
    assert configs["aggressive"]["profiles"]["candidate"]["dual_track"]["fusion_sell_threshold"] == -0.30
    assert aggressive_position["dual_track"]["fusion_buy_threshold"] == 0.50
    assert aggressive_position["dual_track"]["min_fusion_confidence"] == 0.42

    assert stable_candidate["dual_track"]["fusion_buy_threshold"] == 0.43
    assert stable_candidate["dual_track"]["min_fusion_confidence"] == 0.46
    assert stable_position["dual_track"]["fusion_buy_threshold"] == 0.57
    assert stable_position["dual_track"]["min_fusion_confidence"] == 0.50

    assert conservative_candidate["dual_track"]["track_weights"] == {"tech": 0.9, "context": 1.1}
    assert conservative_candidate["dual_track"]["fusion_buy_threshold"] == 0.48
    assert conservative_candidate["dual_track"]["min_fusion_confidence"] == 0.56
    assert conservative_candidate["dual_track"]["min_tech_score_for_buy"] == 0.05
    assert conservative_candidate["dual_track"]["min_context_score_for_buy"] == 0.03
    assert conservative_candidate["dual_track"]["min_tech_confidence_for_buy"] == 0.54
    assert conservative_candidate["dual_track"]["min_context_confidence_for_buy"] == 0.56
    assert conservative_position["dual_track"]["fusion_buy_threshold"] == 0.58
    assert conservative_position["dual_track"]["min_fusion_confidence"] == 0.60


def test_builtin_strategy_profiles_tier_profit_protection_by_risk_style(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    configs = db._build_builtin_strategy_profile_configs()
    aggressive = _resolve_profile(configs["aggressive"], "position")["veto"]["profit_protection"]
    stable = _resolve_profile(configs["stable"], "position")["veto"]["profit_protection"]
    conservative = _resolve_profile(configs["conservative"], "position")["veto"]["profit_protection"]

    assert aggressive["tech_sell_peak_pct"] == 50.0
    assert aggressive["tech_sell_drawdown_pct"] == 15.0
    assert aggressive["hard_trailing_peak_pct"] == 80.0
    assert aggressive["hard_trailing_drawdown_pct"] == 25.0

    assert stable["tech_sell_peak_pct"] == 30.0
    assert stable["tech_sell_drawdown_pct"] == 10.0
    assert stable["hard_trailing_peak_pct"] == 50.0
    assert stable["hard_trailing_drawdown_pct"] == 18.0

    assert conservative["tech_sell_peak_pct"] == 20.0
    assert conservative["tech_sell_drawdown_pct"] == 6.0
    assert conservative["hard_trailing_peak_pct"] == 35.0
    assert conservative["hard_trailing_drawdown_pct"] == 12.0


def test_builtin_strategy_profiles_tier_stock_execution_feedback_policy(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    configs = db._build_builtin_strategy_profile_configs()
    aggressive = configs["aggressive"]["base"]["context"]["stock_execution_feedback_policy"]
    stable = configs["stable"]["base"]["context"]["stock_execution_feedback_policy"]
    conservative = configs["conservative"]["base"]["context"]["stock_execution_feedback_policy"]

    assert aggressive["lookback_days"] >= 20
    assert aggressive["lookback_days"] < stable["lookback_days"] < conservative["lookback_days"]
    assert aggressive["loss_reentry_size_multiplier"] > stable["loss_reentry_size_multiplier"] > conservative["loss_reentry_size_multiplier"]
    assert aggressive["stop_loss_cooldown_days"] < stable["stop_loss_cooldown_days"] < conservative["stop_loss_cooldown_days"]


def test_builtin_strategy_profiles_tier_portfolio_execution_guard_policy(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    configs = db._build_builtin_strategy_profile_configs()
    aggressive = configs["aggressive"]["base"]["context"]["portfolio_execution_guard_policy"]
    stable = configs["stable"]["base"]["context"]["portfolio_execution_guard_policy"]
    conservative = configs["conservative"]["base"]["context"]["portfolio_execution_guard_policy"]

    assert aggressive["weak_edge_abs"] < stable["weak_edge_abs"] < conservative["weak_edge_abs"]
    assert aggressive["confirm_checkpoints"] < stable["confirm_checkpoints"] <= conservative["confirm_checkpoints"]
    assert aggressive["max_new_buys_per_checkpoint"] > stable["max_new_buys_per_checkpoint"] == conservative["max_new_buys_per_checkpoint"]
    assert aggressive["cooldown_size_multiplier"] > stable["cooldown_size_multiplier"] > conservative["cooldown_size_multiplier"]
    assert aggressive["loss_budget_pct"] < stable["loss_budget_pct"] < conservative["loss_budget_pct"]


def test_aggressive_candidate_profile_downweights_low_value_missing_dimensions(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    aggressive_candidate = _resolve_profile(db._build_builtin_strategy_profile_configs()["aggressive"], "candidate")
    context_weights = aggressive_candidate["context"]["dimension_weights"]
    technical_weights = aggressive_candidate["technical"]["dimension_weights"]

    assert context_weights["account_posture"] == 0.05
    assert context_weights["execution_feedback"] == 0.05
    assert technical_weights["kdj_cross"] == 0.35
    assert technical_weights["obv_trend"] > technical_weights["kdj_cross"]
    assert technical_weights["ma_slope"] > technical_weights["ma_alignment"]
    assert technical_weights["atr_risk"] > technical_weights["boll_position"]


def test_aggressive_profile_relaxes_upper_boll_penalty_while_other_profiles_stay_defensive(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    configs = db._build_builtin_strategy_profile_configs()
    boll_position_value = 0.838634

    aggressive_candidate = _resolve_profile(configs["aggressive"], "candidate")
    aggressive_position = _resolve_profile(configs["aggressive"], "position")
    stable_candidate = _resolve_profile(configs["stable"], "candidate")
    conservative_candidate = _resolve_profile(configs["conservative"], "candidate")

    aggressive_candidate_params = aggressive_candidate["technical"]["scorers"]["boll_position"]["params"]
    aggressive_position_params = aggressive_position["technical"]["scorers"]["boll_position"]["params"]
    stable_candidate_params = stable_candidate["technical"]["scorers"]["boll_position"]["params"]
    conservative_candidate_params = conservative_candidate["technical"]["scorers"]["boll_position"]["params"]

    assert _piecewise_score(
        boll_position_value,
        aggressive_candidate_params["position_bands"],
        aggressive_candidate_params["position_scores"],
    ) == 0.35
    assert _piecewise_score(
        boll_position_value,
        aggressive_position_params["position_bands"],
        aggressive_position_params["position_scores"],
    ) == 0.35
    assert _piecewise_score(
        boll_position_value,
        stable_candidate_params["position_bands"],
        stable_candidate_params["position_scores"],
    ) == -0.6
    assert _piecewise_score(
        boll_position_value,
        conservative_candidate_params["position_bands"],
        conservative_candidate_params["position_scores"],
    ) == -0.6


def test_confirm_buy_creates_simulated_position(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 78,
            "reasoning": "趋势改善",
            "status": "pending",
        }
    )

    db.confirm_signal(
        signal_id,
        executed_action="buy",
        price=10.5,
        quantity=100,
        note="手工买入",
    )

    positions = db.get_positions()
    signals = db.get_signals(stock_code="600000")

    assert len(positions) == 1
    assert positions[0]["stock_code"] == "600000"
    assert positions[0]["quantity"] == 100
    assert positions[0]["avg_price"] == 10.5
    assert signals[0]["status"] == "executed"
    assert signals[0]["execution_note"] == "手工买入"


def test_apply_stock_dividend_adjusts_open_lots_cost_and_cash(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000)
    signal_id = db.add_signal(
        {
            "stock_code": "300857",
            "stock_name": "协创数据",
            "action": "BUY",
            "confidence": 90,
            "reasoning": "seed",
            "status": "pending",
        }
    )
    db.confirm_signal(signal_id, executed_action="buy", price=99.12, quantity=600, note="seed", executed_at="2025-04-11 13:30:00")

    applied = db.apply_corporate_action(
        stock_code="300857",
        ex_date="2025-05-12",
        record_date="2025-05-09",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.293,
        description="10转4股派2.93元",
        applied_at="2025-05-12 10:00:00",
    )

    assert applied is True
    position = next(item for item in db.get_positions() if item["stock_code"] == "300857")
    lots = db.get_position_lots("300857", as_of="2025-05-12 10:00:00")
    summary = db.get_account_summary()

    assert position["quantity"] == 840
    assert lots[0]["remaining_quantity"] == 840
    assert lots[0]["entry_price"] == 70.5907
    assert summary["available_cash"] == 40703.8

    assert db.apply_corporate_action(
        stock_code="300857",
        ex_date="2025-05-12",
        record_date="2025-05-09",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.293,
        description="duplicate",
        applied_at="2025-05-12 10:30:00",
    ) is False
    assert next(item for item in db.get_positions() if item["stock_code"] == "300857")["quantity"] == 840


def test_stock_dividend_only_applies_to_lots_held_on_record_date(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000)
    first_signal = db.add_signal({"stock_code": "300857", "stock_name": "协创数据", "action": "BUY", "status": "pending"})
    second_signal = db.add_signal({"stock_code": "300857", "stock_name": "协创数据", "action": "BUY", "status": "pending"})
    db.confirm_signal(first_signal, executed_action="buy", price=99.12, quantity=600, note="eligible", executed_at="2025-05-09 14:30:00")
    db.confirm_signal(second_signal, executed_action="buy", price=80.60, quantity=100, note="ineligible", executed_at="2025-05-12 10:30:00")

    db.apply_corporate_action(
        stock_code="300857",
        ex_date="2025-05-12",
        record_date="2025-05-09",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.293,
        description="10转4股派2.93元",
        applied_at="2025-05-12 11:00:00",
    )

    lots = db.get_position_lots("300857", as_of="2025-05-12 11:00:00")
    position = next(item for item in db.get_positions() if item["stock_code"] == "300857")

    assert [lot["remaining_quantity"] for lot in lots] == [840, 100]
    assert position["quantity"] == 940


def test_stock_dividend_does_not_adjust_position_when_no_lot_is_eligible(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000)
    signal_id = db.add_signal({"stock_code": "300857", "stock_name": "协创数据", "action": "BUY", "status": "pending"})
    db.confirm_signal(signal_id, executed_action="buy", price=80.60, quantity=100, note="after record", executed_at="2025-05-12 10:30:00")
    before = next(item for item in db.get_positions() if item["stock_code"] == "300857")

    db.apply_corporate_action(
        stock_code="300857",
        ex_date="2025-05-12",
        record_date="2025-05-09",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.293,
        description="10转4股派2.93元",
        applied_at="2025-05-12 11:00:00",
    )

    after = next(item for item in db.get_positions() if item["stock_code"] == "300857")
    lots = db.get_position_lots("300857", as_of="2025-05-12 11:00:00")

    assert lots[0]["remaining_quantity"] == 100
    assert after["quantity"] == before["quantity"]
    assert after["latest_price"] == before["latest_price"]
    assert after["avg_price"] == before["avg_price"]


def test_stock_dividend_adjusts_slot_allocation_from_unreleased_quantity(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000)
    buy_signal = db.add_signal({"stock_code": "300857", "stock_name": "协创数据", "action": "BUY", "status": "pending"})
    sell_signal = db.add_signal({"stock_code": "300857", "stock_name": "协创数据", "action": "SELL", "status": "pending"})
    db.confirm_signal(buy_signal, executed_action="buy", price=99.12, quantity=600, note="seed", executed_at="2025-05-09 14:30:00")
    db.confirm_signal(sell_signal, executed_action="sell", price=100.0, quantity=300, note="partial", executed_at="2025-05-12 10:00:00")

    db.apply_corporate_action(
        stock_code="300857",
        ex_date="2025-05-12",
        record_date="2025-05-09",
        bonus_share_ratio=0.4,
        cash_dividend_per_share=0.293,
        description="10转4股派2.93元",
        applied_at="2025-05-12 10:00:00",
    )

    lots = db.get_position_lots("300857", as_of="2025-05-12 10:00:00")
    allocations = db.get_lot_slot_allocations("300857")

    assert lots[0]["remaining_quantity"] == 420
    assert sum(int(item["allocated_quantity"] or 0) for item in allocations) == 720
    assert sum(int(item["released_quantity"] or 0) for item in allocations) == 300


def test_position_market_price_tracks_unrealized_peak_without_lowering_it(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 78,
            "reasoning": "趋势改善",
            "status": "pending",
        }
    )
    db.confirm_signal(signal_id, executed_action="buy", price=10.0, quantity=100, note="建仓")

    db.update_position_market_price("600000", 15.0)
    first = db.get_positions()[0]
    assert first["peak_price"] == 15.0
    assert first["peak_unrealized_pnl_pct"] == 50.0
    assert first["peak_unrealized_pnl"] == 500.0
    assert first["peak_at"]

    db.update_position_market_price("600000", 13.0)
    second = db.get_positions()[0]
    assert second["latest_price"] == 13.0
    assert second["unrealized_pnl_pct"] == 30.0
    assert second["peak_price"] == 15.0
    assert second["peak_unrealized_pnl_pct"] == 50.0
    assert second["peak_unrealized_pnl"] == 500.0


def test_add_position_recomputes_historical_peak_without_lowering_it(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    first_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 78,
            "reasoning": "建仓",
            "status": "pending",
        }
    )
    db.confirm_signal(first_signal_id, executed_action="buy", price=10.0, quantity=100, note="建仓")
    db.update_position_market_price("600000", 20.0)

    second_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 78,
            "reasoning": "加仓",
            "status": "pending",
        }
    )
    db.confirm_signal(second_signal_id, executed_action="buy", price=12.0, quantity=100, note="加仓")

    position = db.get_positions()[0]

    assert position["quantity"] == 200
    assert position["avg_price"] == 11.0
    assert position["latest_price"] == 12.0
    assert position["unrealized_pnl_pct"] == 9.0909
    assert position["peak_price"] == 20.0
    assert position["peak_unrealized_pnl_pct"] == 81.8182
    assert position["peak_unrealized_pnl"] == 1800.0


def test_account_summary_and_trade_history_track_cash_and_realized_pnl(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")

    buy_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "建仓",
            "status": "pending",
        }
    )
    db.confirm_signal(
        buy_signal_id,
        executed_action="buy",
        price=10.0,
        quantity=100,
        note="首次建仓",
        executed_at="2026-04-09 10:00:00",
    )

    after_buy = db.get_account_summary()
    trades_after_buy = db.get_trade_history()

    assert after_buy["initial_cash"] == 100000.0
    assert after_buy["available_cash"] == 99000.0
    assert after_buy["market_value"] == 1000.0
    assert after_buy["total_equity"] == 100000.0
    assert after_buy["realized_pnl"] == 0.0
    assert len(trades_after_buy) == 1
    assert trades_after_buy[0]["action"] == "buy"
    assert trades_after_buy[0]["amount"] == 1000.0

    sell_signal_id = db.add_signal(
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "SELL",
            "confidence": 78,
            "reasoning": "止盈",
            "status": "pending",
        }
    )
    db.confirm_signal(
        sell_signal_id,
        executed_action="sell",
        price=12.0,
        quantity=100,
        note="全部卖出",
        executed_at="2026-04-10 10:00:00",
    )

    after_sell = db.get_account_summary()
    trades_after_sell = db.get_trade_history()

    assert after_sell["available_cash"] == 100200.0
    assert after_sell["market_value"] == 0.0
    assert after_sell["total_equity"] == 100200.0
    assert after_sell["realized_pnl"] == 200.0
    assert len(trades_after_sell) == 2
    assert trades_after_sell[0]["action"] == "sell"
    assert trades_after_sell[0]["realized_pnl"] == 200.0


def test_finalize_cancelled_run_preserves_completed_progress(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="running",
        progress_current=2,
        progress_total=176,
        status_message="正在执行",
    )

    db.finalize_sim_run(
        run_id,
        status="cancelled",
        final_equity=100000.0,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        win_rate=0.0,
        trade_count=0,
        status_message="回放任务已取消",
    )

    run = db.get_sim_run(run_id)

    assert run is not None
    assert run["status"] == "cancelled"
    assert run["progress_current"] == 2
    assert run["progress_total"] == 176


def test_replace_sim_run_results_persists_strategy_signals(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="completed",
    )

    db.replace_sim_run_results(
        run_id,
        trades=[
            {
                "signal_id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "price": 10.0,
                "quantity": 100,
                "amount": 1000.0,
                "realized_pnl": 0.0,
                "executed_at": "2026-04-01 10:00:00",
            }
        ],
        snapshots=[],
        positions=[],
        signals=[
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "回放策略买入",
                "position_size_pct": 60.0,
                "decision_type": "dual_track_resonance",
                "tech_score": 0.72,
                "context_score": 0.28,
                "strategy_profile": {
                    "market_regime": {"label": "牛市"},
                    "fundamental_quality": {"label": "强基本面"},
                    "risk_style": {"label": "激进"},
                    "analysis_timeframe": {"key": "30m"},
                },
                "checkpoint_at": "2026-04-01 10:00:00",
                "created_at": "2026-04-01 10:00:01",
            }
        ],
    )

    signals = db.get_sim_run_signals(run_id)
    signal_detail = db.get_sim_run_signal(signals[0]["id"])
    trades = db.get_sim_run_trades(run_id)

    assert len(signals) == 1
    assert signals[0]["stock_code"] == "300390"
    assert signals[0]["action"] == "BUY"
    assert signals[0]["status"] == "observed"
    assert signals[0]["updated_at"] == "2026-04-01 10:00:01"
    assert signals[0]["strategy_profile"] == {}
    assert signal_detail["strategy_profile"]["risk_style"]["label"] == "激进"
    assert signals[0]["checkpoint_at"] == "2026-04-01 10:00:00"
    assert len(trades) == 1
    assert trades[0]["signal_id"] == signals[0]["id"]


def test_replace_sim_run_runtime_results_preserves_incremental_signals(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="running",
    )
    db.upsert_sim_run_signals(
        run_id,
        [
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "回放策略买入",
                "checkpoint_at": "2026-04-01 10:00:00",
            }
        ],
    )

    db.replace_sim_run_runtime_results(
        run_id,
        trades=[
            {
                "signal_id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "price": 10.0,
                "quantity": 100,
                "amount": 1000.0,
                "realized_pnl": 0.0,
                "executed_at": "2026-04-01 10:00:00",
            }
        ],
        snapshots=[
            {
                "run_reason": "historical_range@2026-04-01 10:00:00",
                "initial_cash": 100000.0,
                "available_cash": 99000.0,
                "market_value": 1000.0,
                "total_equity": 100000.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "created_at": "2026-04-01 10:00:00",
            }
        ],
        positions=[],
    )

    signals = db.get_sim_run_signals(run_id)
    trades = db.get_sim_run_trades(run_id)
    snapshots = db.get_sim_run_snapshots(run_id)

    assert len(signals) == 1
    assert len(trades) == 1
    assert trades[0]["signal_id"] == signals[0]["id"]
    assert len(snapshots) == 1
    assert db.get_sim_run(run_id)["trade_count"] == 1
    assert db.count_sim_run_signals(run_id, actions=["BUY"]) == 1
    assert db.count_sim_run_signals(run_id, actions=["SELL"]) == 0
    assert db.get_sim_run_signals(run_id, actions=["BUY"])[0]["stock_code"] == "300390"


def test_live_trade_ledger_records_full_costs_pnl_slots_and_lots(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000.0)
    db.update_scheduler_config(commission_rate=0.001, sell_tax_rate=0.002)
    candidate_id = db.add_candidate(
        {
            "stock_code": "600036",
            "stock_name": "招商银行",
            "source": "manual",
            "latest_price": 10.0,
        }
    )

    buy_signal_id = db.add_signal(
        {
            "candidate_id": candidate_id,
            "stock_code": "600036",
            "stock_name": "招商银行",
            "action": "BUY",
            "confidence": 88,
            "reasoning": "建仓",
            "position_size_pct": 20,
            "status": "pending",
        }
    )
    db.confirm_signal(
        buy_signal_id,
        executed_action="buy",
        price=10.0,
        quantity=100,
        note="买入成本测试",
        executed_at="2026-04-08 10:00:00",
        apply_trade_cost=True,
    )

    sell_signal_id = db.add_signal(
        {
            "candidate_id": candidate_id,
            "stock_code": "600036",
            "stock_name": "招商银行",
            "action": "SELL",
            "confidence": 82,
            "reasoning": "卖出",
            "position_size_pct": 0,
            "status": "pending",
        }
    )
    db.confirm_signal(
        sell_signal_id,
        executed_action="sell",
        price=11.0,
        quantity=100,
        note="卖出成本测试",
        executed_at="2026-04-09 10:00:00",
        apply_trade_cost=True,
    )

    trades = db.get_trade_history(limit=10)
    sell_trade = trades[0]
    buy_trade = trades[1]
    buy_metadata = json.loads(buy_trade["trade_metadata_json"])
    sell_metadata = json.loads(sell_trade["trade_metadata_json"])
    summary = db.get_account_summary()
    cost_summary = db.get_trade_cost_summary()

    assert buy_trade["gross_amount"] == 1000.0
    assert buy_trade["commission_fee"] == 1.0
    assert buy_trade["sell_tax_fee"] == 0.0
    assert buy_trade["fee_total"] == 1.0
    assert buy_trade["net_amount"] == 1001.0
    assert buy_trade["amount"] == 1001.0
    assert buy_metadata["side"] == "BUY"
    assert buy_metadata["is_add"] is False
    assert buy_metadata["lot"]["quantity"] == 100
    assert buy_metadata["lot"]["lot_count"] == 1
    assert buy_metadata["slot_allocations"]

    assert sell_trade["gross_amount"] == 1100.0
    assert sell_trade["commission_fee"] == 1.1
    assert sell_trade["sell_tax_fee"] == 2.2
    assert sell_trade["fee_total"] == 3.3
    assert sell_trade["net_amount"] == 1096.7
    assert sell_trade["amount"] == 1096.7
    assert sell_trade["realized_pnl"] == 95.7
    assert sell_metadata["side"] == "SELL"
    assert sell_metadata["consumed_lots"][0]["quantity"] == 100
    assert sell_metadata["released_slot_allocations"]
    assert summary["available_cash"] == 100095.7
    assert summary["realized_pnl"] == 95.7
    assert cost_summary["buy_gross_amount"] == 1000.0
    assert cost_summary["sell_gross_amount"] == 1100.0
    assert cost_summary["slot_allocated_cash"] == 1001.0
    assert cost_summary["slot_released_cash"] == 1096.7
    assert cost_summary["max_occupied_slot_count"] == 1
    assert cost_summary["final_occupied_slot_count"] == 0


def test_delete_position_records_sell_costs_and_releases_slot_ledger(tmp_path):
    db = QuantSimDB(tmp_path / "app.quant_sim.db")
    db.configure_account(100000.0)
    db.update_scheduler_config(commission_rate=0.001, sell_tax_rate=0.002)
    candidate_id = db.add_candidate(
        {
            "stock_code": "600036",
            "stock_name": "招商银行",
            "source": "manual",
            "latest_price": 10.0,
        }
    )
    signal_id = db.add_signal(
        {
            "candidate_id": candidate_id,
            "stock_code": "600036",
            "stock_name": "招商银行",
            "action": "BUY",
            "confidence": 88,
            "reasoning": "建仓",
            "position_size_pct": 20,
            "status": "pending",
        }
    )
    db.confirm_signal(
        signal_id,
        executed_action="buy",
        price=10.0,
        quantity=100,
        note="买入成本测试",
        executed_at="2026-04-08 10:00:00",
        apply_trade_cost=True,
    )
    db.update_position_market_price("600036", 11.0)

    assert db.delete_position("600036") is True

    sell_trade = db.get_trade_history(limit=1)[0]
    metadata = json.loads(sell_trade["trade_metadata_json"])
    summary = db.get_account_summary()
    slot_allocations = db.get_lot_slot_allocations("600036")

    assert sell_trade["action"] == "sell"
    assert sell_trade["gross_amount"] == 1100.0
    assert sell_trade["commission_fee"] == 1.1
    assert sell_trade["sell_tax_fee"] == 2.2
    assert sell_trade["fee_total"] == 3.3
    assert sell_trade["net_amount"] == 1096.7
    assert sell_trade["amount"] == 1096.7
    assert sell_trade["realized_pnl"] == 95.7
    assert metadata["side"] == "SELL"
    assert metadata["manual_delete_position"] is True
    assert metadata["consumed_lots"][0]["quantity"] == 100
    assert metadata["released_slot_allocations"][0]["released_cash"] == 1096.7
    assert slot_allocations[0]["status"] == "closed"
    assert summary["available_cash"] == 100095.7
    assert summary["realized_pnl"] == 95.7


def test_replay_trade_results_preserve_full_trade_ledger_fields(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="running",
    )
    db.upsert_sim_run_signals(
        run_id,
        [
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "回放策略买入",
                "checkpoint_at": "2026-04-01 10:00:00",
            }
        ],
    )

    db.replace_sim_run_runtime_results(
        run_id,
        trades=[
            {
                "signal_id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "price": 10.0,
                "quantity": 100,
                "amount": 1001.0,
                "gross_amount": 1000.0,
                "commission_fee": 1.0,
                "sell_tax_fee": 0.0,
                "net_amount": 1001.0,
                "fee_total": 1.0,
                "realized_pnl": 0.0,
                "trade_metadata_json": json.dumps({"side": "BUY", "lot": {"lot_count": 1}}, ensure_ascii=False),
                "executed_at": "2026-04-01 10:00:00",
            }
        ],
        snapshots=[],
        positions=[],
    )

    trade = db.get_sim_run_trades(run_id)[0]

    assert trade["gross_amount"] == 1000.0
    assert trade["commission_fee"] == 1.0
    assert trade["sell_tax_fee"] == 0.0
    assert trade["fee_total"] == 1.0
    assert trade["net_amount"] == 1001.0
    assert json.loads(trade["trade_metadata_json"])["lot"]["lot_count"] == 1


def test_replay_trade_cost_summary_counts_sold_lots_by_share_quantity(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="completed",
    )
    db.replace_sim_run_runtime_results(
        run_id,
        trades=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "SELL",
                "price": 11.0,
                "quantity": 200,
                "amount": 2193.4,
                "gross_amount": 2200.0,
                "commission_fee": 2.2,
                "sell_tax_fee": 4.4,
                "net_amount": 2193.4,
                "fee_total": 6.6,
                "realized_pnl": 193.4,
                "trade_metadata_json": json.dumps(
                    {"side": "SELL", "consumed_lots": [{"lot_id": "L1", "quantity": 200}]},
                    ensure_ascii=False,
                ),
                "executed_at": "2026-04-09 10:00:00",
            }
        ],
        snapshots=[],
        positions=[],
    )

    summary = db.get_sim_run_trade_cost_summary(run_id)

    assert summary["sold_lot_count"] == 2


def test_trade_cost_summary_falls_back_for_legacy_zero_ledger_columns(tmp_path):
    db_file = tmp_path / "quant_sim_replay.db"
    db = QuantSimReplayDB(db_file)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="completed",
    )
    db.replace_sim_run_runtime_results(
        run_id,
        trades=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "price": 10.0,
                "quantity": 100,
                "amount": 1000.0,
                "executed_at": "2026-04-09 10:00:00",
            }
        ],
        snapshots=[],
        positions=[],
    )
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            UPDATE sim_run_trades
            SET gross_amount = 0, net_amount = 0, fee_total = 0, commission_fee = 0, sell_tax_fee = 0
            WHERE run_id = ?
            """,
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()

    summary = db.get_sim_run_trade_cost_summary(run_id)

    assert summary["buy_gross_amount"] == 1000.0
    assert summary["buy_net_amount"] == 1000.0


def test_upsert_sim_run_signals_updates_existing_checkpoint_signal(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="running",
    )

    db.upsert_sim_run_signals(
        run_id,
        [
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "第一次写入",
                "position_size_pct": 60.0,
                "decision_type": "dual_track_resonance",
                "tech_score": 0.72,
                "context_score": 0.28,
                "strategy_profile": {"analysis_timeframe": {"key": "30m"}},
                "checkpoint_at": "2026-04-01 10:00:00",
                "created_at": "2026-04-01 10:00:01",
            }
        ],
    )
    db.upsert_sim_run_signals(
        run_id,
        [
            {
                "id": 101,
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 88,
                "reasoning": "第二次刷新",
                "position_size_pct": 55.0,
                "decision_type": "dual_track_resonance",
                "tech_score": 0.81,
                "context_score": 0.35,
                "strategy_profile": {"analysis_timeframe": {"key": "30m"}},
                "checkpoint_at": "2026-04-01 10:00:00",
                "created_at": "2026-04-01 10:00:02",
            }
        ],
    )

    signals = db.get_sim_run_signals(run_id)

    assert len(signals) == 1
    assert signals[0]["confidence"] == 88
    assert signals[0]["reasoning"] == "第二次刷新"
    assert signals[0]["position_size_pct"] == 55.0
    assert signals[0]["status"] == "observed"
    assert signals[0]["updated_at"] == "2026-04-01 10:00:02"


def test_delete_sim_run_removes_all_replay_artifacts(tmp_path):
    db = QuantSimReplayDB(tmp_path / "quant_sim_replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-04-01 09:30:00",
        end_datetime="2026-04-09 15:00:00",
        initial_cash=100000.0,
        status="completed",
    )
    db.add_sim_run_checkpoint(
        run_id,
        checkpoint_at="2026-04-01 10:00:00",
        candidates_scanned=1,
        positions_checked=0,
        signals_created=1,
        auto_executed=1,
        available_cash=90000.0,
        market_value=10000.0,
        total_equity=100000.0,
    )
    db.replace_sim_run_results(
        run_id,
        trades=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "price": 10.0,
                "quantity": 100,
                "amount": 1000.0,
                "realized_pnl": 0.0,
                "executed_at": "2026-04-01 10:00:00",
            }
        ],
        snapshots=[
            {
                "run_reason": "historical_range@2026-04-01 10:00:00",
                "initial_cash": 100000.0,
                "available_cash": 99000.0,
                "market_value": 1000.0,
                "total_equity": 100000.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "created_at": "2026-04-01 10:00:00",
            }
        ],
        positions=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "quantity": 100,
                "avg_price": 10.0,
                "latest_price": 10.0,
                "market_value": 1000.0,
                "unrealized_pnl": 0.0,
                "sellable_quantity": 0,
                "locked_quantity": 100,
                "status": "holding",
            }
        ],
        signals=[
            {
                "stock_code": "300390",
                "stock_name": "天华新能",
                "action": "BUY",
                "confidence": 82,
                "reasoning": "回放策略买入",
                "position_size_pct": 60.0,
                "decision_type": "dual_track_resonance",
                "tech_score": 0.72,
                "context_score": 0.28,
                "strategy_profile": {"strategy_mode": {"key": "auto"}},
                "checkpoint_at": "2026-04-01 10:00:00",
                "created_at": "2026-04-01 10:00:01",
            }
        ],
    )
    db.append_sim_run_event(run_id, "完成", level="success")

    db.delete_sim_run(run_id)

    assert db.get_sim_run(run_id) is None
    assert db.get_sim_run_checkpoints(run_id) == []
    assert db.get_sim_run_trades(run_id) == []
    assert db.get_sim_run_snapshots(run_id) == []
    assert db.get_sim_run_positions(run_id) == []
    assert db.get_sim_run_signals(run_id) == []
    assert db.get_sim_run_events(run_id) == []
