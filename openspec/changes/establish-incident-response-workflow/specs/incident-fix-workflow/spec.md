## Purpose

Defines what Codex must do with a received incident: independent investigation, choosing a planning path, implementation, testing, and opening a pull request.

## ADDED Requirements

### Requirement: Execution environment
Codex SHALL run as `openai/codex-action` inside a GitHub Actions job triggered per `codex-handoff`, on a fresh checkout of the repository for each run. Codex SHALL NOT assume any state persists from a prior run beyond what is explicitly passed to it (the Incident Package, a review's findings, or the retry count). **Status: Planned. External dependency: `secrets.OPENAI_API_KEY` configured on the repository.**

#### Scenario: Fresh run each time
- **WHEN** a new GitHub Actions run starts for an incident (initial investigation, or a later remediation cycle)
- **THEN** Codex SHALL derive everything it needs from the inputs given to that run — the Incident Package, prior investigation report, or review findings — not from memory of a previous run

### Requirement: Independent root-cause validation
Codex SHALL independently validate an incident's suspected root cause against the repository before implementing a fix. Codex SHALL NOT implement a fix solely because Tracy's Incident Package states a hypothesis. **Status: Planned.**

#### Scenario: Hypothesis rejected by investigation
- **WHEN** Codex's investigation of the repository, git history, configuration, or tests contradicts Tracy's suspected root cause
- **THEN** Codex SHALL report the discrepancy and pursue the evidence-supported cause instead of the original hypothesis

### Requirement: Minimum investigation surface
Codex's investigation SHALL include, at minimum, the relevant code and tests, recent git history touching the affected area, any existing documentation (README, docs/, OpenSpec specs) for the affected capability, and — where safely available — environment/deployment configuration such as Docker or CI configuration relevant to the affected service. **Status: Planned.**

#### Scenario: Minimum investigation performed
- **WHEN** Codex investigates an incident
- **THEN** the investigation record SHALL show that code, git history, existing documentation, and relevant environment/deployment configuration for the affected area were each checked, or SHALL state why one was not applicable

### Requirement: No secret exposure during environment inspection
When Codex inspects Docker, deployment, or environment configuration, it SHALL NOT copy secret values (API keys, credentials, tokens) into the investigation report, commit messages, or the PR description — only the fact that a variable exists and, where relevant, its non-secret shape. **Status: Planned.**

#### Scenario: Config file contains a secret
- **WHEN** Codex reads a configuration file that contains a real credential value
- **THEN** its investigation report and any commit/PR text SHALL reference the variable name only, never the value

### Requirement: Planning path selection
Codex SHALL use the existing OpenSpec workflow to plan a fix when the change affects documented behavior, spans multiple components, or is otherwise a meaningful production change. Codex MAY use a lightweight investigate-then-implement path for small, localized fixes that touch no documented requirement. **Status: Planned.** OpenSpec remains Tracy's only planning layer — this requirement does not introduce, and none of this change introduces, a second planning framework.

#### Scenario: Meaningful change uses OpenSpec
- **WHEN** a fix would change behavior described by an existing spec, or touches multiple components
- **THEN** Codex SHALL create or update an OpenSpec change — proposal, design, tasks, and delta specs as needed — before implementing

#### Scenario: Small fix skips OpenSpec
- **WHEN** a fix is a small, localized correction that changes no documented requirement, such as a null check, a configuration value, or a query typo
- **THEN** Codex MAY implement and test it directly without creating an OpenSpec change, but SHALL still record what was investigated and why

### Requirement: Regression test required
Every incident fix SHALL include a test that fails without the fix and passes with it, unless Codex records an explicit reason why the failure cannot be reproduced in tests. Tests SHALL run through pytest and whatever test configuration the repository actually establishes — Codex SHALL NOT invent a test command the repository doesn't define. **Status: Planned.**

#### Scenario: Fix without a feasible test
- **WHEN** a fix cannot be covered by a feasible automated test, such as one depending on external infrastructure state
- **THEN** Codex SHALL document why in the PR description rather than silently omitting test coverage

### Requirement: Isolated implementation
Codex SHALL implement the fix on an isolated branch or worktree and SHALL NOT commit directly to the repository's main branch. **Status: Planned.**

#### Scenario: Branch created
- **WHEN** Codex begins implementing a fix
- **THEN** the work SHALL happen on a dedicated branch or worktree distinct from the main branch

### Requirement: Self-review before PR
Codex SHALL review its own diff against the investigation findings before opening a PR, confirming the implementation matches the validated root cause and does not exceed the incident's scope. **Status: Planned.**

#### Scenario: Scope check
- **WHEN** Codex finishes implementing a fix
- **THEN** it SHALL confirm the diff addresses the validated root cause, and SHALL flag rather than silently include any change outside that scope
