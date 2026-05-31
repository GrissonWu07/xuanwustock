from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.gateway_api import UIApiContext, create_app
from app.quant_sim.db import OutcomeScoreFilters, QuantSimDB, QuantSimReplayDB
from app.quant_sim.market_technical_artifact import (
    ArtifactWriteRequest,
    MarketTechnicalArtifactData,
    MarketTechnicalArtifactRef,
)
from app.quant_sim.market_technical_artifact_store import MarketTechnicalArtifactStore
from app.quant_sim.signal_outcome_scoring import (
    OutcomeRunScope,
    OutcomeScoringRequest,
    SignalOutcomeScoringService,
)


def _data(price: float, **overrides) -> MarketTechnicalArtifactData:
    values = {
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "latest_price": price,
        "ma20": price * 0.98,
        "rsi": 55.0,
        "macd": 0.1,
        "volume_ratio": 1.2,
        "source_status": "ready",
        "reason_code": "ok",
        "computed_at": "2026-01-05 10:00:00",
        "market_json": {
            "source_score": 0.99,
            "source_confidence": 0.99,
        },
        "quality_json": {"multi_source_bonus": 1.0},
    }
    values.update(overrides)
    return MarketTechnicalArtifactData(**values)


def _live_ref(stock_code: str, checkpoint: str) -> MarketTechnicalArtifactRef:
    return MarketTechnicalArtifactRef.live(
        stock_code=stock_code,
        market="CN",
        checkpoint_at=checkpoint,
        timeframe="30m",
    )


def _run_ref(stock_code: str, checkpoint: str, *, run_id: int = 7) -> MarketTechnicalArtifactRef:
    return MarketTechnicalArtifactRef(
        domain="replay",
        run_id=str(run_id),
        run_type="historical_replay",
        stock_code=stock_code,
        market="CN",
        checkpoint_at=checkpoint,
        timeframe="30m",
    )


def _write_series(
    store: MarketTechnicalArtifactStore,
    refs: list[MarketTechnicalArtifactRef],
    prices: list[float],
) -> str:
    artifact_ref = ""
    for index, (ref, price) in enumerate(zip(refs, prices)):
        written = store.upsert(
            ArtifactWriteRequest(
                ref=ref,
                data=_data(price, high=price * 1.01, low=price * 0.99, computed_at=ref.checkpoint_at),
            )
        )
        if index == 0:
            artifact_ref = written.artifact_ref
    return artifact_ref


def _signal(action: str, artifact_ref: str, **overrides) -> dict:
    payload = {
        "id": 101,
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "action": action,
        "checkpoint_at": "2026-01-05 10:00:00",
        "strategy_profile": {
            "selected_strategy_profile": {"id": "aggressive"},
            "market_snapshot": {"artifact_ref": artifact_ref},
        },
    }
    payload.update(overrides)
    return payload


def _structured_strategy_profile(artifact_ref: str) -> dict:
    explainability = {
        "technical_breakdown": {
            "track": {"score": 0.55, "confidence": 0.72},
            "groups": [{"id": "trend", "score": 0.55, "track_contribution": 0.55}],
            "dimensions": [{"id": "price_vs_ma20", "score": 1.0, "reason": "price above ma20"}],
        },
        "context_breakdown": {
            "track": {"score": 0.2, "confidence": 0.68},
            "groups": [{"id": "market", "score": 0.2, "track_contribution": 0.2}],
            "dimensions": [{"id": "market_alignment", "score": 0.2, "reason": "aligned"}],
        },
        "fusion_breakdown": {
            "mode": "hybrid",
            "tech_score": 0.55,
            "context_score": 0.2,
            "fusion_score": 0.41,
            "fusion_confidence": 0.7,
            "buy_threshold_eff": 0.35,
            "sell_threshold_eff": -0.2,
            "weighted_threshold_action": "BUY",
            "weighted_action_raw": "BUY",
            "core_rule_action": "BUY",
            "final_action": "BUY",
            "tech_weight_norm": 0.6,
            "context_weight_norm": 0.4,
            "weighted_gate_fail_reasons": [],
        },
        "dual_track": {"final_reason": "structured buy"},
        "decision_path": [{"step": "weighted_gate", "detail": "pass"}],
        "vetoes": [],
    }
    return {
        "selected_strategy_profile": {"id": "aggressive", "name": "积极", "version": "1"},
        "market_snapshot": {"artifact_ref": artifact_ref, "current_price": 10.0, "status": "ready"},
        "effective_thresholds": {"buy_threshold": 0.35, "sell_threshold": -0.2},
        "analysis": "structured buy",
        "decision_reason": "structured buy",
        "explainability": explainability,
    }


def _context(tmp_path: Path) -> UIApiContext:
    (tmp_path / "selector_results").mkdir(parents=True, exist_ok=True)
    return UIApiContext(
        data_dir=tmp_path,
        selector_result_dir=tmp_path / "selector_results",
        monitor_db_file=tmp_path / "monitor.db",
        smart_monitor_db_file=tmp_path / "smart_monitor.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        main_force_batch_db_file=tmp_path / "main_force_batch.db",
    )


