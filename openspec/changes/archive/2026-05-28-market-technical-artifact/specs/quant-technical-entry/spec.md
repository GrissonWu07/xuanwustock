## MODIFIED Requirements

### Requirement: Prepared Discovery Persistence

The system SHALL persist discovery candidates after行情 refresh and technical
indicator preparation before automatic lifecycle ingestion.

The persisted prepared candidate record SHALL include:

- stock identity and source audit metadata,
- effective snapshot/checkpoint time,
- artifact reference for the refreshed market and technical fields,
- technical readiness status and missing-field diagnostics,
- quant technical entry score, technical confidence, and score breakdown when
  evaluation has run.

The persisted prepared candidate record SHALL NOT be the authoritative store for
full refreshed price and technical indicator fields after the unified market
technical artifact exists. Full market and technical fields SHALL be read from
the referenced artifact.

Raw selector output, file cache, runtime latest snapshot, provider cache, or
candidate-event payload fields SHALL NOT be the authoritative business source
for discover API rows or lifecycle entry decisions after a discovery task
completes. Provider or行情 caches MAY be used only to accelerate market-data
retrieval before persisting the artifact and prepared candidate record.

#### Scenario: Discovery task writes artifact reference before ingestion

- **GIVEN** a discovery task returns raw candidate stocks
- **WHEN** the task refreshes行情 and technical indicators
- **THEN** the system SHALL persist a market technical artifact for the
  candidate's effective checkpoint
- **AND** the prepared candidate row SHALL persist an artifact reference
- **AND** lifecycle ingestion SHALL read technical facts through that artifact
  reference
- **AND** it SHALL NOT depend on raw selector cache, runtime latest snapshot, or
  candidate-event payload technical fields as the business source of truth.

#### Scenario: Failed technical preparation is persisted as blocked evidence

- **GIVEN** a discovery candidate cannot obtain a ready technical artifact
- **WHEN** the discovery task completes
- **THEN** the system SHALL persist the candidate with technical readiness
  failure diagnostics
- **AND** automatic lifecycle entry SHALL block the candidate with a
  technical-data reason.

#### Scenario: Candidate event payload is not authoritative technical evidence

- **GIVEN** a candidate event payload contains copied market or technical fields
- **AND** the candidate event also contains an artifact reference
- **WHEN** lifecycle ingestion evaluates the candidate
- **THEN** the system SHALL read technical facts from the referenced artifact
- **AND** it SHALL NOT treat copied payload market or technical fields as the
  authoritative evidence.

#### Scenario: Missing artifact reference blocks lifecycle ingestion

- **GIVEN** a prepared candidate or candidate event lacks an artifact reference
- **WHEN** lifecycle ingestion evaluates the candidate
- **THEN** the system SHALL block automatic lifecycle entry with
  `missing_artifact_reference`
- **AND** it SHALL NOT use runtime latest snapshot or provider cache as a
  substitute.
