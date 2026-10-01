# Tracy

**An AI reliability agent built around evidence, controlled action, and verification.**

Tracy's goal is to move from a production failure to an evidence-backed response: observe the incident, retrieve current context, investigate the cause, choose a safe action, obtain authorization, act, and verify what actually changed.

The repository currently implements a deterministic log-to-incident pipeline, optional Gemini analysis, structured incident packages, separate GitHub/Codex investigation and implementation workflows, and a review-feedback loop. The broader autonomous agent remains a roadmap.

## The idea

```text
OBSERVE → RETRIEVE → REASON → DECIDE → AUTHORIZE → ACT
    → RETRIEVE FRESH CONTEXT → VERIFY → RESOLVE / ESCALATE
```

In the target architecture, **Moss** supplies operational context before reasoning, before action, and after action. Local **Gemma/Ollama** and cloud models provide capabilities behind a model boundary. **Voice** provides escalation and human approval. A deterministic Tracy controller owns workflow transitions, authorization, and resolution.

**Retrieved context and confident model output are evidence inputs. They do not grant permission or prove recovery.**

## Current implementation

| Component | Behavior |
| --- | --- |
| Local ingestion | JSON log files in replay/follow mode through `LocalLogSource`. |
| Processing | Parses/normalizes events, filters credential-shaped metadata keys, deduplicates events, and groups related errors. |
| Incident detection | Deterministic thresholds: two repeated non-critical errors or one critical error; process-local in-memory state. |
| Gemini analysis | Optional summaries and hypotheses for newly detected incidents; invalid/unavailable analysis falls back to deterministic data. |
| Incident package | Pydantic/schema validation separates facts, references, hypotheses, and investigation recommendations. |
| Read-only investigation | Opt-in `tracy-investigate` dispatch runs a separate Codex workflow against source, tests, configuration, and history. |
| Implementation gate | Requires a non-empty validated root cause, a confirmed/partially confirmed hypothesis, and an `openspec` or `lightweight` planning path. |
| Implementation and PR | A separate manually invoked CLI checks the gate and dispatches `tracy-implement`; the workflow rechecks authorization before implementation, testing, and PR creation. |
| Review feedback | Bounded remediation for submitted reviews on PRs labelled `tracy-incident`. |

The implementation transition is still **manual**. `python -m tracy` does not wait for investigation completion and automatically authorize implementation.

## Current flow

```text
checkout-api → structured JSON logs → LocalLogSource
    → normalize / deduplicate / group → IncidentDetector
    → optional Gemini analysis → IncidentPackage
    → opt-in GitHub dispatch → Codex read-only investigation
    → operator supplies investigation result to implementation CLI
    → deterministic gate → implementation workflow → tests → PR
    → bounded review feedback
```

The monitored `checkout-api` is an independent FastAPI demo service. It shares a log file with Tracy; neither Python package imports the other.

## Planned architecture

| Area | Intended role | Status |
| --- | --- | --- |
| Orchestrator/state machine | Own lifecycle and deterministic transitions | Planned |
| Durable state | Preserve incidents, approvals, and execution state behind a lightweight storage interface | Planned |
| Moss | Fresh context at pre-reasoning, pre-action, and post-action boundaries | Planned |
| Model router | Local/cloud task routing with bounded retries and fallback | Planned |
| Tools and risk layer | Validate proposed actions and require appropriate approval | Planned |
| Web approval/dashboard | Incident evidence, actions, approvals, and traces | Planned |
| LiveKit/voice | Escalation and human decisions through the existing authorization path | Planned |
| Runtime verification | Fresh evidence and health checks after remediation; resolve or escalate | Planned |
| GCP ingestion | Cloud logs through the source-independent pipeline | Planned; normalization currently raises `NotImplementedError` |

These components are not wired into the runtime today. Tests before opening a PR are implemented; post-deployment recovery verification is a separate future capability. Moss supplies context, not authorization. Voice must return decisions to Tracy's authorization boundary rather than execute tools directly.

## Repository layout

```text
backend/tracy/           Ingestion, detection, Gemini, packages, dispatch, gate, CLIs
backend/tests/           Fixtures and backend tests
checkout-api/app/        Independent monitored demo service
checkout-api/tests/      Service and planted-regression tests
.github/workflows/       Investigation, implementation, review workflows
.agents/skills/          Repository investigation/implementation instructions
openspec/changes/        Proposal, design, schemas, and specifications
```

Local architecture handoff and implementation-checklist documents inform the roadmap. They are not all committed in the published repository, so this README does not depend on links to missing planning files.

