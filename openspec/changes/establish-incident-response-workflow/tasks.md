## 1. Incident Package contract

- [x] 1.1 Publish the Incident Package JSON Schema (`incident-package.schema.json`, now v1.1 with `symptoms`, `error_clusters`, `suspected_root_cause`)
- [ ] 1.2 Once implemented, promote the schema out of the change directory and mirror it as Pydantic models (`LogEvent`/`ErrorCluster`, the ingestion-side building blocks of this schema's `error_clusters`, now exist at `backend/tracy/models.py` — see §7. The `IncidentPackage` model itself, one layer up, is still not implemented.)

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

## 7. Local log ingestion (Phase 2)

- [x] 7.1 `LogEvent` and `ErrorCluster` Pydantic models (`backend/tracy/models.py`) — extends design.md's original sketch with `event_id` (dedup) and `source` (multi-source support); `ErrorCluster`'s fields match `incident-package.schema.json`'s `error_clusters[]` shape exactly
- [x] 7.2 `LogSource` abstraction + `RawRecord` envelope (`backend/tracy/ingestion/base.py`) — the "log source adapter boundary" `production-log-ingestion` requires; no GCP-specific concepts in it
- [x] 7.3 `LocalLogSource` (`backend/tracy/ingestion/local.py`) — replay mode (deterministic, tests) and follow mode (tails a file checkout-api's stdout is redirected into, like `tail -f`); does not spawn checkout-api and does not require checkout-api to know Tracy exists
- [x] 7.4 Pipeline (`backend/tracy/ingestion/pipeline.py`): parse → normalize → sanitize → construct `LogEvent` → deduplicate → cluster into `ErrorCluster`, satisfying `production-log-ingestion`'s normalization-before-analysis and aggregation-before-LLM-exposure requirements and `incident-context`'s no-secrets requirement (independently of checkout-api's own sanitization)
- [x] 7.5 Local demo runner (`backend/tracy/__main__.py`) and 44 passing tests, including an end-to-end test against a fixture and live verification against the real checkout-api regression (repeated triggers correctly increment one `ErrorCluster`'s count)
- [ ] 7.6 `GCPLogSource` — deferred; the interface (7.2) and the pipeline's `_normalize` dispatch point are already shaped to support it, but no `google-cloud-*` code exists yet

## 8. Deterministic incident detection (Phase 3)

- [x] 8.1 `Incident`/`IncidentSeverity` Pydantic models added to `backend/tracy/models.py` (not a new models package) — a deliberately small subset of `design.md`'s eventual Postgres `Incident` row and of `incident-package.schema.json`'s full `IncidentPackage`; every Gemini-authored field (summary, impact, hypotheses, suspected_root_cause, recommended_investigation, etc.) is absent on purpose, to be added later as additive fields on this same model, not a replacement class
- [x] 8.2 `IncidentDetector`/`IncidentStore` (`backend/tracy/detection.py`) — consumes the existing `PipelineResult`, never modifies `Pipeline`/`ErrorCluster`/`LogEvent`. Deterministic rules only: repeated identical error (`cluster.count >= 2`) and immediate critical error (`count >= 1`), satisfying `production-log-ingestion`'s existing "Burst of identical errors" scenario — no new spec requirement needed
- [x] 8.3 Deterministic log-severity -> incident-severity mapping (`detection.map_severity`), resolving a previously-undocumented mismatch: `ErrorCluster.severity` uses the log scale (`CRITICAL`/`ERROR`/...) while `incident-package.schema.json`'s `error_clusters[].severity` uses the business-impact scale (`critical`/`high`/...); `design.md`'s claim that `ErrorCluster` is "mirrored directly" into the schema is not literally true for this field and should be read with that caveat until the schema/model are reconciled
- [x] 8.4 In-memory `IncidentStore` keyed by `ErrorCluster.signature`, one Incident per qualifying signature — duplicate-incident prevention verified by test (repeated occurrences update the existing Incident's cluster snapshot rather than creating a new one; `incident_id` is generated once and never changes)
- [x] 8.5 Affected-service/environment identification sourced from the triggering `LogEvent` (`service`, `environment`, `metadata["endpoint"]`), never parsed from `ErrorCluster.signature`, which does not expose those as structured fields
- [x] 8.6 `backend/tracy/__main__.py` updated to call the detector after `pipeline.process()` and print an `[INCIDENT]` line only on first detection, not on every repeat occurrence; 14 new tests in `backend/tests/test_detection.py` (58 total, up from 44), including an end-to-end run against the existing fixture
- [ ] 8.7 Statistical/rate-based error-rate detection, historical baseline comparison, and any anomaly detection beyond fixed count thresholds — deferred. checkout-api's demo produces no meaningful traffic volume or history to derive a real baseline from; building one would mean inventing telemetry rather than detecting a real pattern
- [ ] 8.8 Semantic/multi-signature incident correlation (grouping *different* signatures into one incident) — deferred to Gemini/`incident-context`, per this change's own scope split; Phase 3 keeps one signature = one incident, no embeddings or similarity search
- [ ] 8.9 PostgreSQL-backed `Incident` persistence and the full `DETECTED -> ... -> RESOLVED`/`FAILED` workflow state machine — still deferred, unchanged from `§7`'s and `design.md`'s existing scope; the in-memory `IncidentStore` added here is not a replacement for it, and Phase 3's `Incident` model intentionally omits a `state` field since no code yet exists that could ever transition it

## Out of Scope for This Change

The hackathon vertical slice below is the priority once implementation starts; everything else in the six specs (dashboard, historical backfill, additional log sources) is explicitly secondary. None of the following exists as code yet — see `design.md` for the Implemented/Planned/External-dependency/Not-yet-available breakdown per decision:

- FastAPI application, SQLAlchemy models/Alembic migrations (the ingestion-side Pydantic models, `LogEvent`/`ErrorCluster`, now exist — see §7.1)
- The GCP Cloud Logging / Log Router / Pub/Sub adapter and the `google-genai` Gemini client
- Postgres-backed orchestrator implementing the `DETECTED` → ... → `RESOLVED`/`FAILED` state machine
- Any GCP project, IAM role, Pub/Sub topic, or GitHub Copilot enablement (all external dependencies to provision, not build)
- Next.js/React/Tailwind dashboard
- `post-deployment-verification` implementation (depends on the ingestion pipeline existing first)
