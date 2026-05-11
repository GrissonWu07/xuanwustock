# Kernel Resonance Quality And Execution Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed kernel resonance position ratios and multiplier-only BUY execution sizing with quality-adjusted kernel positions and account-risk-capped final budgets.

**Architecture:** Add kernel-side resonance quality scoring so `resonance_standard` no longer emits a fixed 50% target. Add execution-side sizing plans that turn kernel quality position, buy tier, lifecycle status, risk budget, account-size caps, and slot capacity into one `final_budget` used for order quantity. Keep live-sim, historical replay, and live-quant drill on the same sizing semantics while preserving their existing database isolation.

**Tech Stack:** Python, dataclass-based quant kernel config, SQLite-backed `QuantSimDB`, pytest, React/TypeScript signal detail UI.

---

### Task 1: Kernel Resonance Quality Policy

**Files:**
- Modify: `app/quant_kernel/config.py`
- Create: `tests/test_kernel_resonance_quality.py`

- [ ] Add failing tests for profile-specific resonance quality defaults.

```python
from app.quant_kernel.config import QuantKernelConfig


def test_resonance_quality_defaults_are_profile_specific():
    cfg = QuantKernelConfig.default()
    policy = cfg.dual_track.resonance_quality_policy

    assert policy["aggressive"]["weights"] == {
        "tech_edge": 0.22,
        "context_edge": 0.18,
        "trend_structure": 0.28,
        "confirmation": 0.16,
        "volume": 0.16,
    }
    assert policy["stable"]["weights"]["context_edge"] == 0.20
    assert policy["conservative"]["weights"]["confirmation"] == 0.20

    assert policy["aggressive"]["position_ranges"]["resonance_full"] == {"min": 0.45, "max": 0.60}
    assert policy["stable"]["position_ranges"]["resonance_full"] == {"min": 0.36, "max": 0.50}
    assert policy["conservative"]["position_ranges"]["resonance_full"] == {"min": 0.28, "max": 0.40}
    assert policy["aggressive"]["position_ranges"]["resonance_standard"] == {"min": 0.12, "max": 0.45}
```

- [ ] Run the failing test.

Run: `python -m pytest tests\test_kernel_resonance_quality.py::test_resonance_quality_defaults_are_profile_specific -q`

Expected: FAIL because `resonance_quality_policy` does not exist.

- [ ] Implement the new config objects.

In `app/quant_kernel/config.py`, update `DualTrackPositionRule` and `DualTrackConfig`:

```python
@dataclass(frozen=True)
class DualTrackPositionRule:
    tech_score_min: float
    context_score_min: float | None = None
    context_score_max: float | None = None
    position_ratio_min: float = 0.0
    position_ratio_max: float = 0.0


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
    resonance_quality_policy: Mapping[str, Any]
```

Update `QuantKernelConfig.default()` dual-track defaults:

```python
dual_track=DualTrackConfig(
    veto_threshold=-0.5,
    extreme_bullish_threshold=0.8,
    resonance_full=DualTrackPositionRule(tech_score_min=0.75, context_score_min=0.6, position_ratio_min=0.45, position_ratio_max=0.60),
    resonance_heavy=DualTrackPositionRule(tech_score_min=0.6, context_score_min=0.6, position_ratio_min=0.38, position_ratio_max=0.55),
    resonance_moderate=DualTrackPositionRule(tech_score_min=0.75, context_score_min=0.3, position_ratio_min=0.28, position_ratio_max=0.50),
    resonance_standard=DualTrackPositionRule(tech_score_min=0.6, context_score_min=0.3, position_ratio_min=0.12, position_ratio_max=0.45),
    divergence_light=DualTrackPositionRule(tech_score_min=0.75, context_score_min=0.0, context_score_max=0.3, position_ratio_min=0.03, position_ratio_max=0.18),
    divergence_none=DualTrackPositionRule(tech_score_min=-1.0, context_score_max=0.0, position_ratio_min=0.0, position_ratio_max=0.0),
    resonance_quality_policy={
        "aggressive": {
            "weights": {"tech_edge": 0.22, "context_edge": 0.18, "trend_structure": 0.28, "confirmation": 0.16, "volume": 0.16},
            "position_ranges": {
                "resonance_full": {"min": 0.45, "max": 0.60},
                "resonance_heavy": {"min": 0.38, "max": 0.55},
                "resonance_moderate": {"min": 0.28, "max": 0.50},
                "resonance_standard": {"min": 0.12, "max": 0.45},
                "divergence_light": {"min": 0.03, "max": 0.18},
                "divergence_none": {"min": 0.0, "max": 0.0},
            },
            "volatility": {
                "ma20_deviation_penalty_threshold": 0.10,
                "ma20_deviation_penalty": 0.10,
                "recent_return_penalty_threshold": 0.07,
                "recent_return_penalty": 0.06,
                "max_volatility_penalty": 0.22,
                "hot_rsi_trend_relief_multiplier": 0.60,
            },
        },
        "stable": {
            "weights": {"tech_edge": 0.20, "context_edge": 0.20, "trend_structure": 0.25, "confirmation": 0.18, "volume": 0.17},
            "position_ranges": {
                "resonance_full": {"min": 0.36, "max": 0.50},
                "resonance_heavy": {"min": 0.30, "max": 0.44},
                "resonance_moderate": {"min": 0.22, "max": 0.38},
                "resonance_standard": {"min": 0.08, "max": 0.32},
                "divergence_light": {"min": 0.02, "max": 0.12},
                "divergence_none": {"min": 0.0, "max": 0.0},
            },
            "volatility": {
                "ma20_deviation_penalty_threshold": 0.08,
                "ma20_deviation_penalty": 0.12,
                "recent_return_penalty_threshold": 0.05,
                "recent_return_penalty": 0.08,
                "max_volatility_penalty": 0.25,
                "hot_rsi_trend_relief_multiplier": 0.60,
            },
        },
        "conservative": {
            "weights": {"tech_edge": 0.18, "context_edge": 0.22, "trend_structure": 0.25, "confirmation": 0.20, "volume": 0.15},
            "position_ranges": {
                "resonance_full": {"min": 0.28, "max": 0.40},
                "resonance_heavy": {"min": 0.22, "max": 0.35},
                "resonance_moderate": {"min": 0.16, "max": 0.30},
                "resonance_standard": {"min": 0.05, "max": 0.24},
                "divergence_light": {"min": 0.0, "max": 0.08},
                "divergence_none": {"min": 0.0, "max": 0.0},
            },
            "volatility": {
                "ma20_deviation_penalty_threshold": 0.06,
                "ma20_deviation_penalty": 0.15,
                "recent_return_penalty_threshold": 0.04,
                "recent_return_penalty": 0.10,
                "max_volatility_penalty": 0.28,
                "hot_rsi_trend_relief_multiplier": 0.60,
            },
        },
    },
)
```

