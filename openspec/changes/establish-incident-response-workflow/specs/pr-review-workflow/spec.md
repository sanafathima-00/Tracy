## Purpose

Defines the review stage between PR creation and human approval: GitHub Copilot's automatic code review as the concrete mechanism, how findings are consumed, and how the review-remediation loop stays bounded.

## ADDED Requirements

### Requirement: Review is required; GitHub Copilot is the concrete mechanism
Every incident-fix PR SHALL go through an automated review stage before human approval. GitHub Copilot's automatic code review is the concrete mechanism, enabled at the repository level so it reviews the PR on open and on every subsequent push. The review is requested/consumed through a stable interface so a different reviewer could be substituted later without changing this requirement. **Status: Planned. External dependency: GitHub Copilot code review must be enabled on the repository — not configured by this change.**

#### Scenario: Reviewer swapped
- **WHEN** the configured automated review mechanism changes
- **THEN** the PR review workflow SHALL continue to function against the same request/result interface, without requiring changes to the incident-fix-workflow or human-approval requirements

#### Scenario: Copilot reviews every push
- **WHEN** Codex pushes a remediation commit to an open incident-fix PR
- **THEN** Copilot SHALL review the updated PR again without a human having to request that review manually

### Requirement: Incident PRs are identifiable
Every PR opened by `create-incident-pr` SHALL carry a `tracy-incident` label (or equivalent marker) so the review-feedback workflow can distinguish it from PRs opened by humans, and SHALL NOT act on a PR lacking that marker. **Status: Planned.**

#### Scenario: Human-authored PR ignored
- **WHEN** a `pull_request_review` event fires on a PR that does not carry the `tracy-incident` marker
- **THEN** the review-feedback workflow SHALL take no action on it

### Requirement: Blocking vs. non-blocking findings
Review findings SHALL be classified as blocking (must be resolved before human approval can be requested) or non-blocking (informational). Human approval SHALL NOT be requested while a blocking finding is unresolved. **Status: Planned.**

#### Scenario: Blocking finding present
- **WHEN** an automated review returns at least one blocking finding
- **THEN** the PR SHALL be routed back to Codex for a fix, not to human approval

### Requirement: Codex consumes review findings directly
Codex SHALL be able to read automated review findings and update the PR in response, without requiring a human to relay the findings manually. **Status: Planned.**

#### Scenario: Findings addressed
- **WHEN** Codex receives blocking review findings
- **THEN** Codex SHALL update the same PR/branch to address them and resubmit for review, rather than opening an unrelated new PR

### Requirement: Bounded remediation loop
The review-remediation cycle SHALL be capped at a fixed number of attempts (3, by default) tracked per incident. If the cap is reached while blocking findings remain, the incident SHALL move to a `FAILED`/`HUMAN_ATTENTION_REQUIRED` state instead of looping again, and a human SHALL be notified. **Status: Planned.**

#### Scenario: Retry limit exceeded
- **WHEN** the remediation loop has already attempted the configured maximum number of fixes for an incident and a blocking finding still remains
- **THEN** the incident SHALL transition to `HUMAN_ATTENTION_REQUIRED` rather than triggering another remediation attempt

#### Scenario: Retry limit not yet reached
- **WHEN** blocking findings remain but fewer remediation attempts have been made than the configured maximum
- **THEN** Codex SHALL be given another attempt before the incident is escalated

### Requirement: Review mechanism has no merge authority
The automated review mechanism SHALL be able to comment on and evaluate a PR but SHALL NOT have authority to merge it. **Status: Planned.**

#### Scenario: Clean review
- **WHEN** an automated review finds no blocking issues
- **THEN** the PR SHALL move to human approval, not directly to merge
