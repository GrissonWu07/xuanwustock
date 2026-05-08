from __future__ import annotations

from copy import deepcopy

import pytest

from app.quant_kernel.config import (
    CONTEXT_DIMENSIONS,
    STRATEGY_SCORING_CONFIG,
    TECHNICAL_DIMENSIONS,
    QuantKernelConfig,
    StrategyScoringConfig,
)
from app.quant_sim.db import QuantSimDB


def test_default_strategy_scoring_mode_is_rule_only() -> None:
    config = QuantKernelConfig.default()
    resolved = config.resolve_strategy_scoring()
    assert resolved["dual_track"]["mode"] == "rule_only"
    assert resolved["dual_track"]["track_weights"]["tech"] == 1.0
    assert resolved["dual_track"]["track_weights"]["context"] == 1.0


def test_candidate_profile_override_merges_group_and_dual_track_settings() -> None:
    config = QuantKernelConfig.default()
    resolved = config.resolve_strategy_scoring("candidate")
    assert resolved["technical"]["group_weights"]["trend"] == 1.3
    assert resolved["technical"]["group_weights"]["volatility_risk"] == 0.8
    assert resolved["dual_track"]["fusion_buy_threshold"] == 0.78
    assert resolved["dual_track"]["sell_precedence_gate"] == -0.52
    assert resolved["dual_track"]["mode"] == "rule_only"
    assert resolved["context"]["group_weights"]["market_structure"] == 1.4


def test_position_profile_override_merges_context_and_dimension_weights() -> None:
    config = QuantKernelConfig.default()
    resolved = config.resolve_strategy_scoring("position")
    assert resolved["technical"]["group_weights"]["volatility_risk"] == 1.5
    assert resolved["technical"]["dimension_weights"]["atr_risk"] == 1.5
    assert resolved["context"]["group_weights"]["risk_account"] == 1.5
    assert resolved["context"]["dimension_weights"]["execution_feedback"] == 1.1
    assert resolved["dual_track"]["fusion_buy_threshold"] == 0.72


def test_all_dimensions_have_scorers_and_reason_templates() -> None:
    config = QuantKernelConfig.default()
    resolved = config.resolve_strategy_scoring()
    technical_scorers = resolved["technical"]["scorers"]
    context_scorers = resolved["context"]["scorers"]
    for dimension in TECHNICAL_DIMENSIONS:
        scorer = technical_scorers[dimension]
        assert isinstance(scorer["algorithm"], str) and scorer["algorithm"]
        assert isinstance(scorer["params"], dict)
        assert isinstance(scorer["reason_template"], str) and scorer["reason_template"]
    for dimension in CONTEXT_DIMENSIONS:
        scorer = context_scorers[dimension]
        assert isinstance(scorer["algorithm"], str) and scorer["algorithm"]
        assert isinstance(scorer["params"], dict)
        assert isinstance(scorer["reason_template"], str) and scorer["reason_template"]


def test_invalid_profile_name_raises_value_error() -> None:
    config = QuantKernelConfig.default()
    with pytest.raises(ValueError):
        config.resolve_strategy_scoring("unknown")


def test_volatility_mode_sell_precedence_validation_is_enforced() -> None:
    payload = deepcopy(STRATEGY_SCORING_CONFIG)
    payload["base"]["dual_track"]["threshold_mode"] = "volatility_adjusted"
    payload["base"]["dual_track"]["fusion_sell_threshold"] = -0.17
    payload["base"]["dual_track"]["sell_vol_k"] = 0.20
    payload["base"]["dual_track"]["sell_precedence_gate"] = -0.30
    strategy = StrategyScoringConfig(schema_version="quant_explain/v2.3", base=payload["base"], profiles=payload["profiles"])
    with pytest.raises(ValueError):
        strategy.resolve()


def _builtin_profile_config(db: QuantSimDB, profile_id: str) -> dict:
    latest = db.get_latest_strategy_profile_version(profile_id)
    assert latest is not None
    config = latest["config"]
    assert isinstance(config, dict)
    return config


def _lifecycle_policy(config: dict) -> dict:
    policy = config["base"]["context"]["quant_universe_lifecycle_policy"]
    assert isinstance(policy, dict)
    return policy


def test_builtin_strategy_profiles_have_profile_specific_quant_lifecycle_policy(tmp_path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")

    aggressive = _lifecycle_policy(_builtin_profile_config(db, "aggressive"))
    stable = _lifecycle_policy(_builtin_profile_config(db, "stable"))
    conservative = _lifecycle_policy(_builtin_profile_config(db, "conservative"))

    assert aggressive["trial_threshold"] != stable["trial_threshold"]
    assert conservative["trial_threshold"] != stable["trial_threshold"]
    assert aggressive["trial_position_multiplier"] > stable["trial_position_multiplier"] > conservative["trial_position_multiplier"]
    assert "auto_exit_enabled" not in aggressive
    assert "auto_entry_mode" not in stable


def test_updating_stable_lifecycle_policy_does_not_overwrite_aggressive(tmp_path) -> None:
    db = QuantSimDB(tmp_path / "quant_sim.db")
    aggressive_before = _lifecycle_policy(_builtin_profile_config(db, "aggressive"))
    stable_config = deepcopy(_builtin_profile_config(db, "stable"))

    stable_config["base"]["context"]["quant_universe_lifecycle_policy"]["trial_threshold"] = 0.61
    db.update_strategy_profile("stable", config=stable_config, note="test_lifecycle_update")

    aggressive_after = _lifecycle_policy(_builtin_profile_config(db, "aggressive"))
    stable_after = _lifecycle_policy(_builtin_profile_config(db, "stable"))

    assert aggressive_after["trial_threshold"] == aggressive_before["trial_threshold"]
    assert stable_after["trial_threshold"] == 0.61