- [ ] Run the targeted test again.

Run: `python -m pytest tests\test_kernel_resonance_quality.py::test_resonance_quality_defaults_are_profile_specific -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_kernel/config.py tests/test_kernel_resonance_quality.py
git commit -m "Add kernel resonance quality policy"
```

### Task 2: Kernel Quality-Adjusted Position Ratio

**Files:**
- Modify: `app/quant_kernel/decision_engine.py`
- Modify: `app/quant_kernel/runtime.py`
- Modify: `tests/test_kernel_resonance_quality.py`

- [ ] Add failing tests for quality-adjusted position ratios.

```python
from datetime import datetime

from app.quant_kernel.runtime import KernelStrategyRuntime


def _candidate_decision(snapshot: dict, profile: str = "aggressive"):
    runtime = KernelStrategyRuntime()
    return runtime.evaluate_candidate(
        candidate={"stock_code": "300001", "stock_name": "测试股", "source": "manual", "sources": ["manual"]},
        market_snapshot={
            "current_price": 10.0,
            "latest_price": 10.0,
            "ma5": 10.1,
            "ma10": 10.0,
            "ma20": 9.9,
            "ma60": 9.8,
            "ma20_slope": 0.01,
            "macd": 0.03,
            "rsi12": 60.0,
            "volume_ratio": 1.5,
            "recent_5d_return": 0.02,
            "trend": "up",
            **snapshot,
        },
        current_time=datetime(2026, 5, 10, 10, 0),
        analysis_timeframe="30m",
        strategy_mode="auto",
        strategy_profile_id=profile,
    )


def test_standard_resonance_no_longer_outputs_fixed_50_percent():
    decision = _candidate_decision(
        {
            "current_price": 10.0,
            "ma5": 10.01,
            "ma10": 10.0,
            "ma20": 9.99,
            "ma60": 9.95,
            "ma20_slope": 0.0,
            "rsi12": 84.0,
            "volume_ratio": 1.1,
        }
    )

    resonance = decision.strategy_profile["explainability"]["resonance"]
    assert resonance["rule_hit"] in {"resonance_standard", "resonance_heavy", "resonance_moderate", "resonance_full"}
    assert decision.position_ratio < 0.5
    assert resonance["quality_adjusted_position_ratio"] == decision.position_ratio
    assert "heat_penalty" in resonance["quality_penalties"]


def test_rsi_overheated_signal_gets_lower_position_than_clean_trend():
    clean = _candidate_decision({"rsi12": 62.0, "volume_ratio": 2.0, "recent_5d_return": 0.02})
    hot = _candidate_decision({"rsi12": 91.0, "volume_ratio": 2.0, "recent_5d_return": 0.09})

    assert clean.position_ratio > hot.position_ratio
    assert hot.strategy_profile["explainability"]["resonance"]["quality_penalties"]["heat_penalty"] >= 0.35
```

- [ ] Run the failing tests.

Run: `python -m pytest tests\test_kernel_resonance_quality.py -q`

Expected: FAIL because quality scoring and resonance explainability are not wired.

- [ ] Update `DualTrackResolver.resolve()` and `_calculate_position_rule()` signatures.

In `app/quant_kernel/decision_engine.py`, allow market snapshot and profile policy:

```python
def resolve(
    self,
    tech_decision: Decision,
    context_score: ContextualScore,
    stock_code: str,
    current_time: datetime,
    *,
    market_snapshot: Mapping[str, Any] | None = None,
    strategy_profile_id: str | None = None,
) -> Decision:
    ...
```

Make `_calculate_position_rule()` return:

```python
{
    "position_ratio": quality_adjusted_position_ratio,
    "rule_hit": rule_hit,
    "base_position_ratio_min": ratio_min,
    "base_position_ratio_max": ratio_max,
    "signal_quality_score": quality_score,
    "quality_components": components,
    "quality_penalties": penalties,
}
```

- [ ] Implement kernel quality helpers.

Add helper methods to `DualTrackResolver`:

```python
def _quality_policy(self, profile_id: str | None) -> Mapping[str, Any]:
    key = str(profile_id or "stable").lower()
    if "aggressive" in key:
        return self.config.resonance_quality_policy["aggressive"]
    if "conservative" in key:
        return self.config.resonance_quality_policy["conservative"]
    return self.config.resonance_quality_policy["stable"]


def _signal_quality_score(self, *, tech_score: float, ctx_score: float, market_snapshot: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = market_snapshot or {}
    weights = policy["weights"]
    volatility = policy["volatility"]
    price = float(snapshot.get("current_price") or snapshot.get("latest_price") or snapshot.get("close") or 0.0)
    ma5 = float(snapshot.get("ma5") or 0.0)
    ma10 = float(snapshot.get("ma10") or 0.0)
    ma20 = float(snapshot.get("ma20") or 0.0)
    ma20_slope = float(snapshot.get("ma20_slope") or 0.0)
    rsi = float(snapshot.get("rsi12") or snapshot.get("rsi") or 50.0)
    volume_ratio = float(snapshot.get("volume_ratio") or 1.0)
    recent_5d_return = float(snapshot.get("recent_5d_return") or 0.0)

    standard = self.config.resonance_standard
    strong_tech = self.config.resonance_full.tech_score_min
    strong_context = float(self.config.resonance_full.context_score_min or 0.0)
    tech_edge = _clamp((tech_score - standard.tech_score_min) / max(strong_tech - standard.tech_score_min, 0.0001), 0.0, 1.0)
    context_edge = _clamp((ctx_score - float(standard.context_score_min or 0.0)) / max(strong_context - float(standard.context_score_min or 0.0), 0.0001), 0.0, 1.0)

    if price > ma20 > 0 and ma5 > ma10 > ma20 and ma20_slope > 0:
        trend_structure = 1.0
    elif price > ma20 > 0 and ma20_slope >= 0:
        trend_structure = 0.6
    elif price > ma20 > 0:
        trend_structure = 0.3
    else:
        trend_structure = 0.0

    confirmation = _clamp(float(snapshot.get("trend_confirmed_checkpoints") or 0.0) / max(float(snapshot.get("required_confirm_checkpoints") or 3.0), 1.0), 0.0, 1.0)
    volume_score = 1.0 if volume_ratio >= 1.6 else 0.6 if volume_ratio >= 1.2 else 0.0

    if rsi < 75:
        heat_penalty = 0.0
    elif rsi < 85:
        heat_penalty = 0.05 + (rsi - 75.0) / 10.0 * 0.15
    elif rsi < 88:
        heat_penalty = 0.25
    else:
        heat_penalty = 0.35
    if trend_structure >= 1.0:
        heat_penalty = max(heat_penalty * float(volatility.get("hot_rsi_trend_relief_multiplier", 0.6)), heat_penalty * 0.4)

    weak_structure_penalty = 0.0
    if ma20_slope < 0:
        weak_structure_penalty += 0.20
    if ma5 > 0 and ma10 > 0 and ma5 < ma10:
        weak_structure_penalty += 0.10
    if float(snapshot.get("macd") or 0.0) > 0 and confirmation < 1.0:
        weak_structure_penalty += 0.10

    volatility_penalty = 0.0
    if ma20 > 0 and abs(price - ma20) / ma20 > float(volatility["ma20_deviation_penalty_threshold"]):
        volatility_penalty += float(volatility["ma20_deviation_penalty"])
    if recent_5d_return > float(volatility["recent_return_penalty_threshold"]):
        volatility_penalty += float(volatility["recent_return_penalty"])
    volatility_penalty = _clamp(volatility_penalty, 0.0, float(volatility["max_volatility_penalty"]))

    raw = (
        tech_edge * weights["tech_edge"]
        + context_edge * weights["context_edge"]
        + trend_structure * weights["trend_structure"]
        + confirmation * weights["confirmation"]
        + volume_score * weights["volume"]
        - heat_penalty
        - weak_structure_penalty
        - volatility_penalty
    )
    return {
        "score": _clamp(raw, 0.0, 1.0),
        "components": {
            "tech_edge_score": round(tech_edge, 6),
            "context_edge_score": round(context_edge, 6),
            "trend_structure_score": round(trend_structure, 6),
            "confirmation_score": round(confirmation, 6),
            "volume_score": round(volume_score, 6),
        },
        "penalties": {
            "heat_penalty": round(heat_penalty, 6),
            "weak_structure_penalty": round(weak_structure_penalty, 6),
            "volatility_penalty": round(volatility_penalty, 6),
            "recent_return_missing": "recent_5d_return" not in snapshot,
        },
    }
```

