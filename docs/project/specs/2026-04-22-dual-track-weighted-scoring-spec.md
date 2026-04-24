# Dual-Track Weighted Scoring Refactor Spec (Implementation-Ready)

Status: ready-for-implementation after this revision  
Version: `v2.3`  
Date: `2026-04-22`

## 1. Objective
Refactor quant decision scoring to support:
- 12 technical dimensions with configurable weights
- configurable context-dimension weights
- configurable dual-track fusion weights and mode
- deterministic hybrid precedence
- sell-precedence safety gate
- divergence-penalized fusion confidence
- strategy-configurable dynamic thresholds
- strict backward compatibility in default mode
- schema-versioned explainability payload
- deterministic regression verification with golden fixtures

## 2. Current Baseline (As-Is)
- Final action is rule-engine driven in `DualTrackResolver`.
- Technical dimensions are limited and hardcoded.
- Context overlay may mutate context score after core scoring.
- UI explainability currently reconstructs part of semantics from display rows.

Referenced modules:
- `app/quant_kernel/runtime.py`
- `app/quant_kernel/decision_engine.py`
- `app/quant_kernel/config.py`
- `app/quant_sim/signal_center_service.py`
- `app/gateway_api.py`
- `ui/src/features/quant/signal-detail-page.tsx`

## 3. Mathematical Model (Exact and Deterministic)

### 3.1 Notation
- `i`: dimension index
- `g`: group index
- `t`: track index (`technical`, `context`)
- `x_i`: raw feature value
- `s_i`: dimension score in `[-1, 1]`
- `a_i`: availability flag (`1` available, `0` unavailable)
- `w_i`: configured dimension weight (`>= 0`)
- `W_g`: configured group weight (`>= 0`)
- `clamp(z) = min(1, max(-1, z))`
- `clamp01(z) = min(1, max(0, z))`

### 3.2 Dimension scoring
- `s_i = f_i(x_i)` where `f_i` is deterministic and bounded to `[-1, 1]`.
- Missing/invalid input: `a_i = 0`, `s_i = 0`.

### 3.3 Group scoring (dimension normalization scope is group-local)
For each group `g` with dimensions `D_g`:
- `w_i_eff = w_i * a_i`
- `w_i_norm_g = w_i_eff / sum_{j in D_g}(w_j_eff)` if denominator `> 0`, else `0`
- `c_i_group = w_i_norm_g * s_i`
- `S_g_raw = sum_{i in D_g}(c_i_group)`
- `S_g = clamp(S_g_raw)`

This is mandatory: dimension weights are normalized **within each group**, never across the full track.

### 3.4 Group coverage and track confidence
Group coverage:
- `GroupCoverage_g = sum_{i in D_g}(w_i * a_i) / sum_{i in D_g}(w_i)` when denominator `> 0`, else `0`

Group availability:
- `A_g = 1` if `GroupCoverage_g > 0`, else `0`

Group weight for score aggregation:
- `W_g_eff = W_g * A_g`
- `W_g_norm = W_g_eff / sum_k(W_k_eff)` if denominator `> 0`, else `0`
- `C_g_track = W_g_norm * S_g`

Track score:
- `TrackScore_t_raw = sum_g(C_g_track)`
- `TrackScore_t = clamp(TrackScore_t_raw)`

Track confidence:
- `TrackConfidence_t = sum_g(W_g * GroupCoverage_g) / sum_g(W_g)` when denominator `> 0`, else `0`

### 3.5 Fusion scoring and confidence
Track fusion weights:
- `alpha_tech >= 0`, `alpha_ctx >= 0`
- `alpha_tech_norm = alpha_tech / (alpha_tech + alpha_ctx)`
- `alpha_ctx_norm = alpha_ctx / (alpha_tech + alpha_ctx)`

Fusion score:
- `FusionScore_raw = alpha_tech_norm * TrackScore_tech + alpha_ctx_norm * TrackScore_ctx`
- `FusionScore = clamp(FusionScore_raw)`

Fusion confidence:
- `FusionConfidence_base = alpha_tech_norm * TrackConfidence_tech + alpha_ctx_norm * TrackConfidence_ctx`
- `SignConflict = 1` iff:
  - `TrackScore_tech * TrackScore_ctx < 0`
  - and `abs(TrackScore_tech) >= sign_conflict_min_abs_score`
  - and `abs(TrackScore_ctx) >= sign_conflict_min_abs_score`
  - else `0`
- `Divergence = abs(TrackScore_tech - TrackScore_ctx) / 2`
- `DivergencePenalty = clamp01(lambda_divergence * Divergence + lambda_sign_conflict * SignConflict)`
- `FusionConfidence = clamp01(FusionConfidence_base * (1 - DivergencePenalty))`

Unavailable track handling policy:
- Track unavailability does **not** renormalize fusion track weights.
- Unavailable track contributes score `0` and confidence `0`.
- This intentionally reduces conviction.

Dynamic threshold policy:
- `threshold_mode = static | volatility_adjusted`
- `VolatilityRegimeScore` source definition:
  - computed by `volatility_regime_score` feature provider
  - normalized to `[-1, 1]`
  - explainability field required: `volatility_regime_score`
  - missing policy:
    - `threshold_volatility_missing_policy = fail_fast | neutral_zero`
    - if `fail_fast`: weighted/hybrid scoring request fails
    - if `neutral_zero`: `v = 0` and reason `threshold_volatility_missing_neutral`
