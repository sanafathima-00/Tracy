## Purpose

Defines how Tracy turns raw production log signals into normalized, filtered candidate incidents, so that no other capability ever has to reason about a specific logging provider's native format or an unfiltered log stream.

## ADDED Requirements

### Requirement: Read-only production access
Tracy's connection to any production log source SHALL be read-only. Tracy SHALL NOT be granted write or administrative permissions on production logging infrastructure. **Status: Planned. External dependency: the read-only IAM role must be provisioned in the GCP project.**

#### Scenario: Read-only credential configured
- **WHEN** Tracy is configured to connect to a production log source
- **THEN** the configured credential or role SHALL grant read access only, and Tracy SHALL refuse to start if it detects a write-capable credential where the platform exposes that information

### Requirement: Log source adapter boundary
Tracy SHALL access production logs through a defined log-source interface rather than coupling detection/correlation logic to a specific provider's API. **Status: Planned.**

#### Scenario: Initial adapter is GCP Cloud Logging
- **WHEN** Tracy is deployed against Google Cloud Logging
- **THEN** log retrieval SHALL go through a GCP Cloud Logging adapter implementing the same log-source interface any future provider adapter would implement

### Requirement: Streaming pipeline via Log Router and Pub/Sub
Tracy SHALL receive near-real-time log signals through a GCP Log Router sink publishing to a Pub/Sub topic, with Tracy subscribed to that topic, rather than polling the Cloud Logging API as its primary detection path. **Status: Planned. External dependency: the Log Router sink and Pub/Sub topic/subscription must be provisioned in the GCP project; not created by this change.**

#### Scenario: Streaming detection path
- **WHEN** a production service emits a log entry matching the Log Router sink's filter
- **THEN** Tracy SHALL receive it via its Pub/Sub subscription rather than by polling Cloud Logging on an interval

#### Scenario: Historical or backfill investigation
- **WHEN** Codex or Tracy needs log context from before the Pub/Sub subscription existed, or outside its retention window
- **THEN** Tracy MAY query the GCP Cloud Logging API directly for that historical range, using the same read-only credential as the streaming path

### Requirement: Filterable retrieval
Tracy SHALL support filtering retrieved logs by service, severity, and timestamp range before further processing. **Status: Planned.**

#### Scenario: Filtered query
- **WHEN** Tracy queries production logs for a detection window
- **THEN** the query SHALL be scoped by at least service, severity, and timestamp range rather than retrieving an entire unfiltered log stream

### Requirement: Normalization before analysis
Tracy SHALL convert raw log entries into a common internal representation (`LogEvent`: timestamp, service, severity, message, and a reference back to the raw entry) before any grouping or correlation logic runs, regardless of the source's native format. **Status: Planned.**

#### Scenario: Normalized fields present
- **WHEN** a raw log entry is ingested
- **THEN** it SHALL be converted to a normalized record exposing at least timestamp, service, severity, and message fields before grouping or correlation

### Requirement: Aggregation before LLM exposure
Tracy SHALL group, deduplicate, and aggregate related log entries into `ErrorCluster`s before any log content is passed to Gemini or any other LLM-based component. Tracy SHALL NOT forward a raw, unaggregated log stream to an LLM. **Status: Planned. Tracy's model is Gemini 3.6 Flash via the `google-genai` SDK — no other LLM provider or local model.**

#### Scenario: Burst of identical errors
- **WHEN** production emits many log entries sharing the same error signature within a short window
- **THEN** Tracy SHALL represent them as a single `ErrorCluster` (signature, count, first/last seen, one sample message) before any LLM-facing step runs

### Requirement: Abnormal pattern identification
Tracy SHALL identify abnormal patterns — such as error-rate spikes, new error signatures, or elevated severity — in normalized/aggregated logs, and SHALL flag them as candidate incidents. **Status: Planned.**

#### Scenario: Error-rate spike
- **WHEN** the error rate for a service exceeds its established baseline within a detection window
- **THEN** Tracy SHALL flag the window as a candidate incident for correlation and packaging
