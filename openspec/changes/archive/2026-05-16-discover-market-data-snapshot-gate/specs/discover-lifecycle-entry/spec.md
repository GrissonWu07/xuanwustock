## ADDED Requirements

### Requirement: Discovery Prepares Technical Snapshot Before Lifecycle Eligibility

The system SHALL determine 30m technical snapshot readiness for each unique discovered stock before publishing automatic lifecycle eligibility for that stock.

#### Scenario: Discovered stock has no local 30m data

- **GIVEN** a discovery task returns a stock and local 30m market data is unavailable for that stock
- **WHEN** the discovery task prepares lifecycle eligibility
- **THEN** the system SHALL attempt to prepare the missing 30m market data and derived technical indicators before the stock can be marked eligible for automatic quant entry
- **AND** the discovery task SHALL report whether preparation succeeded or failed for that stock.

#### Scenario: Duplicate discovery rows reference the same stock

- **GIVEN** multiple discovery rows in the same task reference the same stock code
- **WHEN** the discovery task prepares technical snapshot readiness
- **THEN** the system SHALL evaluate readiness once per unique stock for that task
- **AND** each discovery row for that stock SHALL expose the same readiness result.

### Requirement: Complete Snapshot Defines Automatic Entry Readiness

The system SHALL require a complete 30m technical snapshot before a discovered stock may enter automatic quant trial state.

#### Scenario: Snapshot contains all required fields

- **GIVEN** a discovered stock has a 30m technical snapshot with current price or close, moving average fields, MA20 slope, amount, volume ratio, RSI, MACD, trend, snapshot timestamp, provider, timeframe, and indicator version
- **WHEN** the stock is evaluated for automatic lifecycle entry
- **THEN** the system MAY evaluate the stock against the normal score, confidence, technical confirmation, capacity, and lifecycle rules.

#### Scenario: Snapshot is missing a required technical field

- **GIVEN** a discovered stock is missing at least one required 30m technical snapshot field
- **WHEN** the stock is evaluated for automatic lifecycle entry
- **THEN** the system SHALL NOT enter the stock into automatic quant trial state
- **AND** the lifecycle outcome SHALL identify `missing_technical_snapshot` as a machine-readable blocking reason
- **AND** the lifecycle outcome SHALL include the missing field names.

#### Scenario: Snapshot exists but is not ready for required moving averages

- **GIVEN** a discovered stock has 30m market data but does not have enough usable data to produce the required moving average readiness
- **WHEN** the stock is evaluated for automatic lifecycle entry
- **THEN** the system SHALL treat the technical snapshot as incomplete
- **AND** the stock SHALL be blocked from automatic quant trial state with a machine-readable reason.

### Requirement: Lifecycle Gate Defends Against Incomplete Discovery Inputs

The system SHALL reject automatic lifecycle entry for incomplete technical snapshots even when the discovery result contains score or confidence values.

#### Scenario: Candidate has score but no technical snapshot

- **GIVEN** a discovered stock has score and confidence values
- **AND** the stock lacks a complete 30m technical snapshot
- **WHEN** automatic lifecycle entry is evaluated
- **THEN** the stock SHALL NOT enter automatic quant trial state
- **AND** the result SHALL explain that technical snapshot readiness is missing rather than lowering lifecycle thresholds.

#### Scenario: Candidate has text-only technical explanation

- **GIVEN** a discovered stock has a textual explanation that mentions technical strength
- **AND** the structured 30m technical snapshot fields are incomplete
- **WHEN** automatic lifecycle entry is evaluated
- **THEN** the stock SHALL NOT be treated as technically ready based only on the text explanation
- **AND** the missing structured fields SHALL remain visible in diagnostics.

### Requirement: Discovery Results Expose Technical Readiness

The system SHALL expose technical snapshot readiness and missing-field diagnostics wherever discovery candidates are presented to users or API consumers.

#### Scenario: User views discovery table

- **GIVEN** a discovery task has completed
- **WHEN** a user views the discovery results
- **THEN** each candidate row SHALL show whether the 30m technical snapshot is ready or incomplete
- **AND** incomplete rows SHALL show the missing technical fields or a concise reason that links to those missing fields.

#### Scenario: User inspects a blocked candidate

- **GIVEN** a discovered stock was blocked from automatic quant entry because of an incomplete technical snapshot
- **WHEN** a user inspects the candidate details
- **THEN** the details SHALL show the lifecycle status, `missing_technical_snapshot` reason, and the missing field names.

### Requirement: Discovery Task Reports Snapshot Preparation Diagnostics

The system SHALL report aggregate diagnostics for technical snapshot preparation after a discovery task completes.

#### Scenario: Discovery task has mixed snapshot outcomes

- **GIVEN** a discovery task produces candidates with complete snapshots, incomplete snapshots, and preparation failures
- **WHEN** the task result is returned
- **THEN** the task result SHALL include counts for unique stocks checked, snapshots prepared, complete snapshots, incomplete snapshots, preparation failures, and candidates blocked from automatic entry.

#### Scenario: Market data provider cannot prepare a stock

- **GIVEN** a discovered stock cannot be prepared because required market data is unavailable
- **WHEN** the discovery task completes
- **THEN** the task diagnostics SHALL include the stock code and a safe failure reason
- **AND** the stock SHALL NOT enter automatic quant trial state.

### Requirement: Normal DB Cleanup Preserves Market Data Cache

The system SHALL preserve local market-data caches during normal database reset or cleanup operations unless cache deletion is explicitly requested.

#### Scenario: User requests DB data cleanup only

- **GIVEN** a user or maintenance process requests cleanup of database data
- **WHEN** the cleanup operation runs
- **THEN** locally cached market data and generated indicators SHALL remain available
- **AND** subsequent discovery tasks MAY reuse the preserved cache for snapshot readiness.

#### Scenario: User explicitly requests cache deletion

- **GIVEN** a user explicitly requests deletion of local market-data cache
- **WHEN** the cache cleanup operation runs
- **THEN** the operation SHALL make the cache deletion scope clear before deleting cache data.
