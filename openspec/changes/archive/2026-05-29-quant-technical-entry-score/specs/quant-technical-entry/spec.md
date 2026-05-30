## MODIFIED Requirements

### Requirement: Technical Candidate Entry Score

The system SHALL calculate lifecycle `candidate_score` as a quant technical
entry score in `[0, 1]` using only the stock's行情 data and technical indicators
at the evaluated snapshot or checkpoint.

The score SHALL use this observable formula:

```text
candidate_score =
  clamp(
    0.35 * trend_structure_score
  + 0.20 * momentum_score
  + 0.15 * volume_liquidity_score
  + 0.20 * confirmation_score
  + 0.10 * risk_quality_score
  - overextension_penalty
  - overheated_penalty
  - stale_data_penalty,
  0,
  1
)
```

The system SHALL NOT use discovery source score, scanner score, source
confidence, source name, source type, source count, or source display text as a
positive or negative input to `candidate_score`.

The system SHALL calculate component scores as follows:

```text
trend_structure_score =
  clamp(
    0.25 * price_above_ma20
  + 0.15 * price_above_ma60
  + 0.25 * ma_stack_score
  + 0.20 * ma20_slope_score
  + 0.15 * trend_alignment_score,
  0,
  1
)

momentum_score =
  clamp(
    0.40 * macd_score
  + 0.30 * rsi_constructive_score
  + 0.20 * short_ma_spread_score
  + 0.10 * medium_ma_spread_score,
  0,
  1
)

volume_liquidity_score =
  clamp(
    0.55 * amount_floor_score
  + 0.45 * volume_ratio_constructive_score,
  0,
  1
)

confirmation_score =
  clamp(
    0.60 * consecutive_checkpoint_score
  + 0.40 * ma20_breakout_retest_score,
  0,
  1
)

risk_quality_score =
  clamp(
    0.40 * ma20_distance_quality
  + 0.25 * ma60_distance_quality
  + 0.20 * rsi_risk_quality
  + 0.15 * volume_risk_quality,
  0,
  1
)
```

If consecutive checkpoint or retest evidence is unavailable, the system MAY use
current-snapshot technical confirmation count as a fallback, but that fallback
SHALL be capped at `0.50` so a single snapshot cannot receive full confirmation
credit.

#### Scenario: Strong technical candidate receives high entry score

- **GIVEN** a candidate has a ready 30m technical snapshot
- **AND** price is above MA20 and MA60
- **AND** MA5 >= MA10 >= MA20
- **AND** MA20 slope is positive
- **AND** MACD is positive
- **AND** RSI is in a non-overheated constructive range
- **AND** amount and volume ratio pass liquidity rules
- **WHEN** the lifecycle evaluator calculates `candidate_score`
- **THEN** the returned score SHALL be based on the technical components and
  penalties
- **AND** the score breakdown SHALL include `trend_structure_score`,
  `momentum_score`, `volume_liquidity_score`, `confirmation_score`,
  `risk_quality_score`, `overextension_penalty`, `overheated_penalty`, and
  `stale_data_penalty`
- **AND** the score breakdown SHALL NOT include source-score or
  recommendation-score components.

#### Scenario: High source score does not improve weak technical candidate

- **GIVEN** a candidate has high discovery ranking or AI scanner score
- **AND** price is below MA20 while MA20 slope is negative
- **WHEN** the lifecycle evaluator calculates `candidate_score`
- **THEN** the source score SHALL be ignored
- **AND** the candidate SHALL either receive a low technical score or be blocked
  by the technical entry gate.

### Requirement: Technical Confidence

The system SHALL calculate lifecycle `candidate_confidence` in `[0, 1]` from
technical-data quality only.

The confidence SHALL use this observable formula:

```text
candidate_confidence =
  clamp(
    0.40 * technical_field_coverage
  + 0.25 * snapshot_freshness
  + 0.20 * indicator_consistency
  + 0.15 * history_depth,
  0,
  1
)
```

The system SHALL NOT use discovery source confidence, AI confidence, source
rank, source name, source count, or source display text as an input to
`candidate_confidence`.