def test_future_window_is_ordered_and_does_not_fallback_to_live(tmp_path: Path) -> None:
    live_store = MarketTechnicalArtifactStore(tmp_path / "live.db")
    replay_store = MarketTechnicalArtifactStore(tmp_path / "replay.db")
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    live_ref = _write_series(live_store, [_live_ref("600000", item) for item in checkpoints], [10, 11, 12, 13])
    replay_ref = _write_series(replay_store, [_run_ref("600000", checkpoints[0])], [20])

    live_window = live_store.future_window_by_ref(live_ref, horizon_checkpoints=3)
    replay_window = replay_store.future_window_by_ref(replay_ref, horizon_checkpoints=1)

    assert live_window.mature is True
    assert [item.ref.checkpoint_at for item in live_window.window] == checkpoints[1:]
    assert replay_window.mature is False
    assert replay_window.reason_code == "horizon_not_mature"
    assert replay_window.window == []


def test_buy_outcome_scoring_persists_mature_metrics_and_scrubs_source_fields(tmp_path: Path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
        "2026-01-05 13:00:00",
        "2026-01-05 13:30:00",
    ]
    artifact_ref = _write_series(store, [_live_ref("600000", item) for item in checkpoints], [10, 10.3, 10.7, 10.9, 10.8, 10.6])

    results = SignalOutcomeScoringService(db, store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("BUY", artifact_ref),
            policy={"outcome_horizons_checkpoints": [3, 5]},
        )
    )
    rows = db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=101, limit=10))

    assert [result.status for result in results] == ["mature", "mature"]
    assert [row["horizon_checkpoints"] for row in sorted(rows, key=lambda item: item["horizon_checkpoints"])] == [3, 5]
    horizon5 = next(row for row in rows if row["horizon_checkpoints"] == 5)
    assert horizon5["matured_at"] == "2026-01-05 13:30:00"
    assert horizon5["metrics"]["mfe_pct"] > 0
    assert horizon5["metrics"]["target_hit"] is True
    assert horizon5["status"] == "mature"
    assert "source_score" not in str(horizon5["formula"])
    assert "source_confidence" not in str(horizon5["formula"])
    assert "multi_source_bonus" not in str(horizon5["formula"])


def test_as_of_checkpoint_blocks_preloaded_future_artifacts(tmp_path: Path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    artifact_ref = _write_series(store, [_live_ref("600000", item) for item in checkpoints], [10, 10.1, 10.2, 10.3])

    SignalOutcomeScoringService(db, store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("BUY", artifact_ref, id=301),
            policy={"outcome_horizons_checkpoints": [3]},
            as_of_checkpoint="2026-01-05 11:00:00",
        )
    )
    early_row = db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=301, limit=1))[0]
    SignalOutcomeScoringService(db, store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("BUY", artifact_ref, id=301),
            policy={"outcome_horizons_checkpoints": [3]},
            as_of_checkpoint="2026-01-05 11:30:00",
        )
    )
    mature_row = db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=301, limit=1))[0]

    assert early_row["status"] == "skipped"
    assert early_row["reason_code"] == "horizon_not_mature"
    assert mature_row["status"] == "mature"
    assert mature_row["matured_at"] == "2026-01-05 11:30:00"


def test_sell_outcome_scoring_persists_sell_validation_metrics(tmp_path: Path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    artifact_ref = _write_series(store, [_live_ref("600000", item) for item in checkpoints], [10, 9.8, 9.5, 9.4])

    SignalOutcomeScoringService(db, store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("SELL", artifact_ref, decision_type="profit_tech_sell"),
            policy={"outcome_horizons_checkpoints": [3]},
        )
    )
    row = db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=101, limit=1))[0]

    assert row["action"] == "SELL"
    assert row["metrics"]["avoided_drawdown_pct"] > 0
    assert row["metrics"]["sell_validated"] is True
    assert row["metrics"]["sell_intent"] == "profit_tech_sell"
    assert row["outcome_score"] > 50


def test_incomplete_horizon_persists_skipped_reason(tmp_path: Path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    store = MarketTechnicalArtifactStore(tmp_path / "quant_sim.db")
    checkpoints = ["2026-01-05 10:00:00", "2026-01-05 10:30:00"]
    artifact_ref = _write_series(store, [_live_ref("600000", item) for item in checkpoints], [10, 10.1])

    SignalOutcomeScoringService(db, store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("BUY", artifact_ref),
            policy={"outcome_horizons_checkpoints": [3]},
        )
    )
    row = db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=101, limit=1))[0]

    assert row["status"] == "skipped"
    assert row["reason_code"] == "horizon_not_mature"
    assert row["metrics"]["reason_code"] == "horizon_not_mature"