- when `static`:
  - `buy_threshold_eff = fusion_buy_threshold`
  - `sell_threshold_eff = fusion_sell_threshold`
- when `volatility_adjusted`:
  - `v = VolatilityRegimeScore` (normalized to `[-1, 1]`, higher means more volatile)
  - `buy_threshold_eff = fusion_buy_threshold + buy_vol_k * max(v, 0)`
  - `sell_threshold_eff = fusion_sell_threshold - sell_vol_k * max(v, 0)`
- threshold effective values must satisfy `buy_threshold_eff > sell_threshold_eff`

Weighted action gate:
- Define track enable flags:
  - `TechEnabled = (alpha_tech > 0)`
  - `CtxEnabled = (alpha_ctx > 0)`
- Per-track BUY gates (enabled tracks only):
  - if `TechEnabled`, require `TrackScore_tech >= min_tech_score_for_buy` and `TrackConfidence_tech >= min_tech_confidence_for_buy`
  - if `CtxEnabled`, require `TrackScore_ctx >= min_context_score_for_buy` and `TrackConfidence_ctx >= min_context_confidence_for_buy`
- Stage A (`weighted_threshold_action`):
  - `BUY` if `FusionScore >= buy_threshold_eff`
  - `SELL` if `FusionScore <= sell_threshold_eff`
  - else `HOLD`
- Stage B (`weighted_action_raw`):
  - if `FusionConfidence < min_fusion_confidence` => `HOLD`
  - else if `weighted_threshold_action == BUY` and enabled-track BUY gates fail => `HOLD`
  - else => `weighted_threshold_action`

## 4. Missing-Field Handling Rules

### 4.1 Dimension-level
Missing/invalid/unreliable value => `a_i=0`, `s_i=0`, reason code required:
- `missing_field`
- `missing_series`
- `invalid_value`
- `provider_timeout`

### 4.2 Group-level
All dimensions missing in group:
- `S_g=0`
- `A_g=0`
- `GroupCoverage_g=0`
- group excluded from track score renormalization

### 4.3 Track-level
All groups unavailable:
- `TrackScore_t=0`
- `TrackConfidence_t=0`
- `track_unavailable=true`

### 4.4 Full unavailability and mode interaction
- If both tracks unavailable:
  - weighted/hybrid weighted leg uses `HOLD` with reason `insufficient_data`
- In `rule_only`:
  - legacy resolver remains authoritative
  - compatibility test requires legacy parity

## 5. Candidate vs Position Profile Design

### 5.1 Profile namespace
Config hierarchy:
- `scoring.base`
- `scoring.profiles.candidate`
- `scoring.profiles.position`

Merge order:
- `base` then profile override (`candidate` or `position`)

### 5.2 Shared technical schema (12 dimensions)
Groups:
- `trend`: `trend_direction`, `ma_alignment`, `ma_slope`, `price_vs_ma20`
- `momentum`: `macd_level`, `macd_hist_slope`, `rsi_zone`, `kdj_cross`
- `volume_confirmation`: `volume_ratio`, `obv_trend`
- `volatility_risk`: `atr_risk`, `boll_position`

### 5.3 Profile behavior
- Candidate: entry-oriented scoring parameters.
- Position: hold/exit-oriented scoring parameters.

## 6. Action Vocabulary and Interpretation

Engine internal raw actions:
- `BUY`, `HOLD`, `SELL`

Interpretation:
- Candidate signal:
  - `BUY` => `candidate_buy`
  - `HOLD` => `watch`
  - `SELL` => `reject` (not short-sell)
- Position signal:
  - `BUY` => `add_or_hold_strong` (mapped to existing system enum)
  - `HOLD` => `hold`
  - `SELL` => `reduce_or_exit` (mapped to existing system enum)

Gateway/UI rule for candidate reject:
- Candidate `reject` must not be exposed as tradable `SELL` signal in workbench/live/replay signal lists.
- `gateway_api.py` must map candidate raw `SELL` to non-tradable status (`candidate_reject`) and filter it from execution queues.
- UI displays candidate reject as screening outcome only, never as short/exit instruction.

## 7. Hybrid Mode Precedence (Deterministic)

Modes:
- `rule_only`
- `weighted_only`
- `hybrid`

Mode interaction baseline:
- `veto_action` is resolved first for all modes.
- `core_rule_action` is computed by rule engine without applying hard veto.
- `weighted_threshold_action` and `weighted_action_raw` are computed by weighted scorer without applying hard veto.
- Final action by mode:
  - `rule_only`:
    - final action must come from legacy resolver path (including legacy veto semantics)
    - `veto_action/core_rule_action/weighted_*` can be computed for explanation only
    - replacing legacy rule-only path is allowed only after golden parity is proven 100%
  - `weighted_only`: if veto exists => `veto_action`, else `weighted_action_raw`
  - `hybrid`: follow section 7.3 precedence using `core_rule_action` + `weighted_action_raw`

### 7.1 Veto model and priority
Veto priority (highest first):
1. `risk_stop`
2. `hard_constraint`
3. `context_veto`

