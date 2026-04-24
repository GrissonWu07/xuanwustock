from datetime import datetime, timedelta

from app.quant_kernel.config import StrategyScoringConfig
from app.quant_sim.dynamic_strategy import DynamicStrategyController


class _MissingMarketSectorDB:
    def get_latest_raw_data(self, key, within_hours=None):
        del key, within_hours
        return None

    def get_latest_news_data(self, within_hours=None):
        del within_hours
        return None


class _FakeSmartMonitorDB:
    def __init__(self, rows):
        self.rows = rows

    def get_ai_decisions(self, stock_code=None, limit=100):
        del stock_code, limit
        return list(self.rows)


class _AsOfOnlySectorDB:
    def get_latest_raw_data(self, key, within_hours=None):
        del key, within_hours
        raise AssertionError("replay must not use latest sector raw data")

    def get_raw_data_as_of(self, key, *, as_of, within_hours=None):
        assert key == "market_overview"
        assert as_of == datetime(2025, 8, 29, 13, 30)
        assert within_hours == 48
        return {
            "data_date": "2025-08-29",
            "created_at": "2025-08-29 12:30:00",
            "data_content": {
                "sh_index": {"change_pct": 1.25},
                "sz_index": {"change_pct": 0.75},
            },
        }

    def get_latest_news_data(self, within_hours=None):
        del within_hours
        return None

    def get_news_data_as_of(self, *, as_of, within_hours=None):
        assert as_of == datetime(2025, 8, 29, 13, 30)
        assert within_hours == 48
        return None


class _AsOfNewsFlowDB:
    def get_latest_snapshot(self):
        raise AssertionError("replay must not use latest flow snapshot")

    def get_snapshot_as_of(self, *, as_of, within_hours=None):
        assert as_of == datetime(2025, 8, 29, 13, 30)
        assert within_hours == 48
        return {"total_score": 650, "fetch_time": "2025-08-29 12:00:00"}

    def get_latest_sentiment(self):
        raise AssertionError("replay must not use latest sentiment")

    def get_sentiment_as_of(self, *, as_of, within_hours=None):
        assert as_of == datetime(2025, 8, 29, 13, 30)
        assert within_hours == 48
        return {"sentiment_index": 70, "fetch_time": "2025-08-29 12:00:00"}

    def get_latest_ai_analysis(self):
        raise AssertionError("replay must not use latest AI analysis")

    def get_ai_analysis_as_of(self, *, as_of, within_hours=None):
        assert as_of == datetime(2025, 8, 29, 13, 30)
        assert within_hours == 48
        return {
            "confidence": 80,
            "risk_level": "低",
            "fetch_time": "2025-08-29 12:15:00",
            "affected_sectors": [],
            "recommended_stocks": [],
            "risk_factors": [],
        }