Define `_clamp()` at module level if not already present:

```python
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
```

- [ ] Wire `KernelStrategyRuntime` to pass snapshot/profile id.

In `app/quant_kernel/runtime.py`, change the resolver call:

```python
resolved = self.decision_engine.resolve(
    tech_decision=tech_decision,
    context_score=contextual_score,
    stock_code=stock_code,
    current_time=current_time,
    market_snapshot=market_snapshot,
    strategy_profile_id=strategy_profile.get("id") or strategy_profile.get("profile_id") or strategy_profile.get("strategy_profile_id"),
)
```

- [ ] Attach resonance explainability.

In `_attach_explainability()`, add:

```python
resonance_details = resolved.dual_track_details.get("resonance_quality") if isinstance(resolved.dual_track_details, dict) else None
if isinstance(resonance_details, dict):
    explainability["resonance"] = resonance_details
```

Also keep `dual_track.rule_hit` unchanged for existing UI.

- [ ] Run targeted tests.

Run: `python -m pytest tests\test_kernel_resonance_quality.py tests\test_quant_kernel_runtime.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_kernel/config.py app/quant_kernel/decision_engine.py app/quant_kernel/runtime.py tests/test_kernel_resonance_quality.py
git commit -m "Apply kernel resonance quality sizing"
```

### Task 3: Execution Position Cap Policy

**Files:**
- Create: `app/quant_sim/execution_sizing.py`
- Create: `tests/test_execution_sizing.py`

- [ ] Add failing tests for buy tier caps, lifecycle caps, risk budget, and account equity tiers.

```python
from app.quant_sim.execution_sizing import build_execution_sizing_plan, default_execution_position_cap_policy


def test_trial_weak_buy_uses_lifecycle_cap_and_final_budget():
    policy = default_execution_position_cap_policy("aggressive")
    plan = build_execution_sizing_plan(
        signal={
            "position_size_pct": 28.26,
            "stop_loss_pct": 5.0,
            "strategy_profile": {
                "portfolio_execution_guard": {"buy_tier": "weak_buy", "status": "downgraded"},
                "kernel_positioning": {"quality_position_pct": 28.26},
            },
        },
        total_equity=400000,
        available_cash=300000,
        slot_available_cash=300000,
        quant_status="trial",
        policy=policy,
    )

    assert plan["effective_position_pct"] == 3.0
    assert plan["final_budget"] == 12000.0
    assert "trial_weak_buy_cap" in plan["cap_reasons"]


def test_account_equity_tier_boundaries_are_mutually_exclusive():
    policy = default_execution_position_cap_policy("aggressive")
    assert build_execution_sizing_plan(signal={"position_size_pct": 60, "stop_loss_pct": 5, "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "strong_buy"}}}, total_equity=99999.99, available_cash=99999, slot_available_cash=99999, quant_status="active", policy=policy)["account_equity_tier_cap_pct"] == 18.0
    assert build_execution_sizing_plan(signal={"position_size_pct": 60, "stop_loss_pct": 5, "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "strong_buy"}}}, total_equity=100000, available_cash=100000, slot_available_cash=100000, quant_status="active", policy=policy)["account_equity_tier_cap_pct"] == 15.0
    assert build_execution_sizing_plan(signal={"position_size_pct": 60, "stop_loss_pct": 5, "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "strong_buy"}}}, total_equity=300000, available_cash=300000, slot_available_cash=300000, quant_status="active", policy=policy)["account_equity_tier_cap_pct"] == 12.5
    assert build_execution_sizing_plan(signal={"position_size_pct": 60, "stop_loss_pct": 5, "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "strong_buy"}}}, total_equity=800000, available_cash=800000, slot_available_cash=800000, quant_status="active", policy=policy)["account_equity_tier_cap_pct"] == 8.0


def test_weak_buy_skips_when_one_lot_cost_exceeds_budget():
    policy = default_execution_position_cap_policy("stable")
    plan = build_execution_sizing_plan(
        signal={"position_size_pct": 20, "stop_loss_pct": 5, "strategy_profile": {"portfolio_execution_guard": {"buy_tier": "weak_buy"}}},
        total_equity=100000,
        available_cash=100000,
        slot_available_cash=100000,
        quant_status="trial",
        policy=policy,
        price=250.0,
        lot_size=100,
    )
    assert plan["final_budget"] < plan["one_lot_cost"]
    assert plan["skip_reason"] == "weak_buy_one_lot_exceeds_risk_budget"
```

- [ ] Run the failing tests.

Run: `python -m pytest tests\test_execution_sizing.py -q`

Expected: FAIL because module does not exist.

- [ ] Implement `execution_sizing.py`.

