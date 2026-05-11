from pathlib import Path

from app.quant_sim.db import QuantSimDB, QuantSimReplayDB


def _signal_payload() -> dict:
    return {
        "id": 1001,
        "stock_code": "000001",
        "stock_name": "平安银行",
        "action": "BUY",
        "confidence": 80,
        "reasoning": "contract",
        "position_size_pct": 3.0,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 12.0,
        "decision_type": "dual_track_weighted_buy",
        "tech_score": 0.55,
        "context_score": 0.30,
        "status": "pending",
        "checkpoint_at": "2026-01-05T10:00:00Z",
        "created_at": "2026-01-05T10:00:01Z",
        "updated_at": "2026-01-05T10:00:01Z",
        "strategy_profile": {
            "kernel_positioning": {
                "quality_position_pct": 28.26,
                "rule_hit": "resonance_standard",
                "signal_quality_score": 0.38,
            },
            "execution_sizing_plan": {
                "buy_tier": "weak_buy",
                "effective_position_pct": 3.0,
                "final_budget": 12000.0,
                "cap_reasons": ["trial_weak_buy_cap"],
            },
        },
    }


def test_live_signal_persists_kernel_and_execution_sizing_payload(tmp_path: Path):
    db = QuantSimDB(tmp_path / "live.db")
    signal_id = db.add_signal(_signal_payload())

    signal = db.get_signal(signal_id)
    profile = signal["strategy_profile"]

    assert profile["kernel_positioning"]["quality_position_pct"] == 28.26
    assert profile["execution_sizing_plan"]["effective_position_pct"] == 3.0
    assert profile["execution_sizing_plan"]["final_budget"] == 12000.0


def test_replay_signal_persists_kernel_and_execution_sizing_payload(tmp_path: Path):
    db = QuantSimReplayDB(tmp_path / "replay.db")
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01T00:00:00Z",
        end_datetime="2026-01-31T00:00:00Z",
        initial_cash=400000,
        status="running",
        selected_strategy_profile_id="aggressive",
    )
    db.upsert_sim_run_signals(run_id, [_signal_payload()])

    signal_id = db.get_sim_run_signals(run_id)[0]["id"]
    signal = db.get_sim_run_signal(signal_id)
    profile = signal["strategy_profile"]

    assert profile["kernel_positioning"]["rule_hit"] == "resonance_standard"
    assert profile["execution_sizing_plan"]["buy_tier"] == "weak_buy"
    assert profile["execution_sizing_plan"]["final_budget"] == 12000.0