#### Scenario: Complete and fresh technical data produces usable confidence

- **GIVEN** a candidate has all required technical fields
- **AND** the snapshot time is valid for the current system time or replay
  checkpoint
- **AND** the indicators are internally consistent
- **AND** the history depth is enough to support the longest required moving
  average
- **WHEN** the lifecycle evaluator calculates `candidate_confidence`
- **THEN** the confidence SHALL reflect technical coverage, freshness,
  consistency, and history depth only.

#### Scenario: Source confidence is ignored

- **GIVEN** two candidates have identical technical snapshots
- **AND** their source confidence values differ
- **WHEN** the lifecycle evaluator calculates `candidate_confidence`
- **THEN** both candidates SHALL receive the same `candidate_confidence`.

### Requirement: Technical Entry Components

The system SHALL calculate the technical score components with the following
observable meanings:

- `trend_structure_score`: reward price above MA20, price above MA60, MA5 >=
  MA10 >= MA20, positive MA20 slope, and trend label agreeing with MA evidence.
- `momentum_score`: reward positive MACD, constructive RSI, and positive
  short-to-medium momentum implied by MA relationships.
- `volume_liquidity_score`: reward amount meeting the profile liquidity floor
  and volume ratio in a constructive range.
- `confirmation_score`: reward technical confirmation count and consecutive
  checkpoint confirmation when available. Full confirmation credit requires
  multi-checkpoint persistence or MA20 breakout/retest evidence, not only a
  single current snapshot.
- `risk_quality_score`: reward non-overextended distance from MA20/MA60,
  non-overheated RSI, and absence of persistent downtrend evidence.

#### Scenario: Component scores are visible for audit

- **GIVEN** a candidate is evaluated for automatic trial entry
- **WHEN** the API returns lifecycle scoring diagnostics
- **THEN** the response SHALL expose the technical component scores and
  penalties needed to explain the final `candidate_score`.

#### Scenario: Single snapshot confirmation is capped

- **GIVEN** a candidate has only the current technical snapshot available
- **AND** no consecutive checkpoint or breakout/retest evidence is available
- **WHEN** the lifecycle evaluator calculates `confirmation_score`
- **THEN** current-snapshot confirmation SHALL NOT produce a
  `confirmation_score` greater than `0.50`.

#### Scenario: Severe chase risk is penalized separately

- **GIVEN** a candidate has a positive trend structure
- **AND** price is severely extended above MA20 or MA60
- **OR** RSI or volume ratio indicates an overheated chase condition
- **WHEN** the lifecycle evaluator calculates `candidate_score`
- **THEN** the candidate MAY still receive trend and momentum credit
- **AND** the overextension or overheated condition SHALL appear as a separate
  penalty in the score breakdown.

### Requirement: Technical Entry Gates

The system SHALL block automatic quant entry before score threshold comparison
when required technical evidence is missing, stale, or structurally invalid.

Automatic trial entry SHALL require:

- ready technical snapshot,
- valid price,
- valid MA5, MA10, MA20, MA20 slope, and MA60,
- valid amount and volume ratio,
- valid RSI and MACD,
- valid trend, provider, timeframe, snapshot time, and indicator version,
- amount meeting the active profile's minimum liquidity floor,
- non-persistent downtrend structure,
- `candidate_confidence` meeting the active profile's minimum confidence floor.

#### Scenario: Missing technical snapshot blocks entry

- **GIVEN** a discovery candidate has source evidence
- **AND** the required technical snapshot fields are missing
- **WHEN** automatic quant entry evaluates the candidate
- **THEN** the candidate SHALL NOT enter `trial`
- **AND** the blocking reason SHALL identify missing or stale technical data.

#### Scenario: Source family does not change score semantics

- **GIVEN** two candidates have the same technical snapshot
- **AND** one candidate came from AI scanner while the other came from main force
  discovery
- **WHEN** automatic quant entry evaluates both candidates
- **THEN** both candidates SHALL receive the same `candidate_score` and
  `candidate_confidence`
