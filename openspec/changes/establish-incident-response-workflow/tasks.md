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

## 9. Gemini intelligence (Phase 4)

- [x] 9.1 `GeminiIncidentAnalysis`/`Hypothesis` Pydantic models (`backend/tracy/gemini.py`, not `models.py` — this is the parsed shape of an external API's response, not a pipeline-internal type like `LogEvent`/`ErrorCluster`/`Incident`). Deliberately omits `severity`, `incident_id`, `suspected_root_cause`, `confidence_overall`, `relevant_commit`/`relevant_files`, `deployment_information`, and `incident_title` — the first group is Tracy-owned deterministic data Gemini must never override, the middle two are meant to be derived later from `hypotheses` (max-confidence entry) rather than asked of Gemini as separate fields it could self-contradict against, and `incident_title` has no slot in `incident-package.schema.json`. `Hypothesis.confidence` is constrained `0.0 <= confidence <= 1.0` via Pydantic.
- [x] 9.2 `GeminiClient` (`backend/tracy/gemini.py`) — single-shot, synchronous wrapper around `google-genai`'s `client.models.generate_content(..., response_mime_type="application/json", response_schema=GeminiIncidentAnalysis)`, consuming `response.parsed`. Dependency-injectable (`GeminiClient(client=...)`) for tests; no agent/session/tool-calling concepts.
- [x] 9.3 Bounded input payload (`build_prompt`): exactly the `Incident` plus **one** representative `LogEvent` — never the full log stream, never every matching event. Stack trace capped at 2000 chars (tail-preserving truncation), messages capped at 500 chars.
- [x] 9.4 Bounded retries (max 3 attempts, 1s/2s backoff) for rate-limit/5xx/network errors only; missing/invalid API key and malformed structured output are treated as non-retryable. A Gemini failure of any kind returns `None` and is logged safely — the deterministic `Incident` `IncidentDetector` already produced remains completely unaffected.
- [x] 9.5 `backend/tracy/__main__.py` calls `GeminiClient.analyze()` only when `IncidentDetector.check()` returns `is_new=True` — never on repeat occurrences of an already-detected incident, both to avoid alert spam and to conserve free-tier quota. Prints `[AI analysis unavailable]` on failure, the parsed analysis on success.
- [x] 9.6 `google-genai` added to `backend/pyproject.toml` — the only new dependency this phase; no LangChain/LangGraph/tenacity/python-dotenv/vector DB/agent framework introduced. 22 new tests in `backend/tests/test_gemini.py` (80 total, up from 58), all using a fake injected client — no network access or real API key required by the normal test suite.
- [ ] 9.7 Full `IncidentPackage` assembly (merging Tracy-owned fields — `error_clusters`, `timeline`, `impact.metric`/`value`, `deployment_information.version` — with Gemini's output into one schema-conformant object) — deferred; this phase produces `GeminiIncidentAnalysis` only, not the assembled package. `IncidentPackage` itself still has no Pydantic model (see `§1.2`).
- [ ] 9.8 `correlated_events[]`, `related_incident_ids[]`, `deployment_information.deployed_at`/`commit`, `relevant_commit`/`relevant_files`, `documentation_context[]` — still deferred; no evidence source for any of these exists yet (no git access, no deploy pipeline metadata, no post-deployment-verification loop), and Gemini's output model was deliberately built without slots for them so it cannot invent values to fill them.
- [ ] 9.9 Live Gemini API test — deferred to a manual, human-run smoke test outside the normal `pytest` suite; not part of CI/default test collection.

## Out of Scope for This Change

The hackathon vertical slice below is the priority once implementation starts; everything else in the six specs (dashboard, historical backfill, additional log sources) is explicitly secondary. None of the following exists as code yet — see `design.md` for the Implemented/Planned/External-dependency/Not-yet-available breakdown per decision:

- FastAPI application, SQLAlchemy models/Alembic migrations (the ingestion-side Pydantic models, `LogEvent`/`ErrorCluster`, now exist — see §7.1)
- The GCP Cloud Logging / Log Router / Pub/Sub adapter (the `google-genai` Gemini client now exists — see §9)
- Postgres-backed orchestrator implementing the `DETECTED` → ... → `RESOLVED`/`FAILED` state machine
- Any GCP project, IAM role, Pub/Sub topic, or GitHub Copilot enablement (all external dependencies to provision, not build)
- Next.js/React/Tailwind dashboard
- `post-deployment-verification` implementation (depends on the ingestion pipeline existing first)
