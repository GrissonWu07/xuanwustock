from datetime import datetime, timedelta

from app.quant_kernel.config import StrategyScoringConfig
from app.quant_sim.dynamic_strategy import DynamicStrategyController


class _MissingMarketSectorDB:
    def get_latest_raw_data(self, key, within_hours=None):
        del key, within_hours
        return None


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
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.44


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
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.49


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
    assert candidate["dual_track"]["track_weights"] == {"tech": 1.0, "context": 1.0}
    assert candidate["dual_track"]["fusion_buy_threshold"] == 0.43
    assert candidate["dual_track"]["min_fusion_confidence"] == 0.46