Veto raw action by profile:
- `risk_stop` => candidate:`SELL`, position:`SELL`
- `hard_constraint` => candidate:`SELL`, position:`HOLD`
- `context_veto` => candidate:`HOLD`, position:`HOLD`

If multiple vetoes present, highest priority wins.

### 7.2 Confirmation definition
`confirmation_satisfied = true` iff all conditions hold:
1. no veto is active
2. `FusionScore >= buy_threshold_eff`
3. if `TechEnabled`, `TrackScore_tech >= min_tech_score_for_buy`
4. if `CtxEnabled`, `TrackScore_ctx >= min_context_score_for_buy`
5. if `TechEnabled`, `TrackConfidence_tech >= min_tech_confidence_for_buy`
6. if `CtxEnabled`, `TrackConfidence_ctx >= min_context_confidence_for_buy`
7. `FusionConfidence >= min_fusion_confidence`

Definition tie:
- `confirmation_satisfied` must be equivalent to the condition for `weighted_threshold_action=BUY` to survive into `weighted_action_raw=BUY`.

Sell precedence gate:
- `sell_precedence_gate <= sell_threshold_eff`
- Weighted `SELL` can override a conflicting `HOLD/BUY` only when `FusionScore <= sell_precedence_gate`.

### 7.3 Hybrid precedence matrix
1. Compute `veto_action`, `core_rule_action`, `weighted_action_raw`.
2. Apply:
   - if veto exists => `veto_action`
   - else if `core_rule_action == weighted_action_raw` => that action
   - else if `core_rule_action == SELL` => `SELL`
   - else if `weighted_action_raw == SELL` and `FusionScore <= sell_precedence_gate` => `SELL`
   - else if `weighted_action_raw == SELL` => `HOLD`
   - else if `core_rule_action == BUY` and `weighted_action_raw == HOLD` => `HOLD`
   - else if `core_rule_action == HOLD` and `weighted_action_raw == BUY` => `BUY`
   - else => `HOLD`

`context_veto` cannot be overridden by weighted fusion.

## 8. Context Track Structure and Overlay Ownership

### 8.1 Context structure in v2.3 (grouped, production default)
Context uses grouped scoring with four groups:
- `market_structure`
- `risk_account`
- `tradability_timing`
- `source_execution`

Context dimension groups:
- `market_structure`: `trend_regime`, `price_structure`, `momentum`
- `risk_account`: `risk_balance`, `account_posture`
- `tradability_timing`: `liquidity`, `session`
- `source_execution`: `source_prior`, `execution_feedback`

Important semantic rule:
- context `momentum` is market/sector/regime momentum, not symbol-level technical momentum.

Compatibility note:
- legacy flat-context payload/config can be adapted via compatibility mode, but grouped context is the production default for weighted/hybrid.

### 8.2 Overlay ownership
- `execution_feedback` and `account_posture` are formal context dimensions.
- Post-decision `_apply_ai_overlay` is not part of the production chain. Feature extraction must happen before track scoring, via market/context payload fields such as `execution_feedback_score`, `feedback_sample_count`, and `cash_ratio`.
- No post-fusion or post-track score mutation is allowed.
- `execution_feedback` must use long-decay smoothing and sparse-activation guard:
  - decay policy: exponential decay by `feedback_decay_half_life`
  - sparse guard: if `feedback_sample_count < min_feedback_samples`, set score to neutral `0`
  - score cap is applied at dimension-score stage:
    - `s_execution_feedback = clamp(raw_execution_feedback_score, -execution_feedback_score_cap, +execution_feedback_score_cap)`
    - cap is applied before group/track weighting, not at contribution aggregation stage

## 9. Config Schema and Validation

This YAML is an **abbreviated example** showing canonical structure and representative scorer entries.
Production configs must provide complete scorer definitions for all 21 dimensions via base + profile override resolution.

