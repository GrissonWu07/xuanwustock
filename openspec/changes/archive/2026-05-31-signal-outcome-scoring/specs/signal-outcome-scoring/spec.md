## ADDED Requirements

### Requirement: Signal Outcome Scoring

The system SHALL calculate matured outcome scores for BUY and SELL signals using only market and technical artifacts visible within the signal's completed prediction window.

Each eligible signal SHALL produce outcome records for `3`, `5`, and `10` checkpoint horizons when the horizon is complete. Each outcome score SHALL be in `[0, 100]` and SHALL retain raw metrics needed to explain the score.

The system SHALL NOT use discovery source score, source confidence, source type, source name, source count, source display text, or multi-source bonus as inputs to outcome scoring.

#### Scenario: BUY signal outcome is scored after horizon matures

- **GIVEN** a BUY signal was generated at checkpoint `T`
- **AND** the signal has an artifact reference for its own checkpoint
- **AND** at least 5 later checkpoint artifacts exist for the same stock and run/domain
- **WHEN** outcome scoring runs for horizon `5`
- **THEN** the system SHALL create a BUY outcome record
- **AND** the record SHALL include `mfe_pct`, `mae_pct`, `target_hit`, `invalidation_hit`, `ma20_break_after_buy`, `t1_loss_amplified`, `delay_cost_pct`, `market_alignment`, `outcome_score`, `matured_at`, and `source_artifact_ref`
- **AND** `matured_at` SHALL equal the fifth later checkpoint used by the outcome window.

#### Scenario: SELL signal outcome is scored after horizon matures

- **GIVEN** a SELL signal was generated at checkpoint `T`
- **AND** at least 3 later checkpoint artifacts exist for the same stock and run/domain
- **WHEN** outcome scoring runs for horizon `3`
- **THEN** the system SHALL create a SELL outcome record
- **AND** the record SHALL include `avoided_drawdown_pct`, `missed_upside_pct`, `target_hit`, `sell_validated`, `quick_rebuy_after_sell`, `market_alignment`, `outcome_score`, `matured_at`, and `source_artifact_ref`
- **AND** the score explanation SHALL identify the SELL intent category when available.

#### Scenario: Incomplete horizon is not scored as mature

- **GIVEN** a signal has only 2 later checkpoint artifacts
- **WHEN** outcome scoring evaluates horizons `3`, `5`, and `10`
- **THEN** no mature outcome SHALL be created for horizons that do not have enough later artifacts
- **AND** the skipped horizon diagnostic SHALL expose `horizon_not_mature`.

### Requirement: Matured-Only Feedback Consumption

The system SHALL use outcome data in future trading decisions only through matured outcome records where `matured_at <= current_checkpoint`.

The system SHALL NOT use current-signal future price movement to decide whether that same signal should execute.

#### Scenario: Current checkpoint cannot read future outcome

- **GIVEN** a BUY signal is generated at checkpoint `2026-01-08 10:00:00`
- **AND** its horizon-5 outcome will mature at `2026-01-09 11:00:00`
- **WHEN** trading decisions are made at `2026-01-08 10:00:00`
- **THEN** the system SHALL NOT read or apply that horizon-5 outcome
- **AND** execution diagnostics SHALL NOT contain feedback derived from that future outcome.

#### Scenario: Later checkpoint can read matured historical outcome

- **GIVEN** a previous BUY outcome has `matured_at = 2026-01-09 11:00:00`
- **WHEN** a new signal for the same stock is evaluated at `2026-01-10 10:00:00`
- **THEN** the system MAY apply the matured outcome through `outcome_feedback_score`
- **AND** the decision diagnostics SHALL include the feedback sample count and reason code when it changes sizing, threshold, or lifecycle gate behavior.

### Requirement: Outcome Feedback Score

The system SHALL aggregate matured outcome records into a stock-level `outcome_feedback_score` that can be consumed by execution feedback, portfolio guard, and quant lifecycle logic without changing the meaning of `candidate_score`.

The aggregate SHALL include sample count, BUY score average, SELL score average, recent failed probe count, repeated weak signal count, good SELL validation count, bad SELL validation count, decay-weighted score, and the latest contributing `matured_at`.

The aggregate SHALL use only outcome records already mature for the evaluation checkpoint and SHALL apply minimum sample and time-decay controls before changing trading behavior.

#### Scenario: Outcome feedback downgrades repeated bad BUY behavior

- **GIVEN** a stock has enough matured BUY outcome samples
- **AND** recent BUY outcomes show low MFE, high MAE, repeated MA20 break after buy, or repeated probe loss
- **WHEN** the same stock produces another BUY signal after those outcomes matured
- **THEN** stock execution feedback SHALL be able to downgrade sizing, require stronger confirmation, or enter probe cooldown
- **AND** the decision diagnostics SHALL cite `outcome_feedback_score` and the contributing mature sample count.

#### Scenario: Outcome feedback does not overwrite candidate score