```python
from __future__ import annotations

from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _profile_key(profile_id: str | None) -> str:
    text = str(profile_id or "").lower()
    if "aggressive" in text:
        return "aggressive"
    if "conservative" in text:
        return "conservative"
    return "stable"


def default_execution_position_cap_policy(profile_id: str | None = None) -> dict[str, Any]:
    key = _profile_key(profile_id)
    policies = {
        "aggressive": {
            "buy_tier_cap_pct": {"weak_buy": 5.0, "normal_buy": 9.0, "strong_buy": 15.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 3.0, "normal_buy": 6.0, "strong_buy": 10.0},
                "active": {"weak_buy": 5.0, "normal_buy": 9.0, "strong_buy": 15.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.30, "normal_buy": 0.45, "strong_buy": 0.65},
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 18.0, "max_cash": 18000.0},
                {"lt": 300000, "cap_pct": 15.0, "max_cash": 35000.0},
                {"lt": 800000, "cap_pct": 12.5, "max_cash": 70000.0},
                {"lt": None, "cap_pct": 8.0, "max_cash": 100000.0},
            ],
        },
        "stable": {
            "buy_tier_cap_pct": {"weak_buy": 3.5, "normal_buy": 7.0, "strong_buy": 12.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 2.0, "normal_buy": 4.5, "strong_buy": 8.0},
                "active": {"weak_buy": 3.5, "normal_buy": 7.0, "strong_buy": 12.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.20, "normal_buy": 0.35, "strong_buy": 0.50},
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 14.0, "max_cash": 14000.0},
                {"lt": 300000, "cap_pct": 12.0, "max_cash": 28000.0},
                {"lt": 800000, "cap_pct": 10.0, "max_cash": 55000.0},
                {"lt": None, "cap_pct": 6.0, "max_cash": 75000.0},
            ],
        },
        "conservative": {
            "buy_tier_cap_pct": {"weak_buy": 2.0, "normal_buy": 5.0, "strong_buy": 9.0},
            "lifecycle_cap_pct": {
                "trial": {"weak_buy": 1.0, "normal_buy": 3.0, "strong_buy": 6.0},
                "active": {"weak_buy": 2.0, "normal_buy": 5.0, "strong_buy": 9.0},
                "exit_only": {"weak_buy": 0.0, "normal_buy": 0.0, "strong_buy": 0.0},
            },
            "single_trade_risk_budget_pct": {"weak_buy": 0.10, "normal_buy": 0.25, "strong_buy": 0.40},
            "account_equity_tier_caps": [
                {"lt": 100000, "cap_pct": 10.0, "max_cash": 10000.0},
                {"lt": 300000, "cap_pct": 8.0, "max_cash": 20000.0},
                {"lt": 800000, "cap_pct": 7.0, "max_cash": 40000.0},
                {"lt": None, "cap_pct": 4.0, "max_cash": 50000.0},
            ],
        },
    }
    return policies[key]


def _account_tier(policy: dict[str, Any], total_equity: float) -> dict[str, float]:
    for row in policy["account_equity_tier_caps"]:
        limit = row.get("lt")
        if limit is None or total_equity < float(limit):
            return {"cap_pct": float(row["cap_pct"]), "max_cash": float(row["max_cash"])}
    last = policy["account_equity_tier_caps"][-1]
    return {"cap_pct": float(last["cap_pct"]), "max_cash": float(last["max_cash"])}


def _buy_tier(signal: dict[str, Any]) -> str:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    tier = str(gate.get("buy_tier") or gate.get("initial_buy_tier") or "normal_buy").strip().lower()
    return tier if tier in {"weak_buy", "normal_buy", "strong_buy"} else "normal_buy"


def build_execution_sizing_plan(
    *,
    signal: dict[str, Any],
    total_equity: float,
    available_cash: float,
    slot_available_cash: float,
    quant_status: str,
    policy: dict[str, Any],
    price: float | None = None,
    lot_size: int = 100,
) -> dict[str, Any]:
    tier = _buy_tier(signal)
    status = str(quant_status or "active").strip().lower()
    if status not in {"trial", "active", "exit_only"}:
        status = "trial"
    kernel_pct = _float(signal.get("position_size_pct"), 0.0)
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    kernel_positioning = profile.get("kernel_positioning") if isinstance(profile.get("kernel_positioning"), dict) else {}
    kernel_pct = _float(kernel_positioning.get("quality_position_pct"), kernel_pct)
    stop_loss_pct = max(_float(signal.get("stop_loss_pct"), 5.0), 0.0001)
    risk_budget_pct = _float(policy["single_trade_risk_budget_pct"][tier])
    risk_budget_position_pct = (risk_budget_pct / stop_loss_pct) * 100.0
    buy_tier_cap = _float(policy["buy_tier_cap_pct"][tier])
    lifecycle_cap = _float(policy["lifecycle_cap_pct"].get(status, policy["lifecycle_cap_pct"]["trial"])[tier])
    account_tier = _account_tier(policy, float(total_equity))
    cap_values = {
        "kernel_quality_position_pct": kernel_pct,
        "buy_tier_cap_pct": buy_tier_cap,
        "lifecycle_cap_pct": lifecycle_cap,
        "risk_budget_position_pct": risk_budget_position_pct,
        "account_equity_tier_cap_pct": account_tier["cap_pct"],
    }
    effective_pct = min(cap_values.values())
    final_budget = min(
        float(total_equity) * effective_pct / 100.0,
        account_tier["max_cash"],
        float(available_cash),
        float(slot_available_cash),
    )
    one_lot_cost = max(_float(price), 0.0) * int(lot_size or 100)
    skip_reason = None
    if tier == "weak_buy" and one_lot_cost > 0 and final_budget < one_lot_cost:
        skip_reason = "weak_buy_one_lot_exceeds_risk_budget"
    cap_reasons = [name for name, value in cap_values.items() if abs(value - effective_pct) < 1e-9]
    return {
        "buy_tier": tier,
        **{key: round(value, 6) for key, value in cap_values.items()},
        "risk_budget_pct": round(risk_budget_pct, 6),
        "expected_stop_loss_pct": round(stop_loss_pct, 6),
        "account_equity_tier_max_cash": round(account_tier["max_cash"], 4),
        "effective_position_pct": round(effective_pct, 6),
        "final_budget": round(final_budget, 4),
        "one_lot_cost": round(one_lot_cost, 4),
        "skip_reason": skip_reason,
        "cap_reasons": cap_reasons,
    }
```

- [ ] Run tests.

Run: `python -m pytest tests\test_execution_sizing.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_sim/execution_sizing.py tests/test_execution_sizing.py
git commit -m "Add execution sizing risk budget"
```

### Task 4: SignalCenter Sizing Plan Integration

**Files:**
- Modify: `app/quant_sim/signal_center_service.py`
- Modify: `tests/test_execution_sizing.py`

- [ ] Add failing test for `create_signal()` storing kernel and execution sizing payload.

