## Purpose

Defines how a candidate incident becomes a structured, evidence-graded Incident Package and a human-readable summary — the contract every downstream consumer of an incident relies on.

## ADDED Requirements

### Requirement: Incident Package schema conformance
Every incident Tracy produces SHALL be represented as an Incident Package conforming to a single documented schema, regardless of what triggered detection. **Status: Planned.** The schema is `incident-package.schema.json` in this change; Gemini 3.6 Flash (via `google-genai`) SHALL be the component responsible for producing this structured output from aggregated evidence — no other model or hand-rolled parser is the source of truth for it.

#### Scenario: Schema conformance
- **WHEN** Tracy produces an Incident Package
- **THEN** it SHALL validate against the documented Incident Package schema before being considered complete

### Requirement: Incident is the system of record; the package is a snapshot
Tracy SHALL persist each incident as an `Incident` row (in PostgreSQL, via SQLAlchemy/Alembic) that outlives any single Incident Package, and SHALL track that incident's workflow state on the row rather than inside the package. **Status: Planned.**

#### Scenario: Package regenerated mid-workflow
- **WHEN** new evidence arrives for an incident already being investigated
- **THEN** Tracy SHALL be able to produce an updated Incident Package referencing the same `incident_id`, without losing the `Incident` row's accumulated workflow state (Codex run reference, PR URL, review state, retry count)

### Requirement: Resumable workflow state
The `Incident` row's workflow state SHALL be persisted on every transition, so that a restart or crash of Tracy's orchestrator can resume from the last recorded state rather than losing track of an in-flight incident. **Status: Planned.**

#### Scenario: Orchestrator restarts mid-incident
- **WHEN** Tracy's orchestrator process restarts while an incident is in any state other than a terminal one (`RESOLVED`, `FAILED`, etc.)
- **THEN** it SHALL resume that incident from its last persisted state rather than re-detecting it from scratch or losing it

### Requirement: Evidence tiering
The Incident Package SHALL distinguish observed facts (directly evidenced by logs), correlations (related in time or context but not proven causal), and hypotheses (Tracy's suspected root cause). Tracy SHALL NOT present a hypothesis as an observed fact. **Status: Planned.** The package's `suspected_root_cause` convenience field SHALL always mirror the highest-confidence entry in `hypotheses` — it SHALL NOT introduce a claim absent from that array.

#### Scenario: Suspected cause is a hypothesis
- **WHEN** Tracy suspects a deployment caused an incident based on timing alone
- **THEN** that suspicion SHALL be recorded under hypotheses with a confidence value, not under observed facts

### Requirement: Confidence required on hypotheses
Every hypothesis in the Incident Package SHALL carry an explicit confidence value. Tracy SHALL NOT emit a hypothesis without one. **Status: Planned.**

#### Scenario: Insufficient evidence for confidence
- **WHEN** Tracy cannot establish any basis for confidence in a candidate root cause
- **THEN** Tracy SHALL either omit that hypothesis or mark its confidence as low/unknown rather than fabricating a numeric value

### Requirement: Human-readable incident summary
Tracy SHALL produce a human-readable summary of every incident, derived from the same evidence as the Incident Package, understandable without reading raw logs. **Status: Planned.** This summary and the package's `symptoms` and `error_clusters` fields together SHALL give Codex enough evidence to begin investigating without the developer manually pasting logs.

#### Scenario: Developer-facing summary
- **WHEN** an incident is detected
- **THEN** Tracy SHALL produce a summary including at minimum the affected service, start time, impact, primary error, and current assessment with its confidence

#### Scenario: Enough evidence for Codex without manual log pasting
- **WHEN** an Incident Package is handed to Codex
- **THEN** its `symptoms`, `error_clusters`, `observed_facts`, and `log_references` SHALL be sufficient for `investigate-incident` to begin its investigation without a human supplying additional raw log content

### Requirement: No secrets or unnecessary PII in the package
The Incident Package SHALL NOT contain secrets, access tokens, passwords, private keys, or unnecessary PII, even where such values appear in raw log entries. **Status: Planned.** Codex SHALL be given the minimum context necessary to investigate — this requirement applies equally to what Tracy puts in the package and to what any Skill passes onward into a PR description or commit message.

#### Scenario: Log entry contains a credential
- **WHEN** a raw log entry Tracy ingests contains what appears to be a secret or credential value
- **THEN** that value SHALL be redacted or excluded before it can reach the Incident Package or any downstream consumer

### Requirement: Severity classification
Tracy SHALL assign each incident a severity level drawn from a documented, consistent scale (`critical`, `high`, `medium`, `low` — see `incident-package.schema.json`). **Status: Planned.**

#### Scenario: Severity present
- **WHEN** an Incident Package is produced
- **THEN** it SHALL include a severity field drawn from Tracy's documented severity scale
