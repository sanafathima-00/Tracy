## Context

See `proposal.md` for motivation. This version supersedes the earlier draft's placeholder integration boundaries: the technical stack and the Codex/PR-review integration mechanisms are now finalized decisions, not open questions. Section headers below are annotated **[Implemented]**, **[Planned]**, **[External dependency]**, or **[Not yet available]** so this document never implies more exists than does.

Environment facts checked before writing this revision (not assumed):
- `gcloud`, `gh`, and `codex` binaries are still not installed in this development environment. `openspec` remains reachable only via `npx @fission-ai/openspec`.
- `openai/codex-action`'s actual inputs were fetched and verified from its GitHub repository (not guessed): `openai-api-key`, `prompt`/`prompt-file`, `output-file`, `working-directory`, `permission-profile`, `codex-version`, `codex-args`, `safety-strategy`, `codex-user`, `model`, `effort`. Its documented example permissions are `contents: read`, `issues: write`, `pull-requests: write` for a review-commenting use case; our use case needs `contents: write` because Codex must push a branch.
- The Tracy repository still contains no application code. Nothing in this design has been implemented as running software — every "Implemented" tag below refers only to development-workflow artifacts (Skills, specs, workflow YAML), never to a deployed system.

## Goals / Non-Goals

**Goals:**
- Record the finalized technology stack as authoritative, so every Skill, spec, and workflow file agrees on it.
- Make the Codex-handoff and PR-review mechanisms concrete (GitHub Actions + `openai/codex-action`, GitHub Copilot automatic review) instead of the earlier placeholder interfaces, while keeping the same interface *shape* so a future adapter swap still doesn't require a spec rewrite.
- Define the entities (`LogEvent`, `ErrorCluster`, `Incident`, `IncidentPackage`) and the incident state machine precisely enough to implement against.
- Scope the first working slice tightly enough to build in ~2 hours: GCP logs → Tracy → Gemini → Incident Package → GitHub Actions → Codex → PR → Copilot → human approval.

**Non-Goals:**
- Building any of it yet in this change beyond the Skills, specs, schema, and CI workflow scaffolding. No FastAPI app, no SQLAlchemy models, no Gemini client code, no GCP subscriber exist as of this document.
- Choosing Copilot's or Codex's *internal* model — `openai/codex-action`'s `model`/`effort` inputs are left at their defaults; nothing in this task specified which OpenAI model Codex itself should run.
- A vector database, Redis, Kafka, Temporal/Celery/Airflow, LangChain/LangGraph, or an open-source LLM. All explicitly excluded from the MVP by decision, not by oversight.

## Decisions

### Technology stack **[Planned — nothing implemented yet]**
| Layer | Choice |
|---|---|
| Backend language/runtime | Python 3.12 |
| API framework | FastAPI |
| Validation | Pydantic (models mirror `incident-package.schema.json`) |
| Tracy's AI | Gemini 3.6 Flash via the official `google-genai` SDK — no LangChain/LangGraph |
| Log source | GCP Cloud Logging → GCP Log Router → Pub/Sub (streaming); GCP Cloud Logging API directly for historical/backfill queries |
| GCP SDKs | `google-cloud-logging`, `google-cloud-pubsub` |
| Database | PostgreSQL via SQLAlchemy, migrations via Alembic |
| Orchestration | FastAPI + Postgres-backed state machine — no separate workflow engine |
| Codex execution | GitHub Actions running `openai/codex-action@v1` |
| PR review | GitHub Copilot automatic code review |
| Frontend | Next.js + React + Tailwind CSS (secondary to the backend vertical slice) |
| Tests | pytest, against whatever the repository actually configures once it exists |
| Local dev | Docker + Docker Compose, services limited to Tracy API + Postgres |

**Alternatives considered:** a vector database for retrieval (rejected — no concrete retrieval problem justifies it yet, per explicit instruction); Celery/Temporal for orchestration (rejected — a Postgres-backed state machine is sufficient at this scale and avoids a second infrastructure dependency); an open-source model (rejected — explicit MVP decision to spend the build budget on the system, not model hosting).

### Entity abstractions **[Planned]**
- **`LogEvent`** — one normalized log line: `timestamp`, `service`, `severity`, `message`, `raw_ref` (a pointer back to the GCP log entry, not the full payload).
- **`ErrorCluster`** — a deduplicated group of `LogEvent`s sharing a signature: `signature`, `count`, `first_seen`, `last_seen`, `sample_message`, `severity`. This is what actually reaches Gemini — never a raw `LogEvent` stream. Mirrored directly in `incident-package.schema.json`'s `error_clusters`.
- **`Incident`** — the system-of-record row in Postgres: everything in `IncidentPackage` plus `workflow_state` (see state machine below), `codex_run_reference`, `pr_url`, `review_state`, `retry_count`, and timestamps. An `Incident` outlives any single `IncidentPackage` snapshot.
- **`IncidentPackage`** — the schema in `incident-package.schema.json`: a point-in-time, evidence-graded snapshot of an `Incident`, handed to Codex. It does not carry workflow/orchestration state — that distinction is deliberate (see Risks).

### Incident state machine **[Planned]**
Owned by Tracy's Postgres-backed orchestrator (`incident-context` capability). States: `DETECTED → CONTEXT_READY → CODEX_INVESTIGATING → FIX_IN_PROGRESS → PR_OPEN → REVIEWING ⇄ CHANGES_REQUESTED → READY_FOR_HUMAN → MERGED → VERIFYING → RESOLVED | PERSISTING | CHANGED | REGRESSED`, with `FAILED` reachable from any state. `REVIEWING ⇄ CHANGES_REQUESTED` is the only cycle, bounded (see retry limit below).