```python
from pathlib import Path

from app.quant_sim.db import QuantSimDB
from app.quant_sim.signal_center_service import SignalCenterService


def test_create_signal_attaches_execution_sizing_plan(tmp_path: Path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    service = SignalCenterService(db_file=db_path)

    signal = service.create_signal(
        stock_code="000001",
        stock_name="平安银行",
        decision={
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 28.26,
            "stop_loss_pct": 5,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "selected_strategy_profile": {"id": "aggressive"},
                "kernel_positioning": {"quality_position_pct": 28.26, "rule_hit": "resonance_standard"},
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy", "buy_tier_label": "弱买"},
            },
        },
    )

    profile = signal["strategy_profile"]
    assert profile["kernel_positioning"]["quality_position_pct"] == 28.26
    assert profile["execution_sizing_plan"]["buy_tier"] == "weak_buy"
    assert profile["execution_sizing_plan"]["effective_position_pct"] <= 5.0
    assert signal["position_size_pct"] == profile["execution_sizing_plan"]["effective_position_pct"]
```

- [ ] Run failing test.

Run: `python -m pytest tests\test_execution_sizing.py::test_create_signal_attaches_execution_sizing_plan -q`

Expected: FAIL because sizing plan is not attached.

- [ ] Import and call execution sizing in `SignalCenterService`.

Add imports:

```python
from .execution_sizing import build_execution_sizing_plan, default_execution_position_cap_policy
```

Add method:

```python
def _apply_execution_sizing_plan(self, normalized: dict[str, Any]) -> dict[str, Any]:
    if str(normalized.get("action") or "").upper() != "BUY":
        return normalized
    strategy_profile = normalized.get("strategy_profile") if isinstance(normalized.get("strategy_profile"), dict) else {}
    selected = strategy_profile.get("selected_strategy_profile") if isinstance(strategy_profile.get("selected_strategy_profile"), dict) else {}
    profile_id = str(selected.get("id") or strategy_profile.get("profile_id") or "").strip()
    policy = default_execution_position_cap_policy(profile_id)
    summary = self.db.get_account_summary()
    quant_state = self.db.get_quant_universe_state(str(normalized.get("stock_code") or normalized.get("code") or ""))
    quant_status = str((quant_state or {}).get("quant_status") or "active")
    total_equity = float(summary.get("total_equity") or summary.get("initial_capital") or 0.0)
    available_cash = float(summary.get("available_cash") or summary.get("cash") or 0.0)
    slot_available_cash = available_cash
    try:
        slots = self.db.get_capital_slots()
        slot_available_cash = sum(float(slot.get("available_cash") or 0.0) for slot in slots) or available_cash
    except Exception:
        slot_available_cash = available_cash
    plan = build_execution_sizing_plan(
        signal=normalized,
        total_equity=total_equity,
        available_cash=available_cash,
        slot_available_cash=slot_available_cash,
        quant_status=quant_status,
        policy=policy,
    )
    strategy_profile = dict(strategy_profile)
    strategy_profile["execution_sizing_plan"] = plan
    normalized["strategy_profile"] = strategy_profile
    normalized["position_size_pct"] = float(plan["effective_position_pct"])
    if plan.get("skip_reason"):
        normalized["action"] = "HOLD"
        normalized["position_size_pct"] = 0.0
        normalized["decision_type"] = "execution_sizing_blocked"
        normalized["reasoning"] = f"{normalized.get('reasoning') or ''} 执行仓位阻断：{plan['skip_reason']}。".strip()
    return normalized
```

Call it after `_apply_portfolio_execution_guard()` and before transaction-cost handling.

- [ ] Run targeted tests.

Run: `python -m pytest tests\test_execution_sizing.py tests\test_portfolio_execution_guard.py tests\test_stock_execution_feedback.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_sim/signal_center_service.py tests/test_execution_sizing.py
git commit -m "Attach execution sizing plans to signals"
```

### Task 5: PortfolioService Uses Final Budget

**Files:**
- Modify: `app/quant_sim/portfolio_service.py`
- Modify: `tests/test_quant_sim_auto_execution.py`
- Modify: `tests/test_execution_sizing.py`

- [ ] Add failing test proving final budget controls quantity.

```python
from pathlib import Path

from app.quant_sim.candidate_pool_service import CandidatePoolService
from app.quant_sim.db import QuantSimDB
from app.quant_sim.portfolio_service import PortfolioService


def test_auto_execute_uses_execution_sizing_final_budget(tmp_path: Path):
    db_path = tmp_path / "quant.db"
    db = QuantSimDB(db_path)
    db.reset_runtime_state(initial_cash=400000)
    CandidatePoolService(db_file=db_path).add_manual_candidate("000001", "平安银行", "manual", latest_price=10.0)
    signal_id = db.add_signal(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "action": "BUY",
            "confidence": 80,
            "reasoning": "test",
            "position_size_pct": 50,
            "stop_loss_pct": 5,
            "take_profit_pct": 12,
            "decision_type": "dual_track_weighted_buy",
            "strategy_profile": {
                "portfolio_execution_guard": {"status": "downgraded", "buy_tier": "weak_buy"},
                "execution_sizing_plan": {"final_budget": 12000.0, "effective_position_pct": 3.0, "buy_tier": "weak_buy"},
            },
            "status": "pending",
        }
    )

    service = PortfolioService(db_file=db_path)
    executed = service.auto_execute_signal(db.get_signal(signal_id), executed_at="2026-01-05T10:00:00Z")

    assert executed is True
    trade = db.get_trade_history(limit=1)[0]
    assert trade["quantity"] == 1100
    assert trade["gross_amount"] <= 12000
```

- [ ] Run failing test.

Run: `python -m pytest tests\test_quant_sim_auto_execution.py::test_auto_execute_uses_execution_sizing_final_budget -q`

Expected: FAIL because execution still derives budget from `position_size_pct` or slot math.

- [ ] Update `PortfolioService._estimate_buy_quantity()`.

At the start of `_estimate_buy_quantity()`, read the plan:

```python
strategy_profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
execution_plan = strategy_profile.get("execution_sizing_plan") if isinstance(strategy_profile.get("execution_sizing_plan"), dict) else {}
final_budget = float(execution_plan.get("final_budget") or 0.0)
if final_budget > 0:
    if settle_slots:
        self.db.settle_capital_slots()
    slots = self.db.get_capital_slots()
    slot_available_cash = sum(float(slot.get("available_cash") or 0) for slot in slots) or float(summary["available_cash"] or 0)
    buy_budget = min(final_budget, float(summary["available_cash"] or 0), slot_available_cash)
    lot_cost_with_fee = price * self.A_SHARE_LOT_SIZE * (1 + commission_rate)
    if buy_budget < lot_cost_with_fee:
        return 0, build_sizing_explainability(
            config=normalize_capital_slot_config(scheduler_config),
            slot_plan=calculate_slot_plan(float(summary["total_equity"] or 0), normalize_capital_slot_config(scheduler_config)),
            sizing={**execution_plan, "slot_units_source": "execution_sizing_plan"},
            available_cash=float(summary["available_cash"] or 0),
            slot_available_cash=slot_available_cash,
            buy_budget=buy_budget,
            quantity=0,
            skip_reason=str(execution_plan.get("skip_reason") or "execution_sizing_budget不足买入一手"),
            target_position_pct=float(execution_plan.get("effective_position_pct") or 0.0),
            target_position_budget=final_budget,
            slot_capacity_capped=slot_available_cash + 1e-6 < final_budget,
        )
    lots = floor(buy_budget / lot_cost_with_fee)
    quantity = int(lots * self.A_SHARE_LOT_SIZE)
    return quantity, build_sizing_explainability(
        config=normalize_capital_slot_config(scheduler_config),
        slot_plan=calculate_slot_plan(float(summary["total_equity"] or 0), normalize_capital_slot_config(scheduler_config)),
        sizing={**execution_plan, "slot_units_source": "execution_sizing_plan"},
        available_cash=float(summary["available_cash"] or 0),
        slot_available_cash=slot_available_cash,
        buy_budget=buy_budget,
        quantity=quantity,
        skip_reason=None,
        target_position_pct=float(execution_plan.get("effective_position_pct") or 0.0),
        target_position_budget=final_budget,
        slot_capacity_capped=slot_available_cash + 1e-6 < final_budget,
    )
```