def test_market_component_ignores_stale_flow_snapshot(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    stale_time = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

    monkeypatch.setattr(controller, "_sector_db_instance", lambda: _MissingMarketSectorDB())
    monkeypatch.setattr(
        "app.quant_sim.dynamic_strategy.news_flow_db.get_latest_snapshot",
        lambda: {
            "total_score": 65,
            "fetch_time": stale_time,
        },
    )

    component = controller._market_component(lookback_hours=48)  # noqa: SLF001 - targeted regression coverage

    assert component is None


def test_resolve_binding_replay_asof_omits_future_ai_decisions(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("stable_v23")
    checkpoint = datetime(2025, 8, 29, 13, 30)

    monkeypatch.setattr(controller, "_sector_db_instance", lambda: _MissingMarketSectorDB())
    monkeypatch.setattr(controller, "_smart_db", lambda: _FakeSmartMonitorDB([
        {"action": "BUY", "confidence": 95, "decision_time": "2026-04-24 20:26:55"},
    ]))
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_snapshot", lambda: None)
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_sentiment", lambda: None)
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_ai_analysis", lambda: None)

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="002518",
        stock_name="科士达",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
        as_of=checkpoint,
    )

    dynamic = binding["dynamic_strategy"]
    omitted = {item["key"]: item for item in dynamic["omitted_components"]}

    assert dynamic["as_of"] == "2025-08-29 13:30:00"
    assert dynamic["components"] == []
    assert dynamic["score"] == 0.0
    assert dynamic["confidence"] == 0.0
    assert omitted["ai"]["reason"] == "no_historical_asof_data"


def test_resolve_binding_replay_asof_uses_only_ai_decisions_visible_at_checkpoint(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("stable_v23")
    checkpoint = datetime(2025, 8, 29, 13, 30)

    monkeypatch.setattr(controller, "_sector_db_instance", lambda: _MissingMarketSectorDB())
    monkeypatch.setattr(controller, "_smart_db", lambda: _FakeSmartMonitorDB([
        {"action": "SELL", "confidence": 99, "decision_time": "2026-04-24 20:26:55"},
        {"action": "BUY", "confidence": 80, "decision_time": "2025-08-29 12:45:00"},
    ]))
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_snapshot", lambda: None)
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_sentiment", lambda: None)
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_ai_analysis", lambda: None)

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="002518",
        stock_name="科士达",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
        as_of=checkpoint,
    )

    dynamic = binding["dynamic_strategy"]
    ai_component = next(item for item in dynamic["components"] if item["key"] == "ai")

    assert ai_component["score"] > 0
    assert ai_component["as_of"] == "2025-08-29 12:45:00"
    assert "ai" not in {item["key"] for item in dynamic["omitted_components"]}


def test_resolve_binding_replay_asof_prefers_historical_sector_query(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")

    monkeypatch.setattr(controller, "_sector_db_instance", lambda: _AsOfOnlySectorDB())
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db.get_latest_snapshot", lambda: None)
    monkeypatch.setattr(controller, "_smart_db", lambda: _FakeSmartMonitorDB([]))

    signal = controller._build_dynamic_signal(  # noqa: SLF001 - targeted as-of contract coverage
        stock_code="002518",
        stock_name="科士达",
        lookback_hours=48,
        as_of=datetime(2025, 8, 29, 13, 30),
    )

    market_component = next(item for item in signal["components"] if item["key"] == "market")
    omitted = {item["key"] for item in signal["omitted_components"]}

    assert market_component["reason"] == "market_overview(2)"
    assert market_component["as_of"] == "2025-08-29 12:30:00"
    assert "market" not in omitted


def test_resolve_binding_replay_asof_prefers_historical_news_flow_queries(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")

    monkeypatch.setattr(controller, "_sector_db_instance", lambda: _MissingMarketSectorDB())
    monkeypatch.setattr("app.quant_sim.dynamic_strategy.news_flow_db", _AsOfNewsFlowDB())
    monkeypatch.setattr(controller, "_smart_db", lambda: _FakeSmartMonitorDB([]))

    signal = controller._build_dynamic_signal(  # noqa: SLF001 - targeted as-of contract coverage
        stock_code="002518",
        stock_name="科士达",
        lookback_hours=48,
        as_of=datetime(2025, 8, 29, 13, 30),
    )

    keys = {item["key"] for item in signal["components"]}

    assert "market" in keys
    assert "news" in keys


def test_sector_strategy_db_raw_data_as_of_ignores_future_versions(tmp_path):
    from app.sector_strategy_db import SectorStrategyDatabase

    db = SectorStrategyDatabase(tmp_path / "sector_strategy.db")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO data_versions
        (data_type, data_date, version, fetch_success, record_count, created_at)
        VALUES ('market_overview', '2025-08-29', 1, 1, 1, '2025-08-29 12:30:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO data_versions
        (data_type, data_date, version, fetch_success, record_count, created_at)
        VALUES ('market_overview', '2026-04-24', 1, 1, 1, '2026-04-24 10:00:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO sector_raw_data
        (data_date, sector_code, sector_name, price, change_pct, volume, turnover, data_type, data_version, created_at)
        VALUES ('2025-08-29', 'SH', 'SH指数', 3200, 1.25, 100, 200, 'market_overview', 1, '2025-08-29 12:30:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO sector_raw_data
        (data_date, sector_code, sector_name, price, change_pct, volume, turnover, data_type, data_version, created_at)
        VALUES ('2026-04-24', 'SH', 'SH指数', 3300, -3.5, 100, 200, 'market_overview', 1, '2026-04-24 10:00:00')
        """
    )
    conn.commit()
    conn.close()

    payload = db.get_raw_data_as_of(
        "market_overview",
        as_of="2025-08-29T13:30:00",
        within_hours=48,
    )

    assert payload["created_at"] == "2025-08-29 12:30:00"
    assert payload["data_content"]["sh_index"]["change_pct"] == 1.25


def test_news_flow_db_as_of_queries_ignore_future_records(tmp_path):
    from app.news_flow_db import NewsFlowDatabase

    db = NewsFlowDatabase(tmp_path / "news_flow.db")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO flow_snapshots
        (id, fetch_time, total_platforms, success_count, total_score, flow_level, created_at)
        VALUES (1, '2025-08-29 12:00:00', 3, 3, 650, 'hot', '2025-08-29 12:00:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO flow_snapshots
        (id, fetch_time, total_platforms, success_count, total_score, flow_level, created_at)
        VALUES (2, '2026-04-24 10:00:00', 3, 3, 200, 'cold', '2026-04-24 10:00:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO sentiment_records
        (snapshot_id, sentiment_index, sentiment_class, flow_stage, created_at)
        VALUES (1, 70, '偏热', '扩散', '2025-08-29 12:05:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO sentiment_records
        (snapshot_id, sentiment_index, sentiment_class, flow_stage, created_at)
        VALUES (2, 10, '冰点', '退潮', '2026-04-24 10:05:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO ai_analysis
        (snapshot_id, affected_sectors, recommended_stocks, risk_level, risk_factors, advice, confidence, summary, created_at)
        VALUES (1, '[]', '[]', '低', '[]', '可参与', 80, 'historical', '2025-08-29 12:10:00')
        """
    )
    cursor.execute(
        """
        INSERT INTO ai_analysis
        (snapshot_id, affected_sectors, recommended_stocks, risk_level, risk_factors, advice, confidence, summary, created_at)
        VALUES (2, '[]', '[]', '高', '[]', '回避', 95, 'future', '2026-04-24 10:10:00')
        """
    )
    conn.commit()
    conn.close()

    checkpoint = "2025-08-29 13:30:00"

    assert db.get_snapshot_as_of(as_of=checkpoint, within_hours=48)["total_score"] == 650
    assert db.get_sentiment_as_of(as_of=checkpoint, within_hours=48)["sentiment_index"] == 70
    assert db.get_ai_analysis_as_of(as_of=checkpoint, within_hours=48)["summary"] == "historical"


def test_resolve_binding_keeps_base_template_without_enough_switch_evidence(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("aggressive_v23")

    monkeypatch.setattr(
        controller,
        "_build_dynamic_signal",
        lambda **kwargs: {  # noqa: ARG005 - test seam
            "score": -0.36,
            "confidence": 0.52,
            "components": [
                {
                    "key": "market",
                    "weight": 0.35,
                    "score": -0.36,
                    "confidence": 0.52,
                    "fresh": True,
                }
            ],
        },
    )

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="002463",
        stock_name="沪电股份",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    dynamic = binding["dynamic_strategy"]

    assert binding["profile_id"] == "aggressive_v23"
    assert dynamic["recommended_template_variant"] == "conservative"
    assert dynamic["applied_template_variant"] == "aggressive"
    assert dynamic["template_switch_applied"] is False
    assert dynamic["template_switch_reason"] == "insufficient_evidence"


def test_resolve_binding_switches_template_when_fresh_multi_source_evidence_is_strong(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("aggressive_v23")

    monkeypatch.setattr(
        controller,
        "_build_dynamic_signal",
        lambda **kwargs: {  # noqa: ARG005 - test seam
            "score": -0.54,
            "confidence": 0.82,
            "components": [
                {
                    "key": "market",
                    "weight": 0.35,
                    "score": -0.82,
                    "confidence": 0.75,
                    "fresh": True,
                },
                {
                    "key": "ai",
                    "weight": 0.25,
                    "score": -0.61,
                    "confidence": 0.92,
                    "fresh": True,
                },
            ],
        },
    )

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="002463",
        stock_name="沪电股份",
        ai_dynamic_strategy="hybrid",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    dynamic = binding["dynamic_strategy"]

    assert binding["profile_id"] == "conservative_v23"
    assert dynamic["recommended_template_variant"] == "conservative"
    assert dynamic["applied_template_variant"] == "conservative"
    assert dynamic["template_switch_applied"] is True
    assert dynamic["template_switch_reason"] == "strong_opposite_signal"


def test_resolve_binding_weights_mode_uses_risk_on_overlay_bucket(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("stable_v23")

    monkeypatch.setattr(
        controller,
        "_build_dynamic_signal",
        lambda **kwargs: {  # noqa: ARG005 - test seam
            "score": 0.34,
            "confidence": 0.82,
            "components": [
                {"key": "market", "weight": 0.35, "score": 0.44, "confidence": 0.80, "fresh": True},
                {"key": "ai", "weight": 0.25, "score": 0.32, "confidence": 0.84, "fresh": True},
            ],
        },
    )

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="300750",
        stock_name="宁德时代",
        ai_dynamic_strategy="weights",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    dynamic = binding["dynamic_strategy"]
    scoring = StrategyScoringConfig(
        schema_version=str(binding["config"]["schema_version"]),
        base=binding["config"]["base"],
        profiles=binding["config"]["profiles"],
    )
    candidate = scoring.resolve("candidate")

    assert binding["profile_id"] == "stable_v23"
    assert dynamic["template_switch_applied"] is False
    assert dynamic["template_switch_reason"] == "weights_only"
    assert dynamic["overlay_regime"] == "risk_on"
    assert candidate["dual_track"]["track_weights"] == {"tech": 1.11, "context": 0.89}
    assert candidate["dual_track"]["fusion_buy_threshold"] == 0.39
    assert candidate["dual_track"]["fusion_sell_threshold"] == -0.28
    assert candidate["dual_track"]["sell_precedence_gate"] == -0.38
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.44
    adjustments = {item["path"]: item for item in dynamic["adjustments"]}
    assert adjustments["profiles.candidate.dual_track.fusion_buy_threshold"]["before"] == 0.43
    assert adjustments["profiles.candidate.dual_track.fusion_buy_threshold"]["after"] == 0.39
    assert adjustments["profiles.candidate.dual_track.fusion_sell_threshold"]["before"] == -0.26
    assert adjustments["profiles.candidate.dual_track.fusion_sell_threshold"]["after"] == -0.28
    assert adjustments["profiles.candidate.dual_track.sell_precedence_gate"]["before"] == -0.34
    assert adjustments["profiles.candidate.dual_track.sell_precedence_gate"]["after"] == -0.38
    assert adjustments["profiles.candidate.dual_track.min_fusion_confidence"]["after"] == 0.44


def test_resolve_binding_weights_mode_uses_risk_off_overlay_bucket(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("stable_v23")

    monkeypatch.setattr(
        controller,
        "_build_dynamic_signal",
        lambda **kwargs: {  # noqa: ARG005 - test seam
            "score": -0.37,
            "confidence": 0.80,
            "components": [
                {"key": "market", "weight": 0.35, "score": -0.41, "confidence": 0.76, "fresh": True},
                {"key": "ai", "weight": 0.25, "score": -0.34, "confidence": 0.84, "fresh": True},
            ],
        },
    )

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="300750",
        stock_name="宁德时代",
        ai_dynamic_strategy="weights",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    dynamic = binding["dynamic_strategy"]
    scoring = StrategyScoringConfig(
        schema_version=str(binding["config"]["schema_version"]),
        base=binding["config"]["base"],
        profiles=binding["config"]["profiles"],
    )
    candidate = scoring.resolve("candidate")

    assert dynamic["overlay_regime"] == "risk_off"
    assert candidate["dual_track"]["track_weights"] == {"tech": 0.89, "context": 1.11}
    assert candidate["dual_track"]["fusion_buy_threshold"] == 0.46
    assert candidate["dual_track"]["fusion_sell_threshold"] == -0.24
    assert candidate["dual_track"]["sell_precedence_gate"] == -0.30
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.49
    adjustments = {item["path"]: item for item in dynamic["adjustments"]}
    assert adjustments["profiles.candidate.dual_track.fusion_sell_threshold"]["before"] == -0.26
    assert adjustments["profiles.candidate.dual_track.fusion_sell_threshold"]["after"] == -0.24
    assert adjustments["profiles.candidate.dual_track.sell_precedence_gate"]["before"] == -0.34
    assert adjustments["profiles.candidate.dual_track.sell_precedence_gate"]["after"] == -0.30


def test_resolve_binding_weights_mode_stays_neutral_without_confident_signal(tmp_path, monkeypatch):
    controller = DynamicStrategyController(db_file=tmp_path / "app.quant_sim.db")
    base_binding = controller.db.resolve_strategy_profile_binding("stable_v23")

    monkeypatch.setattr(
        controller,
        "_build_dynamic_signal",
        lambda **kwargs: {  # noqa: ARG005 - test seam
            "score": 0.12,
            "confidence": 0.41,
            "components": [
                {"key": "market", "weight": 0.35, "score": 0.12, "confidence": 0.41, "fresh": True},
                {"key": "ai", "weight": 0.25, "score": 0.09, "confidence": 0.42, "fresh": True},
            ],
        },
    )

    binding = controller.resolve_binding(
        base_binding=base_binding,
        stock_code="300750",
        stock_name="宁德时代",
        ai_dynamic_strategy="weights",
        ai_dynamic_strength=0.5,
        ai_dynamic_lookback=48,
    )

    dynamic = binding["dynamic_strategy"]
    scoring = StrategyScoringConfig(
        schema_version=str(binding["config"]["schema_version"]),
        base=binding["config"]["base"],
        profiles=binding["config"]["profiles"],
    )
    candidate = scoring.resolve("candidate")

    assert dynamic["overlay_regime"] == "neutral"
    assert dynamic["adjustments"] == []
    assert candidate["dual_track"]["track_weights"] == {"tech": 1.0, "context": 1.0}
    assert candidate["dual_track"]["fusion_buy_threshold"] == 0.43
    assert candidate["dual_track"]["fusion_sell_threshold"] == -0.26
    assert candidate["dual_track"]["sell_precedence_gate"] == -0.34
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.46