```yaml
scoring:
  base:
    technical:
      group_weights: {trend: 1.0, momentum: 1.0, volume_confirmation: 1.0, volatility_risk: 1.0}
      dimension_weights:
        trend_direction: 1.0
        ma_alignment: 1.0
        ma_slope: 1.0
        price_vs_ma20: 1.0
        macd_level: 1.0
        macd_hist_slope: 1.0
        rsi_zone: 1.0
        kdj_cross: 1.0
        volume_ratio: 1.0
        obv_trend: 1.0
        atr_risk: 1.0
        boll_position: 1.0
      scorers:
        trend_direction:
          algorithm: condition_map
          params:
            bull_score: 1.0
            mild_bull_score: 0.3
            mild_bear_score: -0.4
            bear_score: -1.0
          reason_template: "close/ma20/ma60={close}/{ma20}/{ma60}"
        ma_slope:
          algorithm: linear
          params:
            slope_scale: 6.0
            intercept: 0.0
            min_clip: -1.0
            max_clip: 1.0
          reason_template: "ma20_slope={ma20_slope}"
    context:
      group_weights:
        market_structure: 1.0
        risk_account: 1.0
        tradability_timing: 1.0
        source_execution: 1.0
      dimension_groups:
        market_structure: [trend_regime, price_structure, momentum]
        risk_account: [risk_balance, account_posture]
        tradability_timing: [liquidity, session]
        source_execution: [source_prior, execution_feedback]
      dimension_weights:
        source_prior: 1.0
        trend_regime: 1.0
        price_structure: 1.0
        momentum: 1.0
        risk_balance: 1.0
        liquidity: 1.0
        session: 1.0
        execution_feedback: 1.0
        account_posture: 1.0
      scorers:
        source_prior:
          algorithm: lookup_map
          params:
            source_score_map:
              high_quality: 0.8
              normal: 0.0
              low_quality: -0.5
          reason_template: "source={source}, score={score}"
        execution_feedback:
          algorithm: composite_rule
          params:
            feedback_decay_half_life: 20
            min_feedback_samples: 5
            success_weight: 0.15
            failure_weight: -0.20
            execution_feedback_score_cap: 0.25
          reason_template: "feedback samples={feedback_sample_count}, score={score}"
      execution_feedback_policy:
        feedback_decay_half_life: 20
        min_feedback_samples: 5
        execution_feedback_score_cap: 0.25
    dual_track:
      mode: rule_only
      track_weights: {tech: 1.0, context: 1.0}
      fusion_buy_threshold: 0.76
      fusion_sell_threshold: -0.17
      sell_precedence_gate: -0.50
      min_fusion_confidence: 0.50
      min_tech_score_for_buy: 0.00
      min_context_score_for_buy: 0.00
      min_tech_confidence_for_buy: 0.50
      min_context_confidence_for_buy: 0.50
      lambda_divergence: 0.60
      lambda_sign_conflict: 0.40
      sign_conflict_min_abs_score: 0.10
      threshold_mode: static
      buy_vol_k: 0.20
      sell_vol_k: 0.20
      threshold_volatility_missing_policy: neutral_zero
    veto:
      source_mode: legacy
      thresholds:
        risk_stop:
          enabled: true
          stop_loss_pct: 0.08
          max_atr_pct: 0.12
        hard_constraint:
          enabled: true
          min_liquidity_score: -0.6
        context_veto:
          enabled: true
          min_context_score: -0.7
  profiles:
    candidate:
      technical:
        group_weights:
          trend: 1.3
          momentum: 1.2
          volume_confirmation: 0.9
          volatility_risk: 0.8
        dimension_weights:
          trend_direction: 1.2
          ma_alignment: 0.8
          ma_slope: 1.0
          price_vs_ma20: 0.8
          macd_hist_slope: 1.2
          kdj_cross: 0.6
      context:
        group_weights:
          market_structure: 1.4
          risk_account: 1.1
          tradability_timing: 0.7
          source_execution: 0.7
        dimension_weights:
          trend_regime: 1.2
          price_structure: 1.1
          momentum: 0.8
          risk_balance: 1.2
          account_posture: 1.0
          liquidity: 1.0
          session: 0.5
          source_prior: 1.0
          execution_feedback: 0.8
      dual_track:
        # optional per-profile override (candidate-specific)
        fusion_buy_threshold: 0.78
        sell_precedence_gate: -0.52
    position:
      technical:
        group_weights:
          trend: 1.1
          momentum: 0.8
          volume_confirmation: 0.9
          volatility_risk: 1.5
        dimension_weights:
          trend_direction: 1.1
          ma_alignment: 0.8
          ma_slope: 1.2
          price_vs_ma20: 0.8
          atr_risk: 1.5
          boll_position: 1.2
          kdj_cross: 0.5
      context:
        group_weights:
          market_structure: 1.0
          risk_account: 1.5
          tradability_timing: 0.6
          source_execution: 0.7
        dimension_weights:
          trend_regime: 1.0
          price_structure: 1.0
          momentum: 0.7
          risk_balance: 1.4
          account_posture: 1.3
          liquidity: 0.9
          session: 0.4
          source_prior: 0.7
          execution_feedback: 1.1
      dual_track:
        # optional per-profile override (position-specific)
        fusion_buy_threshold: 0.72
        sell_precedence_gate: -0.48
```

Scorer validation model (normative):
- schema key is `(dimension_id, algorithm)`
- algorithm-level schema (section 12.3) validates generic fields
- dimension-level schema validates required param keys and value ranges
- effective scorer config is resolved from `base.scorers` + `profile.scorers` overrides

Validation rules:
1. All weights must be finite numbers `>= 0`.
2. At least one technical dimension weight per group must be `> 0`.
3. At least one technical group weight must be `> 0`.
4. At least one context dimension weight must be `> 0`.
5. `alpha_tech + alpha_ctx > 0`.
6. `fusion_buy_threshold > fusion_sell_threshold`.
7. `mode in {rule_only, weighted_only, hybrid}`.
8. Unknown dimension ids in overrides are rejected.
9. Missing override fields inherit from `scoring.base`.
10. Every enabled dimension must include complete `algorithm + params` definition.
11. All algorithm numeric params must be finite and inside declared min/max bounds.
12. Percentage/ratio params must declare unit type (`percent` or `ratio`) and pass unit-aware validation.
13. Any config that requires implicit runtime hardcoded fallback is invalid and must be rejected.
14. For production defaults used by `weighted_only` or `hybrid`, all technical/context group weights cannot be uniformly equal across all groups.
15. Sell precedence validation:
   - static mode: `sell_precedence_gate <= fusion_sell_threshold`
   - volatility-adjusted mode: `sell_precedence_gate <= fusion_sell_threshold - sell_vol_k`
