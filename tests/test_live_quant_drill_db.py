from app.quant_sim.db import QuantSimReplayDB


def _create_drill_run(db: QuantSimReplayDB) -> int:
    return db.create_sim_run(
        mode="live_quant_drill",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-01 09:30:00",
        end_datetime="2026-01-02 15:00:00",
        initial_cash=100000,
        status="running",
        auto_execute=True,
        handoff_to_live=False,
        progress_current=0,
        progress_total=2,
        status_message="running",
        metadata={"run_type": "live_quant_drill"},
    )


def test_live_quant_drill_tables_are_created(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    with db._connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert "sim_run_quant_states" in tables
    assert "sim_run_quant_events" in tables
    assert "sim_run_candidate_events" in tables
    assert "sim_run_quant_summary" in tables


def test_live_quant_drill_quant_state_crud(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    run_id = _create_drill_run(db)

    db.upsert_sim_run_quant_states(
        run_id,
        checkpoint_at="2026-01-01 09:30:00",
        states=[
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "market": "CN",
                "quant_enabled": True,
                "quant_status": "trial",
                "health_score": 88.0,
                "candidate_score": 0.72,
                "downtrend_streak": 2,
                "weakening_warning_streak": 3,
                "blocked_streak": 1,
                "no_buy_days": 4,
                "cooling_until": "2026-01-03 09:30:00",
                "retired_at": None,
                "latest_reason": "auto_trial",
                "snapshot_json": {"reason_code": "auto_trial"},
            }
        ],
    )

    rows = db.list_sim_run_quant_states(run_id, status="trial")
    assert rows["total"] == 1
    assert rows["items"][0]["stock_code"] == "600519"
    assert rows["items"][0]["downtrend_streak"] == 2
    assert rows["items"][0]["cooling_until"] == "2026-01-03 09:30:00"
    assert rows["items"][0]["snapshot_json"]["reason_code"] == "auto_trial"


def test_live_quant_drill_event_candidate_and_summary_crud(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    run_id = _create_drill_run(db)

    db.add_sim_run_candidate_events(
        run_id,
        [
            {
                "checkpoint_at": "2026-01-01 09:30:00",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "source_type": "low_price",
                "source_key": "daily_first",
                "candidate_score": 0.77,
                "confidence": 0.66,
                "reason_text": "历史低价候选",
                "evidence_json": {"price": 10.5},
            }
        ],
    )
    consumed = db.mark_sim_run_candidate_events_consumed(
        run_id,
        stock_code="600519",
        source_type="low_price",
        checkpoint_at_lte="2026-01-01 09:30:00",
    )
    candidates = db.list_sim_run_candidate_events(run_id, status="consumed")
    assert consumed == 1
    assert candidates["total"] == 1
    assert candidates["items"][0]["evidence_json"]["price"] == 10.5

    db.add_sim_run_quant_events(
        run_id,
        [
            {
                "checkpoint_at": "2026-01-01 10:00:00",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "event_type": "status_transition",
                "from_status": "trial",
                "to_status": "active",
                "reason_code": "strong_candidate",
                "reason_text": "强候选升级",
                "health_score_before": 88.0,
                "health_score_after": 92.0,
                "reason_json": {"reason_code": "strong_candidate"},
                "evidence_json": {"buy_strength": 0.8},
            }
        ],
    )
    events = db.list_sim_run_quant_events(run_id, to_status="active")
    assert events["total"] == 1
    assert events["items"][0]["reason_code"] == "strong_candidate"
    assert events["items"][0]["reason_json"]["reason_code"] == "strong_candidate"

    db.upsert_sim_run_quant_summary(
        run_id,
        {
            "checkpoint_at": "2026-01-01 10:00:00",
            "inactive_count": 1,
            "trial_count": 2,
            "active_count": 3,
            "exit_only_count": 1,
            "cooling_count": 0,
            "retired_count": 0,
            "manual_paused_count": 0,
            "auto_promoted_count": 1,
            "auto_exited_count": 0,
            "candidate_event_count": 1,
            "data_warning_count": 0,
            "metadata_json": {"source": "checkpoint"},
        },
    )
    summaries = db.list_sim_run_quant_summary(run_id)
    assert len(summaries) == 1
    assert summaries[0]["inactive_count"] == 1
    assert summaries[0]["active_count"] == 3
    assert summaries[0]["metadata_json"]["source"] == "checkpoint"


def test_delete_sim_run_cleans_live_quant_drill_tables(tmp_path):
    db = QuantSimReplayDB(str(tmp_path / "replay.db"))
    run_id = _create_drill_run(db)
    db.update_sim_run_progress(run_id, status="completed")
    db.upsert_sim_run_quant_states(
        run_id,
        checkpoint_at="2026-01-01 09:30:00",
        states=[{"stock_code": "600519", "quant_status": "active"}],
    )
    db.add_sim_run_quant_events(
        run_id,
        [
            {
                "checkpoint_at": "2026-01-01 09:30:00",
                "stock_code": "600519",
                "event_type": "status_transition",
            }
        ],
    )
    db.add_sim_run_candidate_events(
        run_id,
        [
            {
                "checkpoint_at": "2026-01-01 09:30:00",
                "stock_code": "600519",
                "source_type": "manual_seed",
            }
        ],
    )
    db.upsert_sim_run_quant_summary(
        run_id,
        {
            "checkpoint_at": "2026-01-01 09:30:00",
        },
    )

    db.delete_sim_run(run_id)

    assert db.list_sim_run_quant_states(run_id)["total"] == 0
    assert db.list_sim_run_quant_events(run_id)["total"] == 0
    assert db.list_sim_run_candidate_events(run_id)["total"] == 0
    assert db.list_sim_run_quant_summary(run_id) == []
