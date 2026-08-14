## Purpose

Defines how a completed Incident Package reaches Codex as an actionable GitHub Actions task, with no human copy/paste step, and what Tracy must do if that automation is ever unavailable.

## ADDED Requirements

### Requirement: Incident Package is the sole handoff contract
Tracy SHALL pass incidents to Codex only as a complete Incident Package conforming to the incident-context schema. Tracy SHALL NOT hand off free-form or partial incident data as the primary input. **Status: Planned.**

#### Scenario: Handoff payload
- **WHEN** Tracy initiates a handoff to Codex
- **THEN** the payload SHALL be a schema-conformant Incident Package, not a raw log excerpt or an ad hoc message

### Requirement: GitHub Actions is the automatic handoff mechanism
Tracy SHALL trigger Codex by calling the GitHub REST API to dispatch `.github/workflows/incident-response.yml` (via `repository_dispatch`, event type `tracy-incident`, with the Incident Package as the `client_payload`), which runs `openai/codex-action`. No developer SHALL need to manually copy incident content into Codex for this path to be considered working. **Status: Planned. External dependency: a GitHub personal access token or App credential with `repository_dispatch` permission, and `secrets.OPENAI_API_KEY` configured on the repository — neither is created by this change.**

#### Scenario: Automatic mechanism available
- **WHEN** Tracy has a complete Incident Package and GitHub Actions dispatch access is configured
- **THEN** Tracy SHALL dispatch `incident-response.yml` rather than presenting the incident for manual copy/paste, and no human action SHALL be required between detection and Codex starting its investigation

### Requirement: Documented fallback when automation is unavailable
Tracy SHALL expose the Incident Package through a clearly documented manual interface — the same workflow's `workflow_dispatch` trigger, accepting the package as a JSON input — when the `repository_dispatch` path is not configured or fails, rather than silently failing or claiming a working integration that does not exist. **Status: Planned.** This is a fallback for an unconfigured or broken automatic path, not the primary design.

#### Scenario: Automation not available
- **WHEN** GitHub Actions dispatch access is not configured
- **THEN** Tracy SHALL make the Incident Package available in the documented `workflow_dispatch` format and SHALL state plainly that handoff requires a manual trigger

### Requirement: Handoff failure is surfaced, not silent
If a handoff attempt fails, Tracy SHALL record and surface the failure rather than treating the incident as handed off. **Status: Planned.**

#### Scenario: Delivery failure
- **WHEN** Tracy attempts to hand off an Incident Package and the attempt fails
- **THEN** the incident SHALL remain marked as not-yet-handed-off, and the failure SHALL be visible to a human operator

### Requirement: Context preservation across the handoff boundary
Every field present in the Incident Package SHALL survive the handoff unchanged. The handoff mechanism SHALL NOT summarize, truncate, or drop package fields silently. **Status: Planned.**

#### Scenario: Full package received
- **WHEN** Codex receives a handed-off incident
- **THEN** every field of the original Incident Package SHALL be recoverable from what Codex received