16. `lambda_divergence` and `lambda_sign_conflict` must be in `[0, 1]`.
17. If `threshold_mode = volatility_adjusted`, both `buy_vol_k` and `sell_vol_k` must be finite and `>= 0`.
18. `feedback_decay_half_life > 0`, `min_feedback_samples >= 1`, and `max_execution_feedback_contribution in [0, 1]`.
19. Context `dimension_groups` must be total and disjoint across all 9 context dimensions (each dimension appears exactly once).
20. All declared context groups must be non-empty and have declared group weights.
21. Unknown context group ids in overrides are rejected.
22. In weighted/hybrid production defaults, `source_execution` group weight must not exceed `risk_account` group weight.
23. `context.dimension_weights` must provide weights for every dimension referenced by `context.dimension_groups`.
24. For each enabled context group, if `group_weight > 0`, at least one dimension in that group must have weight `> 0`.
25. Supported scorer algorithms are only: `piecewise`, `linear`, `sigmoid`, `lookup_map`, `condition_map`, `composite_rule`.
26. Every scorer config must include `algorithm`, `params`, and `reason_template`.
27. `reason_template` placeholders must reference declared inputs/computed fields; unknown placeholders reject config.
28. `veto.source_mode` must be one of `legacy`, `profile`, `hybrid_merge`.
29. if `veto.source_mode = profile`, all enabled veto types must provide required threshold params.

## 10. Schema Versioning and Backward Compatibility

Payload version:
- `explain_schema_version: "quant_explain/v2.3"`

Versioning rules:
- Missing version => treat as `v1` via adapter.
- `v1` adapter outputs normalized read-model with `derived=true`.
- UI consumes read-model only.

Backward compatibility acceptance:
1. API shape compatibility for legacy consumers.
2. `rule_only` behavior parity on baseline fixtures must be `100%`.
3. Historical records without `quant_explain/v2.3` fields must render safely via adapter.

## 11. Explainability Contract (Canonical)

### 11.1 technical_breakdown
- `dimensions[]`:
  - `id`, `group`, `score`, `available`, `reason`
  - `weight_raw`
  - `weight_norm_in_group`
  - `group_contribution` (contribution to group score)
  - `track_contribution` (contribution to track score through group weight)
- `groups[]`:
  - `id`, `score`, `available`, `coverage`
  - `weight_raw`, `weight_norm_in_track`
  - `track_contribution`
- `track`:
  - `score`, `confidence`, `available`

### 11.2 context_breakdown
Same structure as technical breakdown, using explicit context groups:
- `market_structure`
- `risk_account`
- `tradability_timing`
- `source_execution`

### 11.3 fusion_breakdown
- `mode`
- `tech_weight_raw`, `context_weight_raw`
- `tech_weight_norm`, `context_weight_norm`
- `tech_score`, `context_score`, `fusion_score`
- `tech_confidence`, `context_confidence`, `fusion_confidence_base`, `fusion_confidence`
- `sign_conflict`, `divergence`, `divergence_penalty`
- `threshold_mode`, `volatility_regime_score`, `buy_threshold_base`, `sell_threshold_base`, `buy_threshold_eff`, `sell_threshold_eff`
- `sell_precedence_gate`
- `weighted_threshold_action`, `weighted_action_raw`, `weighted_gate_fail_reasons[]`
- `core_rule_action`, `final_action`
- `veto_source_mode`

### 11.4 veto and decision path
- `vetoes[]`: `{id, priority, action, reason}`
- `veto_action`
- `decision_path[]`: ordered precedence steps and matched branch

## 12. Scoring Function Definitions (Implementation Appendix)

All dimension scorers must define:
- required inputs
- fallback inputs
- invalid-value handling
- piecewise scoring mapping
- reason template

### 12.1 Technical dimensions (12)
1. `trend_direction`
- inputs: `close`, `ma20`, `ma60`
- candidate: `+1` if `close>ma20>ma60`; `+0.3` if `close>ma20`; `-0.4` if `close<ma20`; `-1` if `close<ma60<ma20`
- position: same signs but weaker penalties for mild pullback
- reason: `close/ma20/ma60={c}/{m20}/{m60}`

2. `ma_alignment`
- inputs: `ma5`, `ma10`, `ma20`, `ma60`
- score by bullish order count (`ma5>ma10>ma20>ma60`) mapped to `[-1,1]`

3. `ma_slope`
- inputs: `ma20_t`, `ma20_t-1`
- slope ratio `r=(ma20_t-ma20_t-1)/max(abs(ma20_t-1),eps)` then clamp to `[-1,1]` with profile scale

4. `price_vs_ma20`
- inputs: `close`, `ma20`
- `z=(close-ma20)/max(abs(ma20),eps)` with piecewise thresholds to `[-1,1]`

5. `macd_level`
- inputs: `dif`, `dea`
- base on `dif-dea` and sign of `dif`

6. `macd_hist_slope`
- inputs: `hist_t`, `hist_t-1`
- slope to score; rising positive => bullish, falling negative => bearish