The orchestrator persists state transitions so that a crash or restart can resume from the last recorded state rather than losing an in-flight incident — this is a Postgres row update per transition, not a separate durability mechanism.

### Codex handoff: GitHub Actions, not manual-file **[Planned — supersedes the earlier "manual-file" adapter]**
The `deliver_incident(package) -> HandoffResult` interface from the prior design revision is kept, but its production adapter is now concrete: Tracy calls the GitHub REST API's `repository_dispatch` endpoint (`event_type: tracy-incident`, `client_payload: <IncidentPackage>`), which triggers `.github/workflows/incident-response.yml`. That workflow checks out the repository and runs `openai/codex-action@v1` with a prompt pointing Codex at the `investigate-incident` Skill and the incident package written to the workspace. No human copy/paste step exists in this path, satisfying the "no manual step between detection and PR review" requirement.

The `manual-file` adapter is kept as a documented fallback (and as the `workflow_dispatch` trigger on the same workflow, for local testing) for exactly the case `codex-handoff`'s spec already requires: automation unavailable → say so, don't fake it.

### PR review: GitHub Copilot, with a separate remediation workflow **[Planned]**
`request_review(pr) -> ReviewResult` is now concretely GitHub Copilot's automatic code review, enabled on the repository so every PR (and every subsequent push to it) gets reviewed without a manual request. Because Copilot's review is asynchronous and can complete well after the PR-opening Actions run has finished, remediation is a **separate** workflow (`incident-review-feedback.yml`) triggered by the `pull_request_review` event, scoped to PRs Codex opened (marked with a `tracy-incident` label by `create-incident-pr`). This runs `openai/codex-action` again, pointed at the new `review-feedback-loop` Skill, which classifies findings and either pushes a remediation commit (re-triggering Copilot) or reports `READY_FOR_HUMAN`.

### Retry limit **[Planned]**
The review ⇄ remediation cycle is capped at **3 remediation attempts** per incident (chosen as a reasonable default for a hackathon-scale system, not derived from data — revisit once real cycles are observed). The count lives on the `Incident` row (`retry_count`), not in any single Actions run's memory, since each run is stateless. `review-feedback-loop` reads the count via a marker the workflow passes in (today: a PR label `tracy-attempt-N`) and stops at `HUMAN_ATTENTION_REQUIRED` rather than looping indefinitely once the cap is hit.

### Security **[Planned, partially External dependency]**
- GCP: read-only IAM role only (**External dependency** — must be provisioned in GCP, not created by this change). No credentials are or will be committed; `GOOGLE_APPLICATION_CREDENTIALS`-style secrets are injected via environment/secret manager at deploy time.
- GitHub Actions: `secrets.OPENAI_API_KEY` is the only secret referenced by the workflow scaffolding added in this change (**External dependency** — must be configured in the repository's secrets before the workflow can run). Permissions are scoped per-workflow (`contents: write`, `pull-requests: write`, `issues: write` only where needed) rather than defaulting to broad repository permissions.
- Incident Package: no secrets, tokens, or unnecessary PII, per `incident-context`'s existing requirement — unchanged by this revision.
- Codex's investigation of "environment configuration" (Docker/deployment config) is read-only inspection for context, never a channel for exporting secret values into the Incident Package, PR description, or commit.

## Risks / Trade-offs

- **[Risk]** Conflating the `Incident` (Postgres, full lifecycle) with the `IncidentPackage` (JSON, point-in-time snapshot) would make the schema carry orchestration concerns it shouldn't. → **Mitigation**: kept as two distinct entities (see Decisions); `incident-package.schema.json` gained no `workflow_state` field in this revision.
- **[Risk]** `openai/codex-action`'s exact behavior under `permission-profile: ":workspace"` (whether it can `git push`, whether it needs a follow-up step to push) was not independently tested in this environment — only its documented inputs were verified. → **Mitigation**: workflow YAML comments flag this explicitly; treat the first real run as the verification step before trusting it unattended.
- **[Risk]** A 3-attempt retry cap is an arbitrary default, not derived from observed Copilot behavior. → **Mitigation**: stored as a single named constant in the workflow/Skill (not scattered), trivial to tune once real review cycles are observed.
- **[Risk]** Two separate GitHub Actions workflows (PR-open vs. review-feedback) must agree on how they identify "this is a Tracy incident PR" (the `tracy-incident` label). If `create-incident-pr` fails to apply it, the remediation workflow silently won't fire. → **Mitigation**: the label application is a required step in `create-incident-pr`'s instructions, not optional; call this out again in `pr-review-workflow`'s spec.
- **[Risk]** Gemini's structured-output reliability for the full Incident Package shape (nested arrays, enums) is unverified — no code has called it yet. → **Mitigation**: `schema_version` exists precisely so the schema can move without breaking every consumer at once; treat v1.1 as provisional until a real Gemini call is made against it.

## Open Questions

- Exact Postgres schema/table design for `Incident` rows — an implementation detail of `incident-context`, doesn't change any spec requirement or this design's decisions.
- Whether `openai/codex-action`'s `permission-profile` should be `:workspace` or a more specific profile once its full set of named profiles is confirmed against the action's own documentation at implementation time — doesn't change the workflow's trigger/permissions shape, safe to decide then.