def test_run_outcome_scoring_is_isolated_from_live_tables(tmp_path: Path) -> None:
    live_db = QuantSimDB(tmp_path / "live.db")
    replay_db = QuantSimReplayDB(tmp_path / "replay.db")
    replay_store = MarketTechnicalArtifactStore(tmp_path / "replay.db")
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    artifact_ref = _write_series(replay_store, [_run_ref("600000", item, run_id=9) for item in checkpoints], [10, 10.2, 10.5, 10.8])

    SignalOutcomeScoringService(replay_db, replay_store).score_signal(
        OutcomeScoringRequest(
            signal=_signal("BUY", artifact_ref, id=201),
            policy={"outcome_horizons_checkpoints": [3]},
            run_scope=OutcomeRunScope(run_id=9, run_type="historical_replay", domain="replay"),
        )
    )

    run_rows = replay_db.list_sim_run_signal_outcome_scores(
        9,
        "historical_replay",
        OutcomeScoreFilters(signal_id=201, limit=10),
    )
    live_rows = live_db.list_signal_outcome_scores(OutcomeScoreFilters(signal_id=201, limit=10))

    assert len(run_rows) == 1
    assert run_rows[0]["run_id"] == 9
    assert live_rows == []


def test_outcome_api_scores_and_exposes_live_signal_detail(tmp_path: Path) -> None:
    context = _context(tmp_path)
    db = QuantSimDB(context.quant_sim_db_file, db_runtime=context.db_runtime)
    store = MarketTechnicalArtifactStore(context.quant_sim_db_file)
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    artifact_ref = _write_series(store, [_live_ref("600000", item) for item in checkpoints], [10, 10.2, 10.5, 10.6])
    signal_id = db.add_signal(
        _signal(
            "BUY",
            artifact_ref,
            id=0,
            confidence=70,
            strategy_profile=_structured_strategy_profile(artifact_ref),
            tech_score=0.55,
            context_score=0.2,
            reasoning="structured buy",
        ),
        dedupe_pending=False,
    )
    with TestClient(create_app(context=context)) as client:
        score_response = client.post("/api/v1/quant/outcomes/live/score-matured?limit=10")
        rows_response = client.get(f"/api/v1/quant/outcomes/signals/{signal_id}?source=live")
        detail_response = client.get(f"/api/v1/quant/signals/{signal_id}?source=live")

    assert score_response.status_code == 200
    assert score_response.json()["scored_signals"] == 1
    assert rows_response.status_code == 200
    assert rows_response.json()["items"][0]["signal_id"] == signal_id
    assert detail_response.status_code == 200
    assert detail_response.json()["outcomes"][0]["signal_id"] == signal_id


def test_outcome_api_scores_run_and_filters_replay_signal_rows(tmp_path: Path) -> None:
    context = _context(tmp_path)
    db = QuantSimReplayDB(context.quant_sim_replay_db_file, db_runtime=context.db_runtime)
    run_id = db.create_sim_run(
        mode="historical_range",
        timeframe="30m",
        market="CN",
        start_datetime="2026-01-05 10:00:00",
        end_datetime="2026-01-05 11:30:00",
        initial_cash=100000.0,
        status="completed",
    )
    checkpoints = [
        "2026-01-05 10:00:00",
        "2026-01-05 10:30:00",
        "2026-01-05 11:00:00",
        "2026-01-05 11:30:00",
    ]
    for checkpoint in checkpoints:
        db.add_sim_run_checkpoint(
            run_id,
            checkpoint_at=checkpoint,
            candidates_scanned=1,
            positions_checked=0,
            signals_created=1,
            auto_executed=0,
            available_cash=100000.0,
            market_value=0.0,
            total_equity=100000.0,
        )
    store = MarketTechnicalArtifactStore(context.quant_sim_replay_db_file)
    artifact_ref = _write_series(store, [_run_ref("600000", item, run_id=run_id) for item in checkpoints], [10, 10.2, 10.5, 10.7])
    db.upsert_sim_run_signals(
        run_id,
        [
            _signal(
                "BUY",
                artifact_ref,
                id=501,
                strategy_profile=_structured_strategy_profile(artifact_ref),
                checkpoint_at=checkpoints[0],
            )
        ],
    )
    persisted_signal = db.get_sim_run_signals(run_id, include_strategy_profile=True)[0]
    persisted_signal_id = persisted_signal["id"]

    assert persisted_signal["strategy_profile"]["market_snapshot"]["artifact_ref"] == artifact_ref

    with TestClient(create_app(context=context)) as client:
        score_response = client.post(f"/api/v1/quant/outcomes/runs/{run_id}/score?runType=historical_replay&limit=10")
        summary_response = client.get(f"/api/v1/quant/outcomes/runs/{run_id}?runType=historical_replay")
        rows_response = client.get(
            f"/api/v1/quant/outcomes/signals/{persisted_signal_id}?source=replay&runId={run_id}&runType=historical_replay&horizon=3"
        )

    assert score_response.status_code == 200
    assert score_response.json()["run_id"] == run_id
    assert score_response.json()["scored_signals"] == 1
    assert summary_response.status_code == 200
    assert summary_response.json()["mature_count"] == 1
    assert rows_response.status_code == 200
    assert rows_response.json()["items"][0]["run_id"] == run_id
    assert rows_response.json()["items"][0]["horizon_checkpoints"] == 3