7. `rsi_zone`
- input: `rsi14`
- candidate: oversold positive, overbought negative
- position: mild overbought can be neutral/positive unless reversal present

8. `kdj_cross`
- inputs: `k`, `d`, `j`
- golden/dead cross and extreme-zone adjustments

9. `volume_ratio`
- input: `volume_ratio`
- low liquidity penalty, healthy expansion positive, excessive spike capped

10. `obv_trend`
- inputs: `obv_t`, `obv_t-1`, optional short window slope
- positive slope bullish, negative bearish

11. `atr_risk`
- inputs: `atr`, `close`
- `atr_pct=atr/max(close,eps)`; high volatility increases risk penalty (candidate stronger penalty)

12. `boll_position`
- inputs: `close`, `boll_upper`, `boll_lower`
- normalized band position to score with profile-specific interpretation near extremes

Orthogonality guard for trend group:
- `trend_direction` and `ma_alignment` are treated as correlated dimensions.
- Production default profiles must avoid equal-high weighting on both simultaneously.
- Recommended defaults:
  - candidate: `trend_direction=1.2`, `ma_alignment=0.8`
  - position: `trend_direction=1.1`, `ma_alignment=0.8`

### 12.2 Context dimensions (9)
Each context dimension maps to `[-1,1]` with deterministic mapping and reason template:
- `source_prior`
- `trend_regime`
- `price_structure`
- `momentum`
- `risk_balance`
- `liquidity`
- `session`
- `execution_feedback`
- `account_posture`

Context mapping parameters are profile-configurable and support profile-specific overrides.

### 12.3 Canonical algorithm schema and default params (required)
Every dimension must provide one algorithm config with explicit param schema.

`piecewise`:
- required: `knots[]` (ordered by `x`), `left_clip`, `right_clip`
- each knot: `{x: number, y: number}` with `y in [-1, 1]`

`linear`:
- required: `slope`, `intercept`, `min_clip`, `max_clip`

`sigmoid`:
- required: `k`, `x0`, `min_clip`, `max_clip`

`lookup_map`:
- required: `map` (`{string -> score}`), `default_score`

`condition_map`:
- required: `rules[]` (ordered predicates with output score), `default_score`

`composite_rule`:
- required: `components[]` (sub-metrics + local weights), `combine_mode`, `min_clip`, `max_clip`

Dimension default schema keys (minimum required):
- `trend_direction`: `bull_score`, `mild_bull_score`, `mild_bear_score`, `bear_score`
- `ma_alignment`: `order_score_map`, `alignment_smooth_k`
- `ma_slope`: `slope_scale`, `neutral_band`, `min_clip`, `max_clip`
- `price_vs_ma20`: `distance_bands`, `band_scores`
- `macd_level`: `hist_bands`, `dif_sign_adjust`
- `macd_hist_slope`: `slope_bands`, `band_scores`
- `rsi_zone`: `oversold`, `neutral_low`, `neutral_high`, `overbought`, `zone_scores`
- `kdj_cross`: `cross_strength_bands`, `extreme_zone_adjust`
- `volume_ratio`: `ratio_bands`, `ratio_scores`
- `obv_trend`: `window`, `slope_bands`, `slope_scores`
- `atr_risk`: `atr_pct_bands`, `risk_scores`
- `boll_position`: `position_bands`, `position_scores`
- `source_prior`: `source_score_map`
- `trend_regime`: `regime_score_map`
- `price_structure`: `structure_score_map`
- `momentum`: `momentum_bands`, `momentum_scores`
- `risk_balance`: `risk_bands`, `risk_scores`
- `liquidity`: `liq_bands`, `liq_scores`
- `session`: `session_score_map`
- `execution_feedback`: `feedback_decay_half_life`, `min_feedback_samples`, `success_weight`, `failure_weight`, `execution_feedback_score_cap`
- `account_posture`: `cash_ratio_bands`, `posture_scores`

## 13. Golden Fixture Regression Tests

Required fixtures:
1. `candidate_full_data.json`
2. `candidate_missing_partial.json`
3. `position_full_data.json`
4. `position_missing_partial.json`
5. `hybrid_conflict_rule_buy_weight_hold.json`
6. `hybrid_conflict_rule_hold_weight_buy_gate_fail.json`
7. `hard_veto_override.json`
8. `legacy_v1_payload.json`
9. `track_unavailable_one_side.json`
10. `config_invalid_weights.json`

Each fixture asserts:
- final action
- fusion score
- track/group coverage and confidence
- precedence branch
- veto resolution
- schema version/adapter behavior

## 14. File Mapping
- `app/quant_kernel/config.py`: schema, validation, profile merge
- `app/quant_kernel/runtime.py`: scoring pipeline, missing handling, v2.3 payload
- `app/quant_kernel/decision_engine.py`: hybrid precedence, veto priority
- `app/quant_sim/signal_center_service.py`: overlay migration to context features
- `app/gateway_api.py`: v1 adapter + v2.3 read-model output
- `ui/src/features/quant/signal-detail-page.tsx`: canonical renderer