- **AND** source metadata MAY be retained only for audit and capacity reporting.

### Requirement: Profile Thresholds

The system SHALL compare the pure technical `candidate_score` and
`candidate_confidence` against profile thresholds for automatic lifecycle entry.

The default technical entry thresholds SHALL be:

| Profile | `trial_threshold` | `min_candidate_confidence` | `strong_candidate_threshold` | `high_reentry_threshold` |
|---|---:|---:|---:|---:|
| aggressive | 0.50 | 0.70 | 0.70 | 0.85 |
| stable | 0.55 | 0.75 | 0.75 | 0.88 |
| conservative | 0.65 | 0.80 | 0.82 | 0.92 |

#### Scenario: Score passes but confidence fails

- **GIVEN** a candidate has `candidate_score` above the active
  `trial_threshold`
- **AND** `candidate_confidence` is below the active
  `min_candidate_confidence`
- **WHEN** automatic quant entry evaluates the candidate
- **THEN** the candidate SHALL NOT enter `trial`
- **AND** the blocking reason SHALL identify insufficient technical confidence.

### Requirement: Flow Consistency

The system SHALL use the same technical entry scoring semantics for discovery
auto-entry, research/AI candidate entry, live quant, historical replay, and live
quant drill.

Each flow SHALL evaluate the technical snapshot for its own effective time:

- live quant and discovery use the latest valid system-time trading snapshot,
- historical replay uses the replay checkpoint's as-of snapshot,
- live quant drill uses the drill checkpoint's as-of snapshot.

#### Scenario: Replay does not use latest live snapshot

- **GIVEN** a replay checkpoint evaluates a candidate for `2026-01-15 10:00:00`
- **WHEN** the lifecycle evaluator calculates technical entry score
- **THEN** the score SHALL use the candidate's as-of technical evidence for that
  checkpoint
- **AND** it SHALL NOT use a later live snapshot.

### Requirement: Prepared Discovery Persistence

The system SHALL persist discovery candidates after行情 refresh and technical
indicator preparation before automatic lifecycle ingestion.

The persisted prepared candidate record SHALL include:

- stock identity and source audit metadata,
- effective snapshot/checkpoint time,
- refreshed price and required technical fields,
- technical readiness status and missing-field diagnostics,
- quant technical entry score, technical confidence, and score breakdown when
  evaluation has run.

Raw selector output, file cache, or provider cache SHALL NOT be the
authoritative business source for discover API rows or lifecycle entry
decisions after a discovery task completes. Provider or行情 caches MAY be used
only to accelerate market-data retrieval before persisting prepared records.

#### Scenario: Discovery task writes prepared records before ingestion

- **GIVEN** a discovery task returns raw candidate stocks
- **WHEN** the task refreshes行情 and technical indicators
- **THEN** the system SHALL persist the prepared candidate rows
- **AND** lifecycle ingestion SHALL read the prepared records or equivalent
  persisted candidate-event payloads
- **AND** it SHALL NOT depend on raw selector cache as the business source of
  truth.

#### Scenario: Failed technical preparation is persisted as blocked evidence

- **GIVEN** a discovery candidate cannot obtain a ready technical snapshot
- **WHEN** the discovery task completes
- **THEN** the system SHALL persist the candidate with technical readiness
  failure diagnostics
- **AND** automatic lifecycle entry SHALL block the candidate with a
  technical-data reason.

### Requirement: API and UI Score Semantics

The system SHALL expose source/discovery evidence separately from quant
technical entry evidence.

When both are present:

- discovery/source score SHALL be labeled as discovery/source evidence,
- lifecycle `candidate_score` SHALL be labeled as quant technical entry score,
- lifecycle `candidate_confidence` SHALL be labeled as technical confidence.

#### Scenario: Discover API does not substitute source score as candidate score

- **GIVEN** a discovered row has a source score but has not been technically
  evaluated
- **WHEN** the discover API returns the row
- **THEN** the row SHALL NOT expose the source score as lifecycle
  `candidate_score`
- **AND** it MAY expose the source score under a discovery/source field.