Keep old path only for signals without `execution_sizing_plan`.

- [ ] Run targeted tests.

Run: `python -m pytest tests\test_quant_sim_auto_execution.py tests\test_quant_sim_capital_slots.py tests\test_execution_sizing.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_sim/portfolio_service.py tests/test_quant_sim_auto_execution.py tests/test_execution_sizing.py
git commit -m "Execute buys from final budget"
```

### Task 5.5: Batch Portfolio Exposure Gate

**Files:**
- Modify: `app/quant_sim/execution_sizing.py`
- Modify: `app/quant_sim/portfolio_service.py`
- Modify: `tests/test_execution_sizing.py`
- Modify: `tests/test_quant_sim_auto_execution.py`

- [ ] Add failing tests for checkpoint/day/trial/weak BUY aggregate caps.

```python
from app.quant_sim.execution_sizing import apply_batch_execution_caps, default_execution_position_cap_policy


def _buy_signal(signal_id: int, tier: str, final_budget: float, risk_pct: float = 0.30, status: str = "trial") -> dict:
    return {
        "id": signal_id,
        "stock_code": f"000{signal_id:03d}",
        "stock_name": f"股票{signal_id}",
        "action": "BUY",
        "confidence": 80 - signal_id,
        "position_size_pct": 3.0,
        "strategy_profile": {
            "portfolio_execution_guard": {
                "buy_tier": tier,
                "buy_strength_score": 0.6 - signal_id * 0.01,
            },
            "execution_sizing_plan": {
                "buy_tier": tier,
                "final_budget": final_budget,
                "risk_budget_pct": risk_pct,
                "effective_position_pct": 3.0,
            },
            "quant_status": status,
        },
    }


def test_batch_caps_skip_trial_buys_after_checkpoint_risk_budget():
    policy = default_execution_position_cap_policy("aggressive")
    signals = [_buy_signal(1, "weak_buy", 12000, 0.30), _buy_signal(2, "weak_buy", 12000, 0.30), _buy_signal(3, "weak_buy", 12000, 0.30)]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=100000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=0,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    allowed = [item for item in result if item["allowed"]]
    skipped = [item for item in result if not item["allowed"]]
    assert len(allowed) == 2
    assert skipped[0]["reason_code"] == "portfolio_trial_risk_budget_exhausted"


def test_batch_caps_skip_when_weak_buy_exposure_already_full():
    policy = default_execution_position_cap_policy("stable")
    signals = [_buy_signal(1, "weak_buy", 8000, 0.20)]

    result = apply_batch_execution_caps(
        signals=signals,
        total_equity=200000,
        existing_trial_market_value=0,
        existing_weak_buy_market_value=200000 * 0.08,
        day_trial_risk_used_pct=0,
        policy=policy,
    )

    assert result[0]["allowed"] is False
    assert result[0]["reason_code"] == "weak_buy_exposure_cap_hit"
```

- [ ] Run failing tests.

Run: `python -m pytest tests\test_execution_sizing.py::test_batch_caps_skip_trial_buys_after_checkpoint_risk_budget tests\test_execution_sizing.py::test_batch_caps_skip_when_weak_buy_exposure_already_full -q`

Expected: FAIL because batch cap helper does not exist.

- [ ] Extend execution cap policy.

In `default_execution_position_cap_policy()`, add:

```python
"checkpoint_trial_risk_budget_pct": 0.80,
"daily_trial_risk_budget_pct": 1.50,
"trial_total_exposure_cap_pct": 20.0,
"weak_buy_total_exposure_cap_pct": 12.0,
```

Use stable values `0.50 / 1.00 / 12.0 / 8.0` and conservative values `0.30 / 0.60 / 8.0 / 5.0`.

- [ ] Implement `apply_batch_execution_caps()`.

```python
BUY_TIER_ORDER = {"strong_buy": 0, "normal_buy": 1, "weak_buy": 2}


def _signal_plan(signal: dict[str, Any]) -> dict[str, Any]:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    plan = profile.get("execution_sizing_plan") if isinstance(profile.get("execution_sizing_plan"), dict) else {}
    return plan


def _signal_quant_status(signal: dict[str, Any]) -> str:
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    return str(profile.get("quant_status") or signal.get("quant_status") or "active").strip().lower()


def _priority(signal: dict[str, Any]) -> tuple[int, float, float, int]:
    plan = _signal_plan(signal)
    tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
    profile = signal.get("strategy_profile") if isinstance(signal.get("strategy_profile"), dict) else {}
    gate = profile.get("portfolio_execution_guard") if isinstance(profile.get("portfolio_execution_guard"), dict) else {}
    strength = _float(gate.get("buy_strength_score"), 0.0)
    confidence = _float(signal.get("confidence"), 0.0)
    signal_id = int(_float(signal.get("id"), 0.0))
    return (BUY_TIER_ORDER.get(tier, 9), -strength, -confidence, signal_id)


def apply_batch_execution_caps(
    *,
    signals: list[dict[str, Any]],
    total_equity: float,
    existing_trial_market_value: float,
    existing_weak_buy_market_value: float,
    day_trial_risk_used_pct: float,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    checkpoint_trial_risk = 0.0
    day_trial_risk = float(day_trial_risk_used_pct or 0.0)
    trial_exposure = float(existing_trial_market_value or 0.0)
    weak_exposure = float(existing_weak_buy_market_value or 0.0)
    trial_exposure_cap = float(total_equity) * float(policy["trial_total_exposure_cap_pct"]) / 100.0
    weak_exposure_cap = float(total_equity) * float(policy["weak_buy_total_exposure_cap_pct"]) / 100.0
    rows: list[dict[str, Any]] = []
    for signal in sorted(signals, key=_priority):
        plan = _signal_plan(signal)
        tier = str(plan.get("buy_tier") or _buy_tier(signal)).strip().lower()
        status = _signal_quant_status(signal)
        final_budget = _float(plan.get("final_budget"), 0.0)
        risk_budget_pct = _float(plan.get("risk_budget_pct"), 0.0)
        reason_code = ""
        if status == "trial":
            if checkpoint_trial_risk + risk_budget_pct > float(policy["checkpoint_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "portfolio_trial_risk_budget_exhausted"
            elif day_trial_risk + risk_budget_pct > float(policy["daily_trial_risk_budget_pct"]) + 1e-9:
                reason_code = "daily_trial_risk_budget_exhausted"
            elif trial_exposure + final_budget > trial_exposure_cap + 1e-9:
                reason_code = "trial_exposure_cap_hit"
        if not reason_code and tier == "weak_buy" and weak_exposure + final_budget > weak_exposure_cap + 1e-9:
            reason_code = "weak_buy_exposure_cap_hit"
        allowed = not reason_code
        if allowed:
            if status == "trial":
                checkpoint_trial_risk += risk_budget_pct
                day_trial_risk += risk_budget_pct
                trial_exposure += final_budget
            if tier == "weak_buy":
                weak_exposure += final_budget
        rows.append({"signal_id": signal.get("id"), "allowed": allowed, "reason_code": reason_code, "signal": signal})
    return rows
```

