## Why

Tracy's product concept spans production observability, an autonomous coding agent, PR review, and human approval — four different systems that must agree on a contract before any of them can be built. Writing that contract down now, spec-first, prevents Tracy's log-ingestion side and Codex's fix-implementation side from being built against different assumptions about what an "incident" is, what evidence backs it, and where each system's authority ends.

## What Changes

- Define requirements for the full incident-to-resolution loop, as six capabilities (below), covering what each stage must guarantee — not how it is implemented.
- Establish that the loop is agent-driven but never fully autonomous: every stage that changes the repository or production goes through Codex's own investigation (never blind trust of Tracy's hypothesis) and every merge requires human approval.
- Establish the Incident Package as the sole handoff contract between Tracy and Codex, with an explicit facts/correlations/hypotheses/confidence separation so guesses are never presented as evidence.
- **Finalize the technology stack and integration mechanisms** (superseding the earlier placeholder-interface approach): Python 3.12 + FastAPI + Pydantic backend, Gemini 3.6 Flash (`google-genai`) as Tracy's model, GCP Cloud Logging → Log Router → Pub/Sub as the log pipeline, PostgreSQL + SQLAlchemy + Alembic as Tracy's state store and orchestrator, GitHub Actions running `openai/codex-action` as the Codex-handoff mechanism, and GitHub Copilot automatic review as the PR-review mechanism. No Redis, Kafka, Temporal/Celery/Airflow, vector database, LangChain/LangGraph, or open-source model.
- Remove the "no automatic handoff exists yet" caveat from `codex-handoff`: with GitHub Actions as the trigger, the loop from incident detection through PR review requires no human copy/paste step. Human involvement starts at `READY_FOR_HUMAN`.
- Add a bounded review-remediation loop (`REVIEWING ⇄ CHANGES_REQUESTED`, capped at 3 attempts) with an explicit `FAILED`/`HUMAN_ATTENTION_REQUIRED` escape hatch, and a fourth post-deployment outcome, `REGRESSED`, alongside resolved/persisting/changed.
- Scope this change's actual *implementation* to the agent-development workflow only — Skills, specs, the Incident Package schema, and CI workflow scaffolding. No GCP client, Postgres models, Gemini client, or application code are written here; see `design.md` for exactly what's tagged Implemented vs. Planned vs. External dependency vs. Not yet available.

## Capabilities

### New Capabilities
- `production-log-ingestion`: reading, filtering, normalizing, and grouping production log signals (initially GCP Cloud Logging) into candidate incidents, without shipping raw logs downstream unfiltered.
- `incident-context`: turning a candidate incident into a structured, evidence-graded Incident Package with a human-readable summary — the facts/correlations/hypotheses/confidence contract.
- `codex-handoff`: how an Incident Package reaches Codex as a task, including what happens when automatic handoff isn't available.
- `incident-fix-workflow`: what Codex does with a received incident — independent investigation, the OpenSpec-or-lightweight planning decision, implementation, testing, and PR creation.
- `pr-review-workflow`: the review stage between PR creation and human approval, including how Codex consumes review findings and where the review mechanism itself is pluggable.
- `post-deployment-verification`: how Tracy re-observes production after a merge and decides whether the incident resolved, persisted, or changed shape.

### Modified Capabilities
(none — this is the first set of specs for Tracy)

## Impact

- **New**: `openspec/specs/{production-log-ingestion,incident-context,codex-handoff,incident-fix-workflow,pr-review-workflow,post-deployment-verification}/spec.md`.
- **New**: four Codex-facing Skills under `.agents/skills/` (`investigate-incident`, `implement-incident-fix`, `create-incident-pr`, `review-feedback-loop`), mirrored to `.claude/skills/`; a thin Claude Code command entry point (`/incident`).
- **New**: `.github/workflows/incident-response.yml` and `.github/workflows/incident-review-feedback.yml`, scaffolding the GitHub Actions side of the Codex-handoff and review-remediation mechanisms, referencing `secrets.OPENAI_API_KEY` only (no credentials fabricated or committed).
- **Not touched**: no application code exists yet, so none is changed. No production credentials, GCP project, GitHub secret values, or Copilot configuration are created by this change — only the interfaces and scaffolding that will consume them once provisioned.
