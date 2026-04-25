"""Kernel configuration dataclasses replacing stockpolicy YAML runtime config."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping

SUPPORTED_SCORER_ALGORITHMS: set[str] = {
    "piecewise",
    "linear",
    "sigmoid",
    "lookup_map",
    "condition_map",
    "composite_rule",
}

TECHNICAL_GROUP_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "trend": ("trend_direction", "ma_alignment", "ma_slope", "price_vs_ma20"),
    "momentum": ("macd_level", "macd_hist_slope", "rsi_zone", "kdj_cross"),
    "volume_confirmation": ("volume_ratio", "obv_trend"),
    "volatility_risk": ("atr_risk", "boll_position"),
}

CONTEXT_GROUP_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "market_structure": ("trend_regime", "price_structure", "momentum"),
    "risk_account": ("risk_balance", "account_posture"),
    "tradability_timing": ("liquidity", "session"),
    "source_execution": ("source_prior", "execution_feedback"),
    "external_analysis": ("stock_analysis",),
}

TECHNICAL_DIMENSIONS: tuple[str, ...] = tuple(
    dimension for dimensions in TECHNICAL_GROUP_DIMENSIONS.values() for dimension in dimensions
)
CONTEXT_DIMENSIONS: tuple[str, ...] = tuple(
    dimension for dimensions in CONTEXT_GROUP_DIMENSIONS.values() for dimension in dimensions
)
PROFILE_IDS: set[str] = {"candidate", "position"}
REASON_TEMPLATE_PATTERN = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")
KNOWN_REASON_FIELDS: set[str] = {
    "score",
    "close",
    "ma20",
    "ma60",
    "ma20_slope",
    "distance_ratio",
    "order_score",
    "dif",
    "dea",
    "hist",
    "hist_slope",
    "rsi14",
    "k",
    "d",
    "j",
    "volume_ratio",
    "obv_slope",
    "atr_pct",
    "boll_position",
    "source",
    "regime",
    "price_structure",
    "context_momentum",
    "risk_metric",
    "liquidity_value",
    "session",
    "feedback_sample_count",
    "cash_ratio",
    "stock_analysis_score",
    "stock_analysis_confidence",
    "record_id",
    "data_as_of",
}


def _deep_merge_dict(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge_dict(existing, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _default_scorers() -> dict[str, dict[str, Any]]:
    return {
        "trend_direction": {
            "algorithm": "condition_map",
            "params": {"bull_score": 1.0, "mild_bull_score": 0.3, "mild_bear_score": -0.4, "bear_score": -1.0},
            "reason_template": "close/ma20/ma60={close}/{ma20}/{ma60}",
        },
        "ma_alignment": {
            "algorithm": "condition_map",
            "params": {
                "order_score_map": {"4": 1.0, "3": 0.5, "2": 0.0, "1": -0.5, "0": -1.0},
                "alignment_smooth_k": 0.2,
            },
            "reason_template": "ma order score={order_score}",
        },
        "ma_slope": {
            "algorithm": "linear",
            "params": {"slope_scale": 6.0, "neutral_band": 0.002, "intercept": 0.0, "min_clip": -1.0, "max_clip": 1.0},
            "reason_template": "ma20_slope={ma20_slope}",
        },
        "price_vs_ma20": {
            "algorithm": "piecewise",
            "params": {
                "distance_bands": [-0.08, -0.03, 0.0, 0.03, 0.08],
                "band_scores": [-1.0, -0.5, 0.0, 0.5, 1.0],
            },
            "reason_template": "distance(close,ma20)={distance_ratio}",
        },
        "macd_level": {
            "algorithm": "composite_rule",
            "params": {"hist_bands": [-0.3, -0.1, 0.1, 0.3], "dif_sign_adjust": 0.15, "combine_mode": "weighted_sum"},
            "reason_template": "dif/dea/hist={dif}/{dea}/{hist}",
        },
        "macd_hist_slope": {
            "algorithm": "piecewise",
            "params": {"slope_bands": [-0.2, -0.05, 0.05, 0.2], "band_scores": [-1.0, -0.4, 0.4, 1.0]},
            "reason_template": "macd_hist_slope={hist_slope}",
        },
        "rsi_zone": {
            "algorithm": "piecewise",
            "params": {
                "oversold": 28.0,
                "neutral_low": 42.0,
                "neutral_high": 68.0,
                "overbought": 72.0,
                "zone_scores": {"oversold": 0.6, "neutral": 0.1, "overbought": -0.4},
            },
            "reason_template": "rsi14={rsi14}",
        },
        "kdj_cross": {
            "algorithm": "composite_rule",
            "params": {"cross_strength_bands": [-0.5, -0.1, 0.1, 0.5], "extreme_zone_adjust": 0.2, "combine_mode": "rule_map"},
            "reason_template": "k/d/j={k}/{d}/{j}",
        },
        "volume_ratio": {
            "algorithm": "piecewise",
            "params": {"ratio_bands": [0.6, 0.9, 1.2, 1.8], "ratio_scores": [-0.8, -0.2, 0.2, 0.7]},
            "reason_template": "volume_ratio={volume_ratio}",
        },
        "obv_trend": {
            "algorithm": "piecewise",
            "params": {"window": 8, "slope_bands": [-0.15, -0.03, 0.03, 0.15], "slope_scores": [-0.8, -0.2, 0.2, 0.8]},
            "reason_template": "obv_slope={obv_slope}",
        },
        "atr_risk": {
            "algorithm": "piecewise",
            "params": {"atr_pct_bands": [0.02, 0.05, 0.09, 0.14], "risk_scores": [0.4, 0.1, -0.3, -0.8]},
            "reason_template": "atr_pct={atr_pct}",
        },
        "boll_position": {
            "algorithm": "piecewise",
            "params": {"position_bands": [0.1, 0.25, 0.75, 0.9], "position_scores": [-0.6, 0.2, 0.2, -0.6]},
            "reason_template": "boll_position={boll_position}",
        },
        "source_prior": {
            "algorithm": "lookup_map",
            "params": {
                "source_score_map": {
                    "main_force": 0.28,
                    "profit_growth": 0.22,
                    "low_price_bull": 0.18,
                    "value_stock": 0.2,
                    "small_cap": 0.16,
                    "manual": 0.12,
                    "default": 0.1,
                }
            },
            "reason_template": "source={source}, score={score}",
        },
        "trend_regime": {
            "algorithm": "lookup_map",
            "params": {"regime_score_map": {"bull": 0.24, "sideways": 0.0, "bear": -0.24}},
            "reason_template": "regime={regime}",
        },
        "price_structure": {
            "algorithm": "condition_map",
            "params": {"structure_score_map": {"bull_stack": 0.14, "above_ma20": 0.08, "bear_stack": -0.14, "below_ma20": -0.08}},
            "reason_template": "price_structure={price_structure}",
        },
        "momentum": {
            "algorithm": "piecewise",
            "params": {"momentum_bands": [-0.6, -0.2, 0.2, 0.6], "momentum_scores": [-0.12, -0.04, 0.04, 0.12]},
            "reason_template": "context_momentum={context_momentum}",
        },
        "risk_balance": {
            "algorithm": "piecewise",
            "params": {"risk_bands": [28.0, 45.0, 68.0, 78.0], "risk_scores": [-0.05, 0.02, 0.04, -0.08]},
            "reason_template": "risk_metric={risk_metric}",
        },
        "liquidity": {
            "algorithm": "piecewise",
            "params": {"liq_bands": [0.7, 0.9, 1.2, 1.8], "liq_scores": [-0.08, -0.04, 0.05, 0.09]},
            "reason_template": "liquidity={liquidity_value}",
        },
        "session": {
            "algorithm": "lookup_map",
            "params": {"session_score_map": {"open": -0.02, "mid": 0.0, "close": 0.03}},
            "reason_template": "session={session}",
        },
        "execution_feedback": {
            "algorithm": "composite_rule",
            "params": {
                "feedback_decay_half_life": 20.0,
                "min_feedback_samples": 5.0,
                "success_weight": 0.15,
                "failure_weight": -0.20,
                "execution_feedback_score_cap": 0.25,
            },
            "reason_template": "feedback samples={feedback_sample_count}, score={score}",
        },
        "account_posture": {
            "algorithm": "piecewise",
            "params": {"cash_ratio_bands": [0.1, 0.25, 0.55, 0.8], "posture_scores": [-0.3, 0.0, 0.3, 0.1]},
            "reason_template": "cash_ratio={cash_ratio}",
        },
        "stock_analysis": {
            "algorithm": "linear",
            "params": {"min_clip": -1.0, "max_clip": 1.0, "intercept": 0.0},
            "reason_template": "record={record_id}, score={stock_analysis_score}, confidence={stock_analysis_confidence}, data_as_of={data_as_of}",
        },
    }


def _default_strategy_profile_payload() -> dict[str, Any]:
    base_technical_weights = {dimension: 1.0 for dimension in TECHNICAL_DIMENSIONS}
    base_context_weights = {dimension: 1.0 for dimension in CONTEXT_DIMENSIONS}
    scorers = _default_scorers()
    return {
        "base": {
            "technical": {
                "group_weights": {group: 1.0 for group in TECHNICAL_GROUP_DIMENSIONS},
                "dimension_weights": base_technical_weights,
                "scorers": {dimension: scorers[dimension] for dimension in TECHNICAL_DIMENSIONS},
            },
            "context": {
                "group_weights": {group: 1.0 for group in CONTEXT_GROUP_DIMENSIONS},
                "dimension_groups": {group: list(dimensions) for group, dimensions in CONTEXT_GROUP_DIMENSIONS.items()},
                "optional_groups": ["external_analysis"],
                "dimension_weights": base_context_weights,
                "scorers": {dimension: scorers[dimension] for dimension in CONTEXT_DIMENSIONS},
                "execution_feedback_policy": {
                    "feedback_decay_half_life": 20.0,
                    "min_feedback_samples": 5.0,
                    "execution_feedback_score_cap": 0.25,
                },
                "stock_analysis_policy": {
                    "enabled": True,
                    "ttl_hours": 48.0,
                    "min_confidence": 0.45,
                    "max_positive_contribution": 0.08,
                    "max_negative_contribution": -0.08,
                },
            },
            "dual_track": {
                "mode": "rule_only",
                "track_weights": {"tech": 1.0, "context": 1.0},
                "fusion_buy_threshold": 0.76,
                "fusion_sell_threshold": -0.17,
                "sell_precedence_gate": -0.50,
                "min_fusion_confidence": 0.50,
                "min_tech_score_for_buy": 0.0,
                "min_context_score_for_buy": 0.0,
                "min_tech_confidence_for_buy": 0.50,
                "min_context_confidence_for_buy": 0.50,
                "lambda_divergence": 0.60,
                "lambda_sign_conflict": 0.40,
                "sign_conflict_min_abs_score": 0.10,
                "threshold_mode": "static",
                "buy_vol_k": 0.20,
                "sell_vol_k": 0.20,
                "threshold_volatility_missing_policy": "neutral_zero",
            },
            "veto": {
                "source_mode": "legacy",
                "thresholds": {
                    "risk_stop": {"enabled": True, "stop_loss_pct": 0.08, "max_atr_pct": 0.12},
                    "hard_constraint": {"enabled": True, "min_liquidity_score": -0.6},
                    "context_veto": {"enabled": True, "min_context_score": -0.7},
                },
            },
        },
        "profiles": {
            "candidate": {
                "technical": {
                    "group_weights": {"trend": 1.3, "momentum": 1.2, "volume_confirmation": 0.9, "volatility_risk": 0.8},
                    "dimension_weights": {
                        "trend_direction": 1.2,
                        "ma_alignment": 0.8,
                        "ma_slope": 1.0,
                        "price_vs_ma20": 0.8,
                        "macd_hist_slope": 1.2,
                        "kdj_cross": 0.6,
                    },
                },
                "context": {
                    "group_weights": {
                        "market_structure": 1.4,
                        "risk_account": 1.1,
                        "tradability_timing": 0.7,
                        "source_execution": 0.7,
                        "external_analysis": 0.2,
                    },
                    "dimension_weights": {
                        "trend_regime": 1.2,
                        "price_structure": 1.1,
                        "momentum": 0.8,
                        "risk_balance": 1.2,
                        "account_posture": 1.0,
                        "liquidity": 1.0,
                        "session": 0.5,
                        "source_prior": 1.0,
                        "execution_feedback": 0.8,
                        "stock_analysis": 0.5,
                    },
                },
                "dual_track": {"fusion_buy_threshold": 0.78, "sell_precedence_gate": -0.52},
            },
            "position": {
                "technical": {
                    "group_weights": {"trend": 1.1, "momentum": 0.8, "volume_confirmation": 0.9, "volatility_risk": 1.5},
                    "dimension_weights": {
                        "trend_direction": 1.1,
                        "ma_alignment": 0.8,
                        "ma_slope": 1.2,
                        "price_vs_ma20": 0.8,
                        "atr_risk": 1.5,
                        "boll_position": 1.2,
                        "kdj_cross": 0.5,
                    },
                },
                "context": {
                    "group_weights": {
                        "market_structure": 1.0,
                        "risk_account": 1.5,
                        "tradability_timing": 0.6,
                        "source_execution": 0.7,
                        "external_analysis": 0.15,
                    },
                    "dimension_weights": {
                        "trend_regime": 1.0,
                        "price_structure": 1.0,
                        "momentum": 0.7,
                        "risk_balance": 1.4,
                        "account_posture": 1.3,
                        "liquidity": 0.9,
                        "session": 0.4,
                        "source_prior": 0.7,
                        "execution_feedback": 1.1,
                        "stock_analysis": 0.4,
                    },
                },
                "dual_track": {"fusion_buy_threshold": 0.72, "sell_precedence_gate": -0.48},
            },
        },
    }


STRATEGY_SCORING_CONFIG: dict[str, Any] = _default_strategy_profile_payload()


@dataclass(frozen=True)
class StrategyScoringConfig:
    schema_version: str
    base: Mapping[str, Any]
    profiles: Mapping[str, Mapping[str, Any]]

    @classmethod
    def default(cls) -> "StrategyScoringConfig":
        payload = deepcopy(STRATEGY_SCORING_CONFIG)
        return cls(schema_version="quant_explain", base=payload["base"], profiles=payload["profiles"])

    def resolve(self, profile: str | None = None) -> dict[str, Any]:
        selected = (profile or "").strip().lower()
        if not selected:
            merged = deepcopy(self.base)
        else:
            if selected not in PROFILE_IDS:
                raise ValueError(f"unsupported strategy profile: {profile}")
            merged = _deep_merge_dict(self.base, self.profiles.get(selected, {}))
        self._validate_core(merged)
        return merged

    def _validate_core(self, config: Mapping[str, Any]) -> None:
        dual_track = config.get("dual_track")
        if not isinstance(dual_track, Mapping):
            raise ValueError("dual_track config is required")
        mode = str(dual_track.get("mode") or "")
        if mode not in {"rule_only", "weighted_only", "hybrid"}:
            raise ValueError(f"invalid dual_track.mode: {mode}")

        track_weights = dual_track.get("track_weights")
        if not isinstance(track_weights, Mapping):
            raise ValueError("dual_track.track_weights is required")
        tech_weight = float(track_weights.get("tech") or 0.0)
        context_weight = float(track_weights.get("context") or 0.0)
        if tech_weight < 0 or context_weight < 0:
            raise ValueError("dual_track.track_weights must be >= 0")
        if tech_weight + context_weight <= 0:
            raise ValueError("dual_track.track_weights.tech + context must be > 0")

        buy_threshold = float(dual_track.get("fusion_buy_threshold"))
        sell_threshold = float(dual_track.get("fusion_sell_threshold"))
        if buy_threshold <= sell_threshold:
            raise ValueError("fusion_buy_threshold must be greater than fusion_sell_threshold")

        threshold_mode = str(dual_track.get("threshold_mode") or "static")
        sell_precedence_gate = float(dual_track.get("sell_precedence_gate"))
        if threshold_mode == "static":
            if sell_precedence_gate > sell_threshold:
                raise ValueError("sell_precedence_gate must be <= fusion_sell_threshold in static mode")
        elif threshold_mode == "volatility_adjusted":
            sell_vol_k = float(dual_track.get("sell_vol_k") or 0.0)
            if sell_precedence_gate > (sell_threshold - sell_vol_k):
                raise ValueError("sell_precedence_gate must be <= fusion_sell_threshold - sell_vol_k in volatility_adjusted mode")
        else:
            raise ValueError(f"invalid threshold_mode: {threshold_mode}")

        technical = config.get("technical")
        context = config.get("context")
        if not isinstance(technical, Mapping) or not isinstance(context, Mapping):
            raise ValueError("technical and context scoring configs are required")

        self._validate_track(technical, TECHNICAL_GROUP_DIMENSIONS, TECHNICAL_DIMENSIONS, "technical")
        self._validate_track(context, CONTEXT_GROUP_DIMENSIONS, CONTEXT_DIMENSIONS, "context")
        if mode in {"weighted_only", "hybrid"}:
            technical_group_weights = technical.get("group_weights") if isinstance(technical.get("group_weights"), Mapping) else {}
            context_group_weights = context.get("group_weights") if isinstance(context.get("group_weights"), Mapping) else {}
            if self._group_weights_uniform(technical_group_weights, TECHNICAL_GROUP_DIMENSIONS):
                raise ValueError("technical.group_weights cannot be uniformly equal in weighted/hybrid production defaults")
            if self._group_weights_uniform(context_group_weights, CONTEXT_GROUP_DIMENSIONS):
                raise ValueError("context.group_weights cannot be uniformly equal in weighted/hybrid production defaults")
            if float(context_group_weights.get("source_execution") or 0.0) > float(context_group_weights.get("risk_account") or 0.0):
                raise ValueError("context.group_weights.source_execution must be <= risk_account in weighted/hybrid production defaults")

    def _validate_track(
        self,
        track: Mapping[str, Any],
        expected_groups: Mapping[str, tuple[str, ...]],
        expected_dimensions: tuple[str, ...],
        track_name: str,
    ) -> None:
        group_weights = track.get("group_weights")
        if not isinstance(group_weights, Mapping):
            raise ValueError(f"{track_name}.group_weights is required")
        unknown_groups = set(group_weights) - set(expected_groups)
        if unknown_groups:
            raise ValueError(f"{track_name}.group_weights has unknown groups: {sorted(unknown_groups)}")
        missing_groups = set(expected_groups) - set(group_weights)
        if missing_groups:
            raise ValueError(f"{track_name}.group_weights missing groups: {sorted(missing_groups)}")

        groups = expected_groups
        if track_name == "context":
            dimension_groups = track.get("dimension_groups")
            if not isinstance(dimension_groups, Mapping):
                raise ValueError("context.dimension_groups is required")
            unknown_dimension_groups = set(dimension_groups) - set(expected_groups)
            if unknown_dimension_groups:
                raise ValueError(f"context.dimension_groups has unknown groups: {sorted(unknown_dimension_groups)}")
            groups = {}
            seen_dimensions: set[str] = set()
            for group_id, raw_dimensions in dimension_groups.items():
                if not isinstance(raw_dimensions, (list, tuple)) or not raw_dimensions:
                    raise ValueError(f"context.dimension_groups[{group_id}] must be a non-empty list")
                dimensions = tuple(str(item) for item in raw_dimensions)
                groups[str(group_id)] = dimensions
                for dimension in dimensions:
                    if dimension in seen_dimensions:
                        raise ValueError(f"context.dimension_groups duplicate dimension: {dimension}")
                    seen_dimensions.add(dimension)
            if seen_dimensions != set(expected_dimensions):
                missing = set(expected_dimensions) - seen_dimensions
                unknown = seen_dimensions - set(expected_dimensions)
                if missing:
                    raise ValueError(f"context.dimension_groups missing dimensions: {sorted(missing)}")
                if unknown:
                    raise ValueError(f"context.dimension_groups unknown dimensions: {sorted(unknown)}")

        if float(sum(max(float(group_weights.get(group) or 0.0), 0.0) for group in expected_groups)) <= 0:
            raise ValueError(f"{track_name}.group_weights must have positive total weight")

        dimension_weights = track.get("dimension_weights")
        if not isinstance(dimension_weights, Mapping):
            raise ValueError(f"{track_name}.dimension_weights is required")
        unknown_dimensions = set(dimension_weights) - set(expected_dimensions)
        if unknown_dimensions:
            raise ValueError(f"{track_name}.dimension_weights has unknown dimensions: {sorted(unknown_dimensions)}")
        for dimension in expected_dimensions:
            if dimension not in dimension_weights:
                raise ValueError(f"{track_name}.dimension_weights missing: {dimension}")
            if float(dimension_weights[dimension]) < 0:
                raise ValueError(f"{track_name}.dimension_weights[{dimension}] must be >= 0")
        if float(sum(float(dimension_weights.get(dimension) or 0.0) for dimension in expected_dimensions)) <= 0:
            raise ValueError(f"{track_name}.dimension_weights must have positive total weight")

        for group_id, dimensions in groups.items():
            if float(group_weights.get(group_id) or 0.0) > 0 and float(
                sum(float(dimension_weights.get(dimension) or 0.0) for dimension in dimensions)
            ) <= 0:
                raise ValueError(
                    f"{track_name}.group_weights[{group_id}] is positive but all group dimensions have zero weight"
                )

        scorers = track.get("scorers")
        if not isinstance(scorers, Mapping):
            raise ValueError(f"{track_name}.scorers is required")
        unknown_scorer_dimensions = set(scorers) - set(expected_dimensions)
        if unknown_scorer_dimensions:
            raise ValueError(f"{track_name}.scorers has unknown dimensions: {sorted(unknown_scorer_dimensions)}")
        for dimension in expected_dimensions:
            scorer = scorers.get(dimension)
            if not isinstance(scorer, Mapping):
                raise ValueError(f"{track_name}.scorers missing: {dimension}")
            algorithm = str(scorer.get("algorithm") or "")
            if algorithm not in SUPPORTED_SCORER_ALGORITHMS:
                raise ValueError(f"{track_name}.scorers[{dimension}].algorithm is unsupported: {algorithm}")
            if not isinstance(scorer.get("params"), Mapping):
                raise ValueError(f"{track_name}.scorers[{dimension}].params is required")
            reason_template = scorer.get("reason_template")
            if not isinstance(reason_template, str) or not reason_template.strip():
                raise ValueError(f"{track_name}.scorers[{dimension}].reason_template is required")
            self._validate_reason_template(track_name=track_name, dimension=dimension, scorer=scorer)

    @staticmethod
    def _group_weights_uniform(weights: Mapping[str, Any], expected_groups: Mapping[str, tuple[str, ...]]) -> bool:
        values = [float(weights.get(group) or 0.0) for group in expected_groups]
        if not values:
            return True
        baseline = values[0]
        return all(abs(value - baseline) < 1e-9 for value in values)

    def _validate_reason_template(self, *, track_name: str, dimension: str, scorer: Mapping[str, Any]) -> None:
        reason_template = str(scorer.get("reason_template") or "")
        params = scorer.get("params")
        param_keys = set(params.keys()) if isinstance(params, Mapping) else set()
        placeholders = set(REASON_TEMPLATE_PATTERN.findall(reason_template))
        for placeholder in placeholders:
            if placeholder not in KNOWN_REASON_FIELDS and placeholder not in param_keys:
                raise ValueError(
                    f"{track_name}.scorers[{dimension}].reason_template has unknown placeholder: {placeholder}"
                )


@dataclass(frozen=True)
class DualTrackPositionRule:
    tech_score_min: float
    context_score_min: float | None = None
    context_score_max: float | None = None
    position_ratio: float = 0.0


@dataclass(frozen=True)
class DualTrackConfig:
    veto_threshold: float
    extreme_bullish_threshold: float
    resonance_full: DualTrackPositionRule
    resonance_heavy: DualTrackPositionRule
    resonance_moderate: DualTrackPositionRule
    resonance_standard: DualTrackPositionRule
    divergence_light: DualTrackPositionRule
    divergence_none: DualTrackPositionRule


@dataclass(frozen=True)
class SourceContextConfig:
    default_weight: float
    source_weights: Mapping[str, float]


@dataclass(frozen=True)
class TechnicalScoreConfig:
    trend_up_bonus: float
    trend_down_penalty: float
    alignment_bonus: float
    misalignment_penalty: float
    macd_positive_bonus: float
    macd_negative_penalty: float
    balanced_rsi_min: float
    balanced_rsi_max: float
    balanced_rsi_bonus: float
    overbought_rsi_threshold: float
    overbought_rsi_penalty: float
    oversold_rsi_threshold: float
    oversold_rsi_bonus: float
    high_volume_ratio_threshold: float
    high_volume_ratio_bonus: float
    low_volume_ratio_threshold: float
    low_volume_ratio_penalty: float
    buy_threshold: float
    sell_threshold: float
    min_confidence: float
    max_confidence: float
    base_confidence: float
    tech_confidence_weight: float
    context_confidence_weight: float


@dataclass(frozen=True)
class PositionScoreConfig:
    below_ma20_penalty: float
    negative_macd_penalty: float
    deep_loss_threshold: float
    deep_loss_penalty: float
    strong_profit_threshold: float
    strong_profit_penalty: float
    guarded_profit_threshold: float
    guarded_profit_bonus: float
    overbought_rsi_threshold: float
    overbought_rsi_penalty: float


@dataclass(frozen=True)
class MarketRegimeConfig:
    bullish_threshold: float
    weak_threshold: float
    trend_up_weight: float
    trend_down_weight: float
    above_ma20_weight: float
    below_ma20_weight: float
    above_ma60_weight: float
    below_ma60_weight: float
    positive_macd_weight: float
    negative_macd_weight: float
    strong_volume_weight: float
    weak_volume_weight: float


@dataclass(frozen=True)
class FundamentalQualityConfig:
    strong_threshold: float
    weak_threshold: float
    profit_growth_strong: float
    profit_growth_weak: float
    roe_strong: float
    roe_weak: float
    pe_reasonable_max: float
    pe_expensive_min: float
    pb_reasonable_max: float
    pb_expensive_min: float
    strong_bonus: float
    weak_penalty: float


@dataclass(frozen=True)
class RiskStylePreset:
    label: str
    buy_threshold_offset: float
    sell_threshold_offset: float
    max_position_ratio: float
    confidence_bonus: float
    allow_pyramiding: bool


@dataclass(frozen=True)
class TimeframeProfile:
    key: str
    buy_threshold: float
    sell_threshold: float
    max_position_ratio: float
    allow_pyramiding: bool
    confirmation: str


@dataclass(frozen=True)
class QuantKernelConfig:
    dual_track: DualTrackConfig
    source_context: SourceContextConfig
    technical: TechnicalScoreConfig
    position_scoring: PositionScoreConfig
    market_regime: MarketRegimeConfig
    fundamental_quality: FundamentalQualityConfig
    risk_style_presets: Mapping[str, RiskStylePreset]
    timeframe_profiles: Mapping[str, TimeframeProfile]
    strategy_scoring: StrategyScoringConfig

    def resolve_strategy_scoring(self, profile: str | None = None) -> dict[str, Any]:
        return self.strategy_scoring.resolve(profile)

    @classmethod
    def default(cls) -> "QuantKernelConfig":
        return cls(
            dual_track=DualTrackConfig(
                veto_threshold=-0.5,
                extreme_bullish_threshold=0.8,
                resonance_full=DualTrackPositionRule(tech_score_min=0.75, context_score_min=0.6, position_ratio=1.0),
                resonance_heavy=DualTrackPositionRule(tech_score_min=0.6, context_score_min=0.6, position_ratio=0.8),
                resonance_moderate=DualTrackPositionRule(tech_score_min=0.75, context_score_min=0.3, position_ratio=0.6),
                resonance_standard=DualTrackPositionRule(tech_score_min=0.6, context_score_min=0.3, position_ratio=0.5),
                divergence_light=DualTrackPositionRule(
                    tech_score_min=0.75,
                    context_score_min=0.0,
                    context_score_max=0.3,
                    position_ratio=0.3,
                ),
                divergence_none=DualTrackPositionRule(tech_score_min=-1.0, context_score_max=0.0, position_ratio=0.0),
            ),
            source_context=SourceContextConfig(
                default_weight=0.1,
                source_weights={
                    "main_force": 0.28,
                    "profit_growth": 0.22,
                    "low_price_bull": 0.18,
                    "value_stock": 0.2,
                    "small_cap": 0.16,
                    "manual": 0.12,
                },
            ),
            technical=TechnicalScoreConfig(
                trend_up_bonus=0.35,
                trend_down_penalty=0.35,
                alignment_bonus=0.25,
                misalignment_penalty=0.25,
                macd_positive_bonus=0.15,
                macd_negative_penalty=0.15,
                balanced_rsi_min=45,
                balanced_rsi_max=68,
                balanced_rsi_bonus=0.1,
                overbought_rsi_threshold=75,
                overbought_rsi_penalty=0.12,
                oversold_rsi_threshold=25,
                oversold_rsi_bonus=0.08,
                high_volume_ratio_threshold=1.2,
                high_volume_ratio_bonus=0.08,
                low_volume_ratio_threshold=0.8,
                low_volume_ratio_penalty=0.05,
                buy_threshold=0.6,
                sell_threshold=-0.3,
                min_confidence=0.35,
                max_confidence=0.95,
                base_confidence=0.58,
                tech_confidence_weight=0.22,
                context_confidence_weight=0.08,
            ),
            position_scoring=PositionScoreConfig(
                below_ma20_penalty=0.25,
                negative_macd_penalty=0.2,
                deep_loss_threshold=-5.0,
                deep_loss_penalty=0.35,
                strong_profit_threshold=10.0,
                strong_profit_penalty=0.15,
                guarded_profit_threshold=2.0,
                guarded_profit_bonus=0.08,
                overbought_rsi_threshold=75.0,
                overbought_rsi_penalty=0.12,
            ),
            market_regime=MarketRegimeConfig(
                bullish_threshold=0.45,
                weak_threshold=-0.2,
                trend_up_weight=0.24,
                trend_down_weight=0.24,
                above_ma20_weight=0.16,
                below_ma20_weight=0.16,
                above_ma60_weight=0.16,
                below_ma60_weight=0.16,
                positive_macd_weight=0.16,
                negative_macd_weight=0.16,
                strong_volume_weight=0.1,
                weak_volume_weight=0.1,
            ),
            fundamental_quality=FundamentalQualityConfig(
                strong_threshold=0.45,
                weak_threshold=-0.15,
                profit_growth_strong=25.0,
                profit_growth_weak=-10.0,
                roe_strong=15.0,
                roe_weak=5.0,
                pe_reasonable_max=30.0,
                pe_expensive_min=60.0,
                pb_reasonable_max=3.5,
                pb_expensive_min=8.0,
                strong_bonus=0.22,
                weak_penalty=0.22,
            ),
            risk_style_presets={
                "激进": RiskStylePreset(
                    label="激进",
                    buy_threshold_offset=-0.04,
                    sell_threshold_offset=-0.03,
                    max_position_ratio=0.8,
                    confidence_bonus=0.04,
                    allow_pyramiding=True,
                ),
                "稳重": RiskStylePreset(
                    label="稳重",
                    buy_threshold_offset=0.0,
                    sell_threshold_offset=0.0,
                    max_position_ratio=0.6,
                    confidence_bonus=0.0,
                    allow_pyramiding=False,
                ),
                "保守": RiskStylePreset(
                    label="保守",
                    buy_threshold_offset=0.08,
                    sell_threshold_offset=0.05,
                    max_position_ratio=0.35,
                    confidence_bonus=-0.03,
                    allow_pyramiding=False,
                ),
            },
            timeframe_profiles={
                "1d": TimeframeProfile(
                    key="1d",
                    buy_threshold=0.6,
                    sell_threshold=-0.3,
                    max_position_ratio=0.6,
                    allow_pyramiding=False,
                    confirmation="日线方向确认",
                ),
                "30m": TimeframeProfile(
                    key="30m",
                    buy_threshold=0.68,
                    sell_threshold=-0.22,
                    max_position_ratio=0.5,
                    allow_pyramiding=False,
                    confirmation="30分钟信号确认",
                ),
                "1d+30m": TimeframeProfile(
                    key="1d+30m",
                    buy_threshold=0.72,
                    sell_threshold=-0.2,
                    max_position_ratio=0.45,
                    allow_pyramiding=False,
                    confirmation="日线方向 + 30分钟共振确认",
                ),
            },
            strategy_scoring=StrategyScoringConfig.default(),
        )