- [ ] Integrate in `PortfolioService.auto_execute_pending_signals()`.

Before iterating BUY signals, split and cap:

```python
config = self.db.get_scheduler_config()
sells = [signal for signal in ordered if str(signal.get("action") or "").upper() == "SELL"]
buys = [signal for signal in ordered if str(signal.get("action") or "").upper() == "BUY"]
policy = default_execution_position_cap_policy(config.get("strategy_profile_id"))
summary = self.db.get_account_summary()
existing_trial_market_value, existing_weak_buy_market_value = self._current_trial_and_weak_buy_exposure()
day_trial_risk_used_pct = self._day_trial_risk_used_pct(executed_at)
batch_rows = apply_batch_execution_caps(
    signals=buys,
    total_equity=float(summary.get("total_equity") or 0),
    existing_trial_market_value=existing_trial_market_value,
    existing_weak_buy_market_value=existing_weak_buy_market_value,
    day_trial_risk_used_pct=day_trial_risk_used_pct,
    policy=policy,
)
for row in batch_rows:
    if not row["allowed"]:
        self._record_auto_execute_skip(row["signal"], f"自动执行跳过：{row['reason_code']}")
```

Then execute `sells + [row["signal"] for row in batch_rows if row["allowed"]]`.

Add `import json` at the top of `app/quant_sim/portfolio_service.py`, then add helpers:

```python
def _current_trial_and_weak_buy_exposure(self) -> tuple[float, float]:
    positions = self.db.get_positions()
    trial_total = 0.0
    weak_total = 0.0
    for position in positions:
        market_value = float(position.get("market_value") or 0.0)
        state = self.db.get_quant_universe_state(str(position.get("stock_code") or ""))
        if str((state or {}).get("quant_status") or "").lower() == "trial":
            trial_total += market_value
        if self.db.get_stock_execution_feedback_summary(str(position.get("stock_code") or "")).get("last_buy_was_weak"):
            weak_total += market_value
    return trial_total, weak_total


def _day_trial_risk_used_pct(self, executed_at: str | datetime | None) -> float:
    day = executed_at.date().isoformat() if isinstance(executed_at, datetime) else str(executed_at or datetime.now().isoformat())[:10]
    total = 0.0
    for trade in self.db.get_trade_history(limit=1000):
        if str(trade.get("action") or "").upper() != "BUY":
            continue
        if str(trade.get("executed_at") or "")[:10] != day:
            continue
        metadata = trade.get("trade_metadata") if isinstance(trade.get("trade_metadata"), dict) else {}
        if not metadata:
            try:
                metadata = json.loads(str(trade.get("trade_metadata_json") or "{}"))
            except json.JSONDecodeError:
                metadata = {}
        plan = metadata.get("execution_sizing_plan") if isinstance(metadata.get("execution_sizing_plan"), dict) else {}
        total += float(plan.get("risk_budget_pct") or 0.0)
    return total
```

- [ ] Add auto execution integration test.

In `tests/test_quant_sim_auto_execution.py`, create three pending trial weak BUY signals on a 100k account and assert one is skipped with `portfolio_trial_risk_budget_exhausted`.

- [ ] Run tests.

Run: `python -m pytest tests\test_execution_sizing.py tests\test_quant_sim_auto_execution.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add app/quant_sim/execution_sizing.py app/quant_sim/portfolio_service.py tests/test_execution_sizing.py tests/test_quant_sim_auto_execution.py
git commit -m "Apply batch execution exposure caps"
```

### Task 6: API Payload And Signal Detail UI

**Files:**
- Modify: `app/gateway/signals.py` or current signal detail gateway file located by `rg "signal-detail|SignalDetail"`
- Modify: `ui/src/features/quant/signal-detail-page.tsx`
- Modify: `ui/src/tests/signal-detail-page.test.tsx`
- Modify: `ui/src/locales/zh-CN.json`
- Modify: `ui/src/locales/en-US.json`

- [ ] Locate current gateway and UI render path.

Run:

```powershell
rg -n "signal-detail|SignalDetail|execution_sizing_plan|portfolio_execution_guard" app ui/src -S
```

Expected: paths include `ui/src/features/quant/signal-detail-page.tsx` and the backend signal detail route.

- [ ] Add failing UI test for kernel and execution sizing display.

In `ui/src/tests/signal-detail-page.test.tsx`, add payload fields to the mock signal:

```ts
strategy_profile: {
  kernel_positioning: {
    quality_position_pct: 28.26,
    rule_hit: "resonance_standard",
    signal_quality_score: 0.38,
    quality_penalties: ["rsi_hot", "weak_ma20_slope"],
  },
  execution_sizing_plan: {
    buy_tier: "weak_buy",
    kernel_quality_position_pct: 28.26,
    buy_tier_cap_pct: 5,
    lifecycle_cap_pct: 3,
    risk_budget_pct: 0.3,
    expected_stop_loss_pct: 5,
    effective_position_pct: 3,
    final_budget: 12000,
    cap_reasons: ["trial_weak_buy_cap", "buy_tier_cap"],
  },
}
```

Add assertions:

```ts
expect(await screen.findByText("Kernel 建议仓位")).toBeInTheDocument();
expect(screen.getByText("28.26%")).toBeInTheDocument();
expect(screen.getByText("最终执行仓位")).toBeInTheDocument();
expect(screen.getByText("3.00%")).toBeInTheDocument();
expect(screen.getByText("12,000.00")).toBeInTheDocument();
```

- [ ] Run failing UI test.

Run: `cd ui; npm test -- signal-detail-page.test.tsx --runInBand`

Expected: FAIL because the fields are not rendered.