- **GIVEN** a stock has poor mature outcome feedback
- **AND** its current technical entry artifact produces a high `candidate_score`
- **WHEN** lifecycle entry is evaluated
- **THEN** the technical `candidate_score` SHALL remain the score calculated from current technical facts
- **AND** outcome feedback SHALL appear only as a separate feedback/gate field or reason.

### Requirement: Live Replay Drill Data Isolation

The system SHALL use the same outcome scoring algorithm for live quant, historical replay, and live quant drill while keeping their persisted data isolated.

Live outcome records SHALL be associated with live signals. Historical replay and live quant drill outcome records SHALL be associated with `run_id` and `run_type`, and SHALL NOT update live signal, live trade, live lifecycle, or live feedback tables.

#### Scenario: Replay outcome does not alter live feedback

- **GIVEN** a historical replay run creates matured BUY outcomes for stock `300736`
- **WHEN** outcome feedback is aggregated inside that replay run
- **THEN** the replay feedback SHALL be queryable for that run
- **AND** live `stock_execution_feedback` and live lifecycle state SHALL remain unchanged.

#### Scenario: Live feedback uses live matured outcomes only

- **GIVEN** live quant evaluates a BUY signal
- **WHEN** it reads outcome feedback for that stock
- **THEN** it SHALL use only live-domain matured outcomes
- **AND** it SHALL NOT read replay or drill outcome rows.

### Requirement: Outcome Evidence and Diagnostics

The system SHALL expose signal outcome and outcome feedback diagnostics through existing signal detail, historical replay, live quant drill, and quant lifecycle diagnostic entry points.

The exposed diagnostics SHALL include the score, horizon, matured status, source artifact reference, key raw metrics, feedback impact, reason codes, and skipped/partial reasons.

#### Scenario: Signal detail exposes outcome records

- **GIVEN** a user opens a BUY or SELL signal detail page
- **WHEN** the signal has mature outcome records
- **THEN** the response SHALL include outcome rows by horizon
- **AND** the UI SHALL show score, MFE/MAE or avoided drawdown/missed upside, target/invalidated state, and feedback impact when applicable.

#### Scenario: Run result exposes outcome summary

- **GIVEN** a historical replay or live quant drill run has completed outcome scoring
- **WHEN** the user views the run result page
- **THEN** the response SHALL include aggregate outcome counts, average BUY score, average SELL score, high-risk repeated weak signal count, and top positive/negative contributing stocks.

### Requirement: Artifact-Backed Scoring and Missing Data Handling

The system SHALL calculate outcomes from `market_technical_artifact` records referenced by signal/run/domain identity.

If required artifact data is missing, partial, stale, or invalid, the system SHALL not silently substitute current live data. It SHALL persist a skipped or partial diagnostic reason instead.

#### Scenario: Missing run artifact is recorded as skipped outcome

- **GIVEN** a replay signal references a run-scoped artifact
- **AND** the required future horizon artifact is missing
- **WHEN** outcome scoring runs
- **THEN** the system SHALL NOT read live artifact data as a fallback
- **AND** it SHALL record `missing_horizon_artifact` or `horizon_not_mature` for that horizon.

#### Scenario: Source scoring fields are scrubbed from outcome inputs

- **GIVEN** a market artifact or signal payload contains `source_score`, `source_confidence`, or `multi_source_bonus`
- **WHEN** outcome scoring reads the input facts
- **THEN** those fields SHALL be ignored
- **AND** they SHALL NOT appear in the outcome formula breakdown.

### Requirement: Outcome Configuration

The system SHALL provide strategy-profile aware configuration for outcome scoring and outcome feedback thresholds.

Default configuration SHALL include:

| Parameter | aggressive | stable | conservative |
|---|---:|---:|---:|
| `outcome_feedback_enabled` | true | true | true |
| `outcome_horizons_checkpoints` | `3,5,10` | `3,5,10` | `3,5,10` |
| `buy_target_pct` | 4.0 | 3.0 | 2.5 |
| `buy_invalidation_mae_pct` | -4.5 | -3.5 | -2.8 |
| `sell_validation_drawdown_pct` | 3.0 | 2.5 | 2.0 |
| `missed_upside_penalty_pct` | 5.0 | 4.0 | 3.0 |
| `min_feedback_samples` | 3 | 4 | 5 |
| `feedback_lookback_days` | 30 | 45 | 60 |
| `poor_buy_score_threshold` | 45 | 50 | 55 |
| `good_sell_score_threshold` | 65 | 70 | 75 |
| `feedback_size_multiplier_floor` | 0.30 | 0.25 | 0.20 |

#### Scenario: Profile-specific outcome feedback is applied

- **GIVEN** the active strategy profile is `aggressive`
- **WHEN** outcome feedback evaluates mature BUY outcomes
- **THEN** it SHALL use the aggressive target, invalidation, sample, lookback, and multiplier defaults unless the saved strategy profile configuration overrides them.

#### Scenario: Configuration is visible in strategy config

- **GIVEN** the user opens strategy configuration
- **WHEN** outcome feedback configuration exists
- **THEN** the UI SHALL expose editable fields for horizons, target/invalidation thresholds, minimum samples, lookback days, and feedback multiplier floor.
