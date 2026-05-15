## ADDED Requirements

### Requirement: Discovery Candidates Publish Lifecycle Inputs

The system SHALL publish normalized lifecycle input fields for every candidate returned by a discovery run.

#### Scenario: Candidate has explicit scoring evidence

- **GIVEN** a discovery strategy returns a candidate with explicit score, confidence, trend, and technical evidence
- **WHEN** the discovery run completes
- **THEN** the candidate's lifecycle input SHALL include normalized score and confidence values between 0.0 and 1.0
- **AND** the candidate's lifecycle input SHALL include trend and technical confirmation values derived from the discovery evidence
- **AND** the candidate SHALL NOT be evaluated with zero score or zero confidence solely because the discovery result was converted for display.

#### Scenario: Candidate lacks explicit scoring evidence

- **GIVEN** a discovery strategy returns a candidate without explicit score or confidence fields
- **WHEN** the discovery run completes
- **THEN** the system SHALL derive deterministic score and confidence values from available evidence such as ranking, data completeness, market liquidity, and strategy-specific measurable signals
- **AND** the derived values SHALL be visible in lifecycle diagnostics
- **AND** the system SHALL mark missing or weak evidence explicitly when derived values are insufficient for lifecycle entry.

#### Scenario: Candidate has no measurable evidence

- **GIVEN** a discovery strategy returns a candidate with only source identity and no measurable evidence
- **WHEN** the candidate is evaluated for lifecycle entry
- **THEN** the candidate SHALL NOT receive score credit solely from the source name
- **AND** the lifecycle outcome SHALL explain that evidence is missing or insufficient.

### Requirement: AI Discovery Preserves Structured Evidence

The system SHALL preserve AI discovery's structured scanner score, confidence evidence, trend evidence, and technical confirmation through discovery output and lifecycle evaluation.

#### Scenario: AI candidate includes scanner and technical evidence

- **GIVEN** AI discovery returns a candidate with scanner score and technical evidence
- **WHEN** the discovery result is shown and evaluated for lifecycle entry
- **THEN** the candidate SHALL expose the scanner score as lifecycle score input
- **AND** the candidate SHALL expose confidence and technical confirmation input
- **AND** the candidate SHALL NOT be classified as recommended-only due to missing technical confirmation when the original AI discovery result included sufficient technical confirmation.

#### Scenario: AI candidate lacks sufficient technical confirmation

- **GIVEN** AI discovery returns a candidate without sufficient technical confirmation
- **WHEN** the candidate is evaluated for lifecycle entry
- **THEN** the candidate MAY be classified as recommended-only
- **AND** the lifecycle outcome SHALL identify technical confirmation as the reason.

### Requirement: Lifecycle Entry Remains Rule Driven

The system SHALL use normalized discovery evidence as lifecycle input while preserving lifecycle thresholds, gates, and capacity limits.

#### Scenario: Candidate satisfies lifecycle rules

- **GIVEN** a discovered candidate has normalized evidence that satisfies lifecycle score, confidence, technical confirmation, and capacity rules
- **WHEN** the discovery run completes
- **THEN** the candidate SHALL enter the appropriate lifecycle entry state according to the configured lifecycle mode
- **AND** the discovery result SHALL report the candidate as already in quant or eligible according to the lifecycle outcome.

#### Scenario: Candidate does not satisfy lifecycle rules

- **GIVEN** a discovered candidate has normalized evidence that does not satisfy lifecycle score, confidence, technical confirmation, or capacity rules
- **WHEN** the discovery run completes
- **THEN** the candidate SHALL remain out of the active quant universe
- **AND** the discovery result SHALL expose the reason the candidate was not entered.

#### Scenario: Lifecycle thresholds are unchanged

- **GIVEN** the lifecycle has configured thresholds and gates
- **WHEN** discovery evidence is normalized
- **THEN** the system SHALL NOT lower lifecycle thresholds or bypass gates as part of discovery normalization.

### Requirement: Discovery Task Reports Auto Entry Diagnostics

The system SHALL report discovery-to-lifecycle entry diagnostics after a discovery task finishes.

#### Scenario: Discovery task completes with mixed outcomes

- **GIVEN** a discovery task produces candidates that are promoted, eligible, recommended-only, blocked, and skipped
- **WHEN** the task result is returned
- **THEN** the task result SHALL include counts for lifecycle attempts, promoted candidates, eligible candidates, and skipped candidates
- **AND** skipped or blocked candidates SHALL include machine-readable reasons suitable for troubleshooting.

#### Scenario: User inspects a candidate row

- **GIVEN** a user views a discovery candidate after a discovery run
- **WHEN** lifecycle evaluation has been performed for that candidate
- **THEN** the candidate row or candidate detail SHALL expose the lifecycle eligibility status, candidate score, confidence or blocking reason, and whether the candidate is already in quant.

### Requirement: Existing Historical Records Are Not Rewritten

The system SHALL apply corrected discovery lifecycle scoring to new discovery runs without requiring migration of old candidate records.

#### Scenario: Existing old records have zero scoring evidence

- **GIVEN** historical discovery candidate records exist with zero score or confidence
- **WHEN** this change is applied
- **THEN** those historical records SHALL NOT be rewritten automatically
- **AND** a subsequent discovery run SHALL produce corrected lifecycle inputs for newly generated candidate records.