## 15. Acceptance Criteria
1. Formulas in section 3 implemented exactly (including group-local normalization).
2. Missing handling in section 4 deterministic and reason-coded.
3. Candidate/position profile behavior in section 5 and action mapping in section 6 implemented.
4. Hybrid precedence and confirmation in section 7 implemented exactly.
5. Context grouped scoring and overlay ownership in section 8 implemented.
6. Config schema and validation in section 9 enforced.
7. Schema versioning and compatibility in section 10 pass.
8. Explainability contract in section 11 matches runtime truth.
9. Scorers in section 12 are coded with deterministic mappings.
10. All fixtures in section 13 pass.

## 16. Strategy Profile Configuration (UI + API + Runtime Binding)

### 16.1 Requirement
All tunable knobs for parameters, weights, and scoring algorithms must be configurable through UI-managed strategy profiles.
Each profile can be saved and applied independently in:
- live simulation
- historical replay

### 16.2 Tunable scope exposed by profile
Each profile contains:
1. General:
- `profile_name`
- `profile_code`
- `description`
- `enabled`
2. Dual-track:
- `mode` (`rule_only`, `weighted_only`, `hybrid`)
- `track_weights.tech`
- `track_weights.context`
- `fusion_buy_threshold`
- `fusion_sell_threshold`
- `sell_precedence_gate`
- `min_fusion_confidence`
- `min_tech_score_for_buy`
- `min_context_score_for_buy`
- `min_tech_confidence_for_buy`
- `min_context_confidence_for_buy`
- `lambda_divergence`
- `lambda_sign_conflict`
- `threshold_mode` (`static`, `volatility_adjusted`)
- `buy_vol_k`
- `sell_vol_k`
3. Technical scoring:
- group weights
- dimension weights (12 dimensions)
- per-dimension scorer algorithm type and parameters
4. Context scoring:
- dimension weights (9 dimensions)
- per-dimension scorer algorithm type and parameters
- execution feedback policy parameters (`feedback_decay_half_life`, `min_feedback_samples`, `execution_feedback_score_cap`)
5. Profile overrides:
- candidate profile overrides
- position profile overrides
6. Per-profile dual-track overrides:
- candidate/position may override dual-track thresholds and gates (including `fusion_buy_threshold`, `fusion_sell_threshold`, `sell_precedence_gate`, confidence gates)
- per-profile override precedence: `profile.dual_track` > `base.dual_track`

Algorithm types (v2.3):
- `piecewise`
- `linear`
- `sigmoid`
- `lookup_map`
- `condition_map`
- `composite_rule`

Mandatory configurability rule:
- Any numeric constant, threshold, ratio, percentage, slope factor, clamp bound, veto trigger level, or confirmation cutoff used by decision logic must come from strategy profile config (or inherited base profile), not hardcoded in runtime code.
- Runtime logic can only use validated profile defaults, and must not silently inject magic numbers.

### 16.3 Persistence model
Add strategy profile persistence (database):
- `strategy_profiles`
  - `id`
  - `profile_code` (unique)
  - `profile_name`
  - `description`
  - `enabled`
  - `is_system_default`
  - `schema_version` (default `quant_explain/v2.3`)
  - `config_json` (full validated scoring config)
  - `created_at`
  - `updated_at`
- `strategy_profile_versions` (optional but recommended)
  - immutable snapshots for audit and rollback
  - required for replay reproducibility unless replay task persists full `config_snapshot_json`

Live/replay task binding:
- live run/task table adds `strategy_profile_id`
- replay task table adds `strategy_profile_id`

### 16.4 API contract
Strategy profile management:
- `GET /api/v1/strategy-profiles`
- `GET /api/v1/strategy-profiles/{id}`
- `POST /api/v1/strategy-profiles`
- `PUT /api/v1/strategy-profiles/{id}`
- `POST /api/v1/strategy-profiles/{id}/clone`
- `POST /api/v1/strategy-profiles/{id}/validate`
- `POST /api/v1/strategy-profiles/{id}/set-default`
- `DELETE /api/v1/strategy-profiles/{id}` (logical delete or disable)

Binding and execution:
- live execution request accepts `strategy_profile_id`
- replay start request accepts `strategy_profile_id`
- replay start response must return bound immutable `strategy_profile_version_id` (or persisted `config_snapshot_hash`)
- task detail payload returns bound profile:
  - `strategy_profile_id`
  - `strategy_profile_name`
  - `strategy_profile_version`

Signal explain payload must include:
- `strategy_profile_id`
- `strategy_profile_name`
- `strategy_profile_version`

### 16.5 UI requirements
New settings module: `策略配置` page.

Page capabilities:
1. Profile list:
- list existing profiles
- show default profile badge
- clone/delete/enable-disable
2. Profile editor:
- sectioned form for dual-track, technical, context, overrides
- algorithm type selector and parameter editors per dimension
- context dimension-to-group mapping is read-only in v2.3 standard UI
- inline validation errors
- save as new version / save overwrite
3. Validation:
- run backend validate endpoint before save
- prevent invalid save

Live simulation page:
- add profile selector
- selected profile applied to all new live signal computations in that run

Historical replay page:
- add profile selector near replay start controls
- selected profile is frozen for the replay task lifecycle

### 16.6 Runtime resolution precedence
When scoring request arrives:
1. request-level `strategy_profile_id` (highest)
2. task-bound `strategy_profile_id`
3. environment default strategy profile
4. system fallback profile (lowest)

