from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3

from app.database import StockAnalysisDatabase


def test_stock_analysis_context_repository_filters_quality_for_replay(tmp_path) -> None:
    from app.data.analysis_context.repository import StockAnalysisContextRepository

    db = StockAnalysisDatabase(tmp_path / "analysis.db")
    checkpoint = datetime(2025, 8, 29, 13, 30)
    common = {
        "symbol": "002518",
        "stock_name": "科士达",
        "period": "1y",
        "stock_info": {"symbol": "002518"},
        "agents_results": {},
        "discussion_result": "讨论",
        "final_decision": {"decision_text": "建议买入", "confidence": 0.8},
        "indicators": {},
        "historical_data": [],
        "data_as_of": (checkpoint - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "valid_until": (checkpoint + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "analysis_context": {"action_bias": 0.6, "confidence": 0.8, "summary": "偏多"},
    }
    fallback_id = db.save_analysis(**common, data_as_of_quality="generated_at_fallback")
    exact_id = db.save_analysis(**common, data_as_of_quality="exact")
    future_id = db.save_analysis(
        **{
            **common,
            "analysis_context": {"action_bias": 0.95, "confidence": 0.99, "summary": "未来生成，不应使用"},
        },
        data_as_of_quality="exact",
    )
    with sqlite3.connect(tmp_path / "analysis.db") as conn:
        conn.execute(
            "UPDATE analysis_records SET created_at = ? WHERE id IN (?, ?)",
            ((checkpoint - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), fallback_id, exact_id),
        )
        conn.execute(
            "UPDATE analysis_records SET created_at = ? WHERE id = ?",
            ((checkpoint + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), future_id),
        )

    repo = StockAnalysisContextRepository(db_path=tmp_path / "analysis.db")
    replay_record = repo.get_latest_valid("002518", as_of=checkpoint, mode="replay")
    realtime_record = repo.get_latest_valid("002518", as_of=checkpoint, mode="realtime")

    assert replay_record is not None
    assert replay_record["record_id"] == exact_id
    assert replay_record["data_as_of_quality"] == "exact"
    assert realtime_record is not None
    assert realtime_record["record_id"] in {fallback_id, exact_id}


def test_stock_analysis_context_normalizer_is_deterministic() -> None:
    from app.data.analysis_context.normalizer import StockAnalysisContextNormalizer

    result = StockAnalysisContextNormalizer().normalize(
        final_decision={"rating": "买入", "confidence": 0.7, "risk_warning": "估值偏贵"},
        agents_results={"fund_flow": {"analysis": "资金流入明显"}, "risk": {"analysis": "短线波动风险"}},
    )

    assert result["action_bias"] > 0
    assert 0 <= result["confidence"] <= 1
    assert result["risk_bias"] < 0
    assert "final_decision" in result["source_fields"]


def test_stock_analysis_policy_is_resolved_from_strategy_profile(tmp_path) -> None:
    from app.quant_kernel.config import StrategyScoringConfig
    from app.quant_sim.engine import QuantSimEngine

    payload = StrategyScoringConfig.default()
    config = {
        "schema_version": payload.schema_version,
        "base": json.loads(json.dumps(payload.base, ensure_ascii=False)),
        "profiles": json.loads(json.dumps(payload.profiles, ensure_ascii=False)),
    }
    config["base"]["context"]["stock_analysis_policy"]["ttl_hours"] = 12
    config["base"]["context"]["stock_analysis_policy"]["min_confidence"] = 0.67
    binding = {"config": config}
    engine = QuantSimEngine(
        db_file=tmp_path / "sim.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        stock_analysis_refresh_enabled=False,
    )
    captured = {}

    class FakeRepository:
        def get_latest_valid(self, symbol, *, as_of=None, mode="realtime", ttl_hours=48.0, min_confidence=0.0):
            captured.update({"symbol": symbol, "ttl_hours": ttl_hours, "min_confidence": min_confidence})
            return {"used": True, "record_id": 1, "score": 0.5, "effective_score": 0.335, "confidence": 0.67}

    engine.stock_analysis_context = FakeRepository()
    policy = engine._stock_analysis_policy_from_binding(binding, profile_kind="candidate")
    context = engine._build_stock_analysis_context({"stock_code": "002518"}, profile_kind="candidate", policy=policy)

    assert captured == {"symbol": "002518", "ttl_hours": 12.0, "min_confidence": 0.67}
    assert context is not None
    assert context["used"] is True
    assert context["policy"]["ttl_hours"] == 12.0


def test_default_stock_analysis_policy_keeps_context_for_one_day(tmp_path) -> None:
    from app.quant_sim.engine import QuantSimEngine

    engine = QuantSimEngine(
        db_file=tmp_path / "sim.db",
        stock_analysis_db_file=tmp_path / "analysis.db",
        stock_analysis_refresh_enabled=False,
    )

    policy = engine._default_stock_analysis_policy()

    assert policy["ttl_hours"] == 24.0


def test_missing_stock_analysis_does_not_reduce_context_confidence() -> None:
    from app.quant_kernel.config import CONTEXT_DIMENSIONS, StrategyScoringConfig
    from app.quant_kernel.scoring_v23 import score_track

    config = StrategyScoringConfig.default().resolve("candidate")
    raw_dimensions = {
        dimension: {"score": 0.1, "available": True, "reason": "fixture"}
        for dimension in CONTEXT_DIMENSIONS
        if dimension != "stock_analysis"
    }
    raw_dimensions["stock_analysis"] = {
        "score": 0.0,
        "available": False,
        "reason": "no_valid_stock_analysis_context",
    }

    scored = score_track(
        track_name="context",
        track_config=config["context"],
        raw_dimensions=raw_dimensions,
    )

    assert scored["track"]["confidence"] == 1.0
    assert next(group for group in scored["groups"] if group["id"] == "external_analysis")["available"] is False
