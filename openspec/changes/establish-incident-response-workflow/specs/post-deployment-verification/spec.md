## Purpose

Defines how Tracy re-observes production after a merged fix deploys, and how it decides whether the original incident actually resolved.

## ADDED Requirements

### Requirement: Verification triggered by deployment
WHEN a fix produced by the incident-fix-workflow is deployed, Tracy SHALL re-observe the production signals associated with the original incident, via the same GCP Log Router / Pub/Sub pipeline used for initial detection. **Status: Planned.**

#### Scenario: Post-merge observation begins
- **WHEN** a PR linked to an incident is merged and deployed
- **THEN** Tracy SHALL begin observing the same service and error signature that defined the original incident

### Requirement: Four-way resolution outcome
Tracy SHALL classify the post-deployment state as one of: `RESOLVED`, `PERSISTING`, `CHANGED`, or `REGRESSED`. Tracy SHALL NOT collapse these into a single ambiguous "not resolved" state. **Status: Planned.**
- `PERSISTING`: the original error signature continues essentially unchanged.
- `CHANGED`: the original signature stopped, but a new, different symptom appeared in the same area, without evidence tying it specifically to the deployed fix.
- `REGRESSED`: evidence (deployment timing plus the specific files/paths the fix touched) ties a new problem directly to the fix itself, distinct from a merely coincidental `CHANGED` outcome.

#### Scenario: Symptoms changed without a clear link to the fix
- **WHEN** the original error pattern stops but a new, unrelated-looking error pattern appears in the same service shortly after deployment, with no evidence tying it to the files the fix touched
- **THEN** Tracy SHALL classify the outcome as `CHANGED`, not `RESOLVED` or `REGRESSED`

#### Scenario: New failure traced to the fix itself
- **WHEN** a new error signature appears immediately after deployment, in code paths the fix modified
- **THEN** Tracy SHALL classify the outcome as `REGRESSED`, and the follow-up Incident Package SHALL name the fix's own PR/commit as a correlated event

### Requirement: Evidence-based verification
Tracy SHALL base the `RESOLVED`/`PERSISTING`/`CHANGED`/`REGRESSED` determination on observed production signals, not solely on elapsed time since deployment. **Status: Planned.**

#### Scenario: Quiet period without enough evidence
- **WHEN** no new errors occur for the affected service after deployment, but Tracy has not yet observed a full comparable traffic window
- **THEN** Tracy SHALL avoid declaring the incident resolved until it has enough comparable observation to support that conclusion, and SHALL report verification as still in progress

### Requirement: Verification closes the loop
The verification outcome SHALL be recorded against the original `Incident` row's workflow state. A `PERSISTING`, `CHANGED`, or `REGRESSED` outcome SHALL be capable of starting a new incident-fix-workflow cycle that references the original incident via `related_incident_ids`. **Status: Planned.**

#### Scenario: Fix incomplete
- **WHEN** verification determines the incident is `PERSISTING`
- **THEN** Tracy SHALL be able to produce a follow-up Incident Package that references the original incident and the attempted fix

#### Scenario: Fix caused a regression
- **WHEN** verification determines the incident `REGRESSED`
- **THEN** Tracy SHALL produce a follow-up Incident Package treating the regression as its own new incident, referencing the original via `related_incident_ids`