Live simulation behavior:
- if request explicitly provides missing/disabled profile => fail fast (400) unless `allow_live_profile_fallback=true`
- if no explicit profile provided => default profile resolution is allowed

Historical replay behavior:
- replay task must bind immutable `strategy_profile_version_id` or `config_snapshot_json` at creation
- if bound profile/version/snapshot is missing or invalid => replay task fails fast
- replay must never fallback to default profile after task creation
- this is required for replay reproducibility

### 16.7 Compatibility and migration
- Existing runs/tasks without `strategy_profile_id` continue using default profile.
- Existing behavior remains stable with default profile matching current baseline (`rule_only`).
- No breaking change to old signal payload consumers.
- Flat context legacy configs are auto-adapted into grouped context via compatibility adapter.

### 16.8 Full parameterization matrix (all dimensions)
For each dimension in a strategy profile, the UI/API must expose:
- `weight`
- `algorithm`
- `params` (all numeric knobs used by algorithm)
- `reason_template`

Technical (12) required configurable parameter groups:
1. `trend_direction`: ordering-score map, pullback penalty, full-break penalty.
2. `ma_alignment`: order-count to score mapping, smoothing parameters.
3. `ma_slope`: slope scale, neutral band, positive/negative caps.
4. `price_vs_ma20`: distance bands and per-band scores.
5. `macd_level`: DIF/DEA band thresholds and score map.
6. `macd_hist_slope`: histogram slope thresholds and score map.
7. `rsi_zone`: oversold/neutral/overbought cutoffs and scores.
8. `kdj_cross`: cross-strength thresholds, extreme-zone adjustments.
9. `volume_ratio`: low/normal/high/spike bands and scores.
10. `obv_trend`: slope-window length, trend thresholds, score map.
11. `atr_risk`: ATR% risk bands and penalty map.
12. `boll_position`: band position thresholds and score map.

Context (9) required configurable parameter groups:
1. `source_prior`: source class score mapping.
2. `trend_regime`: regime class score mapping.
3. `price_structure`: structure-pattern thresholds and scores.
4. `momentum`: momentum thresholds and scores.
5. `risk_balance`: risk band thresholds and penalties.
6. `liquidity`: liquidity band thresholds and penalties.
7. `session`: session time-window mapping.
8. `execution_feedback`: decay coefficient, success/failure impact weights.
9. `account_posture`: cash/position posture bands and scores.

Profile-level configurable decision parameters:
- dual-track mode
- track weights
- fusion thresholds
- confidence gates
- veto threshold parameters
- profile-specific overrides for candidate and position

### 16.9 Production default profile policy
Weighted/hybrid production defaults must use non-uniform group weights:
- technical groups: not all equal
- context groups: not all equal

Recommended production defaults:
- candidate technical group weights:
  - `trend=1.3`
  - `momentum=1.2`
  - `volume_confirmation=0.9`
  - `volatility_risk=0.8`
- position technical group weights:
  - `trend=1.1`
  - `momentum=0.8`
  - `volume_confirmation=0.9`
  - `volatility_risk=1.5`
- candidate context group weights:
  - `market_structure=1.4`
  - `risk_account=1.1`
  - `tradability_timing=0.7`
  - `source_execution=0.7`
- position context group weights:
  - `market_structure=1.0`
  - `risk_account=1.5`
  - `tradability_timing=0.6`
  - `source_execution=0.7`

## 17. Additional Acceptance Criteria for Strategy Profiles
11. UI can create/edit/clone/enable-disable strategy profiles.
12. UI can configure parameters, weights, and algorithms per profile.
13. Save operation enforces backend validation rules.
14. Live simulation can select and apply a strategy profile.
15. Historical replay can select and apply a strategy profile.
16. Task detail and signal detail expose applied profile id/name/version.
17. Existing tasks without profile binding still execute with default profile.
18. All 12 technical dimensions have editable algorithm parameters in UI.
19. All 9 context dimensions have editable algorithm parameters in UI.
20. Changing any active profile parameter deterministically affects scoring when its branch is exercised by targeted fixtures.
21. Switching strategy profile in live/replay applies new params/weights/algorithms without service restart.
22. Context grouped scoring is available in UI/API with editable group weights; dimension-to-group mapping is locked in v2.3 standard UI.
23. Weighted/hybrid production default profiles use non-uniform technical/context group weights.
24. Weak weighted `SELL` cannot override `HOLD/BUY` unless `FusionScore <= sell_precedence_gate`.
25. Fusion confidence includes divergence and sign-conflict penalty fields and values in explainability payload.
26. Candidate `reject` outcomes are not emitted as tradable `SELL` signals in execution-facing APIs/UI.
27. Dynamic threshold mode (`volatility_adjusted`) is configurable and reflected in effective threshold fields.

## 18. Rollout Policy (Production Safety)
1. Phase A: ship v2.3 payload and config schema under `rule_only`.
2. Phase B: enable `weighted_only` in replay/backtest first and validate score distribution + action stability.
3. Phase C: enable `hybrid` only after:
- sell-precedence gate behavior is validated on golden and replay suites.
- divergence-penalized confidence reduces conflicting-track false positives as expected.
- candidate reject filtering is verified in API/UI.
