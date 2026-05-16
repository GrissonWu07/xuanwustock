## ADDED Requirements

### Requirement: Discovery Publishes Current Candidate Evidence

The system SHALL publish a current discovery candidate set with source evidence
and run traceability after a discovery task completes.

#### Scenario: Discovery task completes with candidates

- **GIVEN** a discovery task returns one or more candidates from selected
  strategies
- **WHEN** the task completes
- **THEN** the discovery result SHALL expose the candidate stock code, name,
  source strategy, selected time, discovery run identifier, and available
  source score or confidence evidence
- **AND** the candidate set SHALL be available to later discover API reads
  without depending on raw selector text alone.

#### Scenario: Multiple strategies return the same stock

- **GIVEN** multiple selected discovery strategies return the same stock code
- **WHEN** the discovery task publishes the current candidate set
- **THEN** each candidate row SHALL preserve its source strategy evidence
- **AND** refresh readiness for that stock SHALL be evaluated once per unique
  stock code for the task.

### Requirement: Discovery Candidates Use Latest Refreshed Technical Snapshot

The system SHALL hydrate discovery candidates with the latest refreshed 30m
market and technical snapshot before automatic lifecycle eligibility is
published or displayed.

#### Scenario: Selector result has no technical fields

- **GIVEN** a discovery strategy returns a candidate without structured MA,
  MACD, RSI, amount, volume ratio, trend, or snapshot metadata
- **WHEN** the discovery task prepares lifecycle eligibility
- **THEN** the system SHALL refresh or reuse the latest available 30m technical
  snapshot for that stock
- **AND** the task result SHALL report whether the refreshed snapshot is ready,
  incomplete, stale, or failed.

#### Scenario: Refreshed snapshot is complete

- **GIVEN** a discovered stock has a refreshed 30m snapshot with current price
  or close, moving averages, MA20 slope, amount, volume ratio, RSI, MACD,
  trend, timestamp, provider, timeframe, and indicator version
- **WHEN** the stock is evaluated for automatic lifecycle entry
- **THEN** the system MAY evaluate the stock against the normal score,
  confidence, technical confirmation, capacity, and lifecycle rules
- **AND** the discover API SHALL expose those refreshed technical fields.

#### Scenario: Refreshed snapshot is missing or stale

- **GIVEN** a discovered stock has no refreshed technical snapshot, an
  incomplete snapshot, or a snapshot that is older than the accepted freshness
  window
- **WHEN** the stock is evaluated or shown
- **THEN** the stock SHALL NOT enter automatic quant trial state
- **AND** the discovery row and lifecycle outcome SHALL expose
  `missing_technical_snapshot` or a more specific stale/unprepared reason
- **AND** missing fields or refresh failure details SHALL be visible as safe
  diagnostics.

### Requirement: Discovery API And Lifecycle Ingestion Share Hydrated Evidence

The system SHALL use the same hydrated candidate evidence for discover API rows
and lifecycle candidate event ingestion for a completed discovery run.

#### Scenario: Candidate event is created

- **GIVEN** a completed discovery run has hydrated a candidate from the latest
  refreshed 30m snapshot
- **WHEN** lifecycle candidate events are created
- **THEN** the candidate event payload SHALL include the same refreshed
  technical readiness fields, snapshot metadata, trend, technical confirmation
  count, score, and confidence that discover API rows expose for that candidate.

#### Scenario: User reads discover API after ingestion

- **GIVEN** lifecycle ingestion has consumed or changed the status of a
  candidate event
- **WHEN** a user or client reads the discover API
- **THEN** the discovery row SHALL still expose the latest refreshed technical
  readiness diagnostics for that stock
- **AND** lifecycle status changes SHALL NOT erase the technical evidence shown
  to the user.

### Requirement: Lifecycle Scoring Runs After Refresh Hydration

The system SHALL calculate discovery lifecycle score, confidence, trend, and
technical confirmation after latest refreshed technical evidence is applied.

#### Scenario: Technical confirmation comes from refreshed indicators

- **GIVEN** a discovery candidate originally lacks structured technical
  confirmation fields
- **AND** the latest refreshed 30m snapshot contains trend and indicator
  evidence
- **WHEN** lifecycle scoring is calculated
- **THEN** the score diagnostics SHALL reflect the refreshed trend and technical
  confirmation evidence
- **AND** the candidate SHALL NOT be scored from raw selector text alone.

#### Scenario: Lifecycle thresholds remain unchanged

- **GIVEN** lifecycle thresholds, gates, capacity limits, and source-family
  rules are configured
- **WHEN** discovery candidates are refreshed and scored
- **THEN** the system SHALL NOT lower thresholds, bypass gates, or enter a stock
  into automatic quant trial state without satisfying the existing lifecycle
  rules.

### Requirement: Discovery Fallback Rows Are Explicitly Stale

The system SHALL mark raw selector fallback rows as stale or unprepared when no
current hydrated discovery candidate view is available.

#### Scenario: Only raw selector output exists

- **GIVEN** old selector output exists but no current hydrated discovery
  candidate view is available
- **WHEN** a user or client reads discovery results
- **THEN** the returned rows SHALL explicitly indicate stale or unprepared
  status
- **AND** the rows SHALL NOT appear as current technically ready candidates.

#### Scenario: Existing historical records remain untouched

- **GIVEN** old candidate records or selector files exist without refreshed
  technical snapshot fields
- **WHEN** this change is applied
- **THEN** the system SHALL NOT rewrite historical records automatically
- **AND** a subsequent discovery run SHALL publish corrected refreshed evidence
  for newly generated candidates.
