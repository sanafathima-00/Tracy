## 1. Incident Package contract

- [x] 1.1 Publish the Incident Package JSON Schema (`incident-package.schema.json`, now v1.1 with `symptoms`, `error_clusters`, `suspected_root_cause`)
- [ ] 1.2 Once implemented, promote the schema out of the change directory and mirror it as Pydantic models

## 2. Codex-facing Skills

- [x] 2.1 `investigate-incident` — updated for the finalized stack (Postgres/Incident vs. IncidentPackage distinction, environment/Docker inspection, no-secret-exposure)
- [x] 2.2 `implement-incident-fix` — updated (pytest, GitHub Actions execution context)
- [x] 2.3 `create-incident-pr` — narrowed to first-time PR creation + initial review request; carries the `tracy-incident` label; no longer owns the remediation loop
- [x] 2.4 `review-feedback-loop` — new: consumes `pull_request_review` events on `tracy-incident`-labeled PRs, classifies findings, enforces the 3-attempt retry cap, hands remediation back to `implement-incident-fix` or reports `READY_FOR_HUMAN` / `HUMAN_ATTENTION_REQUIRED`

## 3. Claude Code entry point

- [x] 3.1 `/incident` command — thin entry point covering the full lifecycle description; automation itself lives in the Skills and GitHub Actions workflows, not in the command

## 4. GitHub Actions scaffolding

- [x] 4.1 `.github/workflows/incident-response.yml` — `repository_dispatch` (production path) and `workflow_dispatch` (manual fallback) triggers, running `openai/codex-action@v1` against `investigate-incident` → `implement-incident-fix` → `create-incident-pr`
- [x] 4.2 `.github/workflows/incident-review-feedback.yml` — `pull_request_review` trigger, running `openai/codex-action@v1` against `review-feedback-loop`
- [ ] 4.3 Once `openai/codex-action`'s `permission-profile` values are confirmed against its own docs at implementation time, set the exact profile instead of the placeholder noted in the workflow comments
- [ ] 4.4 Configure `secrets.OPENAI_API_KEY` on the repository (external — cannot be done from this change)

## 5. Distribution consistency

- [x] 5.1 All four Skills live under `.agents/skills/` as canonical, mirrored to `.claude/skills/`
- [x] 5.2 Nothing added under `.codex/` — Codex resolves `.agents/skills/` directly

## 6. Validation

- [x] 6.1 `openspec validate establish-incident-response-workflow --strict` passes
- [ ] 6.2 Once `production-log-ingestion` produces a real Incident Package via Gemini, re-validate it against `incident-package.schema.json` with actual data, not just the schema's own structural validity

## Out of Scope for This Change

The hackathon vertical slice below is the priority once implementation starts; everything else in the six specs (dashboard, historical backfill, additional log sources) is explicitly secondary. None of the following exists as code yet — see `design.md` for the Implemented/Planned/External-dependency/Not-yet-available breakdown per decision:

- FastAPI application, Pydantic models, SQLAlchemy models/Alembic migrations
- The GCP Cloud Logging / Log Router / Pub/Sub adapter and the `google-genai` Gemini client
- Postgres-backed orchestrator implementing the `DETECTED` → ... → `RESOLVED`/`FAILED` state machine
- Any GCP project, IAM role, Pub/Sub topic, or GitHub Copilot enablement (all external dependencies to provision, not build)
- Next.js/React/Tailwind dashboard
- `post-deployment-verification` implementation (depends on the ingestion pipeline existing first)