## Local setup

Both packages target **Python 3.12** (`>=3.12,<3.13`). Use separate environments and the indicated working directories.

### 1. Start the demo service

From `checkout-api/`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --no-access-log > checkout-api.log
```

The service listens at `http://127.0.0.1:8000`. In another PowerShell terminal, trigger the intentional pricing regression twice:

```powershell
$body = '{"user_id":"demo-user","product_id":"prod-003","quantity":5}'
1..2 | ForEach-Object {
    try {
        Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/checkout -ContentType application/json -Body $body
    } catch {
        Write-Host "Expected checkout failure:" $_.Exception.Message
    }
}
```

`calculate_total()` divides by `remaining_stock - quantity` here. Buying exactly the remaining stock produces the planted `ZeroDivisionError`. The regression is retained as a controlled investigation scenario.

### 2. Read the logs with Tracy

From `backend/`, in a separate terminal:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -u -m tracy ../checkout-api/checkout-api.log
```

Add `--follow` to keep watching. Replay mode reads to EOF and exits. Without a Gemini key, deterministic incident data remains available.

Tracy expects UTF-8 JSON lines. Non-JSON output is skipped and counted as malformed. Older PowerShell versions that redirect to UTF-16 need an explicit UTF-8 capture method.

### 3. Optional integrations

Set variables in the launching shell. The backend does not automatically load the repository `.env` file.

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Optional Gemini analysis |
| `TRACY_GITHUB_TOKEN` | Credentials for explicitly requested dispatch |
| `TRACY_GITHUB_REPOSITORY` | Destination in `owner/repo` format |
| GitHub Actions secret `OPENAI_API_KEY` | Codex authentication in workflows |

```powershell
# Sends newly detected incident packages to the configured repository.
python -u -m tracy ../checkout-api/checkout-api.log --follow --dispatch

# Separate controlled transition using matching, schema-valid JSON files.
python -m tracy.implement_cli incident_package.json investigation_result.json
```

The implementation CLI needs matching incident IDs and JSON contracts; it does not parse an arbitrary Markdown report. GitHub Actions must have the permissions specified by the separate workflows. These workflows do not establish a production deployment or recovered service.

## Tests and verification

Run `python -m pytest -q` in each package's installed development environment.

Local validation on **October 1, 2026**:

- Backend: **173 passed**.
- Checkout API: **19 passed, 1 expected failure** for the intentionally unfixed regression.

This verifies local unit/fixture suites, not credentials, external model calls, GitHub Actions execution, voice, or the target autonomous loop in a fresh deployment.

## Reliability boundaries

- Gemini proposes hypotheses; independent investigation and structured gates control implementation.
- Investigation and implementation have separate permission boundaries.
- Metadata sanitization filters known credential-shaped keys. It is not a full detector for secrets inside messages or stack traces; sanitize real logs before dispatch.
- Incident state is lost on restart. Cross-process deduplication and durable recovery are not implemented.
- A merge, passing tests, or plausible explanation is not proof of post-deployment recovery.
- Retrieval outages, ambiguous causes, unsafe actions, and failed verification should become explicit degraded/escalated states as the planned agent is built.

## Existing demo captures

These illustrate earlier incident/PR work, not the unimplemented roadmap.

<img width="1535" height="163" alt="Existing Tracy demo capture 1" src="https://github.com/user-attachments/assets/ad634672-de14-4a91-a432-d091e7653309" />
<img width="806" height="842" alt="Existing Tracy demo capture 2" src="https://github.com/user-attachments/assets/047ee162-5efc-4018-aaaa-51e2ec2b6b9a" />
<img width="565" height="639" alt="Existing Tracy demo capture 3" src="https://github.com/user-attachments/assets/a081ea7c-5dad-4149-a981-114061072595" />
<img width="576" height="255" alt="Existing Tracy demo capture 4" src="https://github.com/user-attachments/assets/201cecc0-ba3b-4bf4-b76b-d331026fea3c" />

## Specifications

- [Proposal](openspec/changes/establish-incident-response-workflow/proposal.md)
- [Design](openspec/changes/establish-incident-response-workflow/design.md)
- [Incident package schema](openspec/changes/establish-incident-response-workflow/incident-package.schema.json)
- [Implementation gate](backend/tracy/investigation.py)
- [Workflows](.github/workflows/)

Python, Pydantic, Google GenAI SDK, FastAPI, pytest, JSON Schema, GitHub Actions, Codex, and OpenSpec form the current foundation. Moss, hybrid routing, voice, and autonomous recovery describe the next architecture rather than the current stack.