- [ ] Ensure backend returns nested strategy profile fields.

In the signal detail gateway, preserve:

```python
strategy_profile["kernel_positioning"]
strategy_profile["execution_sizing_plan"]
strategy_profile["explainability"]["resonance"]
```

Do not flatten or drop these fields.

- [ ] Render sizing fields in `SignalDetailPage`.

Add a compact section near the decision/execution block:

```tsx
const kernelPositioning = detail.signal?.strategy_profile?.kernel_positioning ?? detail.signal?.strategy_profile?.explainability?.resonance;
const executionSizingPlan = detail.signal?.strategy_profile?.execution_sizing_plan;
```

Render labels:

```tsx
<Metric label={t("Kernel 建议仓位")} value={formatPercent(kernelPositioning?.quality_position_pct)} />
<Metric label={t("最终执行仓位")} value={formatPercent(executionSizingPlan?.effective_position_pct)} />
<Metric label={t("最终预算")} value={formatCurrency(executionSizingPlan?.final_budget)} />
<Metric label={t("风险预算")} value={formatPercent(executionSizingPlan?.risk_budget_pct)} />
```

- [ ] Add i18n keys.

In both locale files add:

```json
"Kernel 建议仓位": "Kernel 建议仓位",
"最终执行仓位": "最终执行仓位",
"最终预算": "最终预算",
"风险预算": "风险预算"
```

For English:

```json
"Kernel 建议仓位": "Kernel suggested position",
"最终执行仓位": "Final execution position",
"最终预算": "Final budget",
"风险预算": "Risk budget"
```

- [ ] Run UI tests/build.

Run: `cd ui; npm test -- signal-detail-page.test.tsx --runInBand`

Expected: PASS.

- [ ] Commit.

```powershell
git add app ui/src
git commit -m "Show kernel and execution sizing in signal detail"
```

### Task 7: Replay And Drill Data Contract Verification

**Files:**
- Create: `tests/test_sizing_payload_contract.py`

- [ ] Create a focused contract test for persisted signal payloads.

```python
from pathlib import Path

from app.quant_sim.db import QuantSimDB


def _signal_payload() -> dict:
    return {
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
    db = QuantSimDB(tmp_path / "replay.db")
    run_id = db.create_sim_run(
        {
            "run_type": "historical_replay",
            "status": "running",
            "strategy_profile_id": "aggressive",
            "initial_cash": 400000,
            "started_at": "2026-01-01T00:00:00Z",
        }
    )
    signal_id = db.add_sim_run_signal(run_id, _signal_payload())

    signal = db.get_sim_run_signal(run_id, signal_id)
    profile = signal["strategy_profile"]

    assert profile["kernel_positioning"]["rule_hit"] == "resonance_standard"
    assert profile["execution_sizing_plan"]["buy_tier"] == "weak_buy"
    assert profile["execution_sizing_plan"]["final_budget"] == 12000.0
```

- [ ] Run tests.

Run: `python -m pytest tests\test_sizing_payload_contract.py tests\test_execution_sizing.py -q`

Expected: PASS.

- [ ] Commit.

```powershell
git add tests/test_sizing_payload_contract.py tests/test_execution_sizing.py
git commit -m "Verify sizing payloads in replay and drill"
```

### Task 8: End-To-End Regression Runs

**Files:**
- No code files expected.
- Output: save summary notes in `docs/superpowers/reports/2026-05-10-kernel-sizing-regression.md`

- [ ] Run backend targeted suite.

Run:

```powershell
python -m pytest tests\test_kernel_resonance_quality.py tests\test_execution_sizing.py tests\test_portfolio_execution_guard.py tests\test_quant_sim_auto_execution.py tests\test_quant_sim_capital_slots.py tests\test_live_quant_drill_service.py tests\test_quant_replay_engine.py -q
```

Expected: PASS.

- [ ] Run full backend suite.

Run: `python -m pytest`

Expected: PASS.

- [ ] Run frontend test/build used by repo.

Run:

```powershell
cd ui
npm test -- signal-detail-page.test.tsx --runInBand
npm run build
```

Expected: PASS.

- [ ] Re-run latest live quant drill scenario.

Use the existing local API or service command that created the previous `live_quant_drill` run. Parameters:

```text
run_type = live_quant_drill
strategy_profile = aggressive
initial_cash = 400000
market = CN
timeframe = 30m
start = 2026-01-01 09:30
end = current date 15:00
seed_current_quant_universe = true
historical_candidate_events = true
auto_entry = true
auto_exit = true
execute_trades = true
liquidate_at_end = true
```

Capture:

```text
final_equity
total_return_pct
max_drawdown_pct
trade_count
buy_count
sell_count
realized_pnl
unrealized_pnl
weak_buy_count
weak_buy_avg_gross_amount
trial_weak_buy_avg_gross_amount
trial/cooling/retired transition counts
```

- [ ] Re-run matching historical replay scenario.

Use the same strategy profile, stock universe, starting capital, timeframe, and date range. Capture the same metrics.

- [ ] Write regression report.

Create `docs/superpowers/reports/2026-05-10-kernel-sizing-regression.md`:

```markdown
# Kernel Sizing Regression

## Inputs

- Strategy:
- Starting cash:
- Date range:
- Stock universe:

## Live Quant Drill

| Metric | Before | After |
|---|---:|---:|
| final_equity |  |  |
| total_return_pct |  |  |
| max_drawdown_pct |  |  |
| realized_pnl |  |  |
| weak_buy_avg_gross_amount |  |  |
| trial_weak_buy_avg_gross_amount |  |  |

## Historical Replay

| Metric | Before | After |
|---|---:|---:|
| final_equity |  |  |
| total_return_pct |  |  |
| max_drawdown_pct |  |  |
| realized_pnl |  |  |
| weak_buy_avg_gross_amount |  |  |

## Acceptance

- weak_buy average amount reduced:
- 400k trial weak buy target 12k-20k:
- resonance_standard no fixed 50%:
- signal detail explains kernel and execution sizing:
```

- [ ] Commit report.

```powershell
git add docs/superpowers/reports/2026-05-10-kernel-sizing-regression.md
git commit -m "Record kernel sizing regression results"
```

---

## Self-Review

- Spec section 6.2 quality weights: Task 1 and Task 2.
- Spec section 6.3 resonance min/max and full max downgrade: Task 1 and Task 2.
- Spec section 7.1 final budget chain: Task 3, Task 4, Task 5.
- Spec section 7.5 checkpoint/day/trial/weak aggregate exposure caps: Task 5.5.
- Spec section 7.6 account equity tier boundaries: Task 3 tests exact `<100000`, `100000`, `300000`, `800000`.
- Spec section 10 UI requirements: Task 6.
- Spec section 12 replay/drill acceptance: Task 7 and Task 8.

No migration task is included because the project is not yet live and the spec requires direct replacement of old config semantics.
