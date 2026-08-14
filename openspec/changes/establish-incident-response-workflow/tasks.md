## 1. Incident Package contract

- [x] 1.1 Publish the Incident Package JSON Schema (`incident-package.schema.json`, now v1.1 with `symptoms`, `error_clusters`, `suspected_root_cause`)
- [ ] 1.2 Promote the schema out of the change directory once this change is archived — not done yet, still lives at `openspec/changes/establish-incident-response-workflow/incident-package.schema.json`. Pydantic models now mirror it fully: `LogEvent`/`ErrorCluster` (`backend/tracy/models.py`, see §7) feed `IncidentPackage` (`backend/tracy/incident_package.py`, see §10), which is validated both by Pydantic at construction and, in tests, against the JSON Schema itself via `jsonschema.validate()` — not Pydantic validation alone.

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
- [x] 9.9 Live Gemini API test — performed once, manually, outside the normal `pytest` suite (not part of CI/default test collection): a real `GEMINI_API_KEY` was supplied, and one live call succeeded end-to-end (API key → Gemini → structured response → Pydantic parsing), returning an accurate, evidence-grounded hypothesis for the real checkout-api regression. Not repeated since; this is not an automated regression check.

## 10. Incident Package + human-readable incident (Phase 5)

- [x] 10.1 `IncidentPackage` and its nested schema-shaped models (`ImpactInfo`, `PackageErrorCluster`, `EvidenceRef`, `ObservedFact`, `CorrelatedEvent`, `TimelineEvent`, `DeploymentInfo`) added in a new `backend/tracy/incident_package.py`, not `models.py` or `gemini.py` — this is the final assembled artifact, a third kind of thing distinct from both the pipeline-internal types (§7/§8) and Gemini's own response shape (§9). Reuses `IncidentSeverity` (`models.py`) and `Hypothesis` (`gemini.py`) directly rather than duplicating them. `PackageErrorCluster` is deliberately its own small model, not a reuse of `ErrorCluster`: the schema's `error_clusters[].severity` uses the business scale, `ErrorCluster.severity` uses the log scale (see §8.3) — reusing `ErrorCluster` verbatim would have put a log-scale value into a field the schema types as the business scale.
- [x] 10.2 `IncidentPackage` matches `incident-package.schema.json` field-for-field: same names, nesting, required fields, enums, and the exact existing `schema_version: "1.1"` contract — not changed, not re-versioned. Verified with real JSON Schema validation (`jsonschema.validate()` against the actual schema file, not just Pydantic construction) in both the with-Gemini and without-Gemini (degraded) cases.
- [x] 10.3 `IncidentPackage.to_schema_dict()` (`model_dump(mode="json", exclude_none=True)`) — the schema declares every optional field with a plain, non-nullable JSON type, so an absent value is omitted entirely, never emitted as `null`; verified by test.
- [x] 10.4 `IncidentPackageBuilder.build(incident, event, analysis)` — deterministic except for consuming an already-produced `GeminiIncidentAnalysis | None`; never calls Gemini itself. Tracy-owned fields (`severity`, `service`, `environment`, `affected_component`, `error_clusters`, `impact.metric`/`value`, `timeline`, `observed_facts`, `log_references`, `deployment_information.version`) are read only from `Incident`/`LogEvent`/`ErrorCluster`; Gemini-owned fields (`impact.description`, `symptoms`, `hypotheses`, `recommended_investigation`, part of `summary`) are copied verbatim from `analysis` when present. `confidence_overall`/`suspected_root_cause` are derived from `max(hypotheses, key=confidence)`, never asked of Gemini as separate fields (extends the same principle `gemini.py` already established for why those fields don't exist on `GeminiIncidentAnalysis`).
- [x] 10.5 `summary`'s first sentence is a deterministic, Tracy-generated statement of fact (e.g. "checkout-api checkout requests are failing with ZeroDivisionError.") — not a new `title` field, since the schema has none; Gemini's own `summary` text, when available, is appended after it, not substituted for it.
- [x] 10.6 `observed_facts[]` built entirely from `Incident`/`LogEvent`/`ErrorCluster` data (occurrence count, first/last seen, error type/message, endpoint, HTTP status, request_id) with real `evidence[]` entries referencing `LogEvent.raw_ref` and real timestamps — never a pass-through of `GeminiIncidentAnalysis.observed_facts`, which is Gemini's own restatement and is deliberately discarded rather than copied, to keep the fact/hypothesis boundary structurally enforced rather than merely documented.
- [x] 10.7 `correlated_events` and `related_incident_ids` are unconditionally `[]` — no correlation evidence source (deployment, git, cross-incident, traffic, infrastructure) exists anywhere in Tracy today; not asked of Gemini.
- [x] 10.8 `deployment_information` populated only from `LogEvent.version` when present (omitted entirely otherwise); `commit`/`deployed_at`/`relevant_commit`/`relevant_files`/`documentation_context` are never fabricated — left at the schema's empty representation, deferred to Codex's future repository access.
- [x] 10.9 Gemini failure/unavailability (`analysis=None`) still produces a fully schema-valid `IncidentPackage` — every Gemini-owned field takes its empty form (`[]`, `0.0`, or omitted), and every Tracy-owned field is populated exactly as when Gemini succeeds; verified by dedicated tests including a full `jsonschema.validate()` pass on the degraded package.
- [x] 10.10 `backend/tracy/__main__.py` builds and prints the `IncidentPackage` for a newly-detected incident only (`[INCIDENT]`/`[HYPOTHESIS]`/`[CONFIDENCE]`/`[RECOMMENDED INVESTIGATION]`), whether or not Gemini succeeded. 35 new tests in `backend/tests/test_incident_package.py` (115 total, up from 80); `jsonschema` added as a **dev-only** dependency (needed only to test real schema conformance, not at runtime) — no other new dependency.
- [ ] 10.11 Persistent `IncidentPackage` storage (Postgres or otherwise) — deferred; each package is built fresh in-process and only ever printed, matching this repository's existing in-memory-everything posture (`Deduplicator`, `ErrorGrouper`, `IncidentStore`).
- [ ] 10.12 Real cross-incident correlation, deployment/commit correlation, and Codex repository evidence — deferred, no evidence source exists yet (see 10.7/10.8).
- [ ] 10.13 Statistical/business-impact metrics (revenue, affected users, traffic percentage, downtime) and the full `DETECTED -> ... -> RESOLVED`/`FAILED` workflow state machine — still deferred, unchanged from `§7`/`§8`/`§9`'s existing scope.

## Out of Scope for This Change

The hackathon vertical slice below is the priority once implementation starts; everything else in the six specs (dashboard, historical backfill, additional log sources) is explicitly secondary. None of the following exists as code yet — see `design.md` for the Implemented/Planned/External-dependency/Not-yet-available breakdown per decision:

- FastAPI application, SQLAlchemy models/Alembic migrations (the ingestion-side Pydantic models, `LogEvent`/`ErrorCluster`, now exist — see §7.1)
- The GCP Cloud Logging / Log Router / Pub/Sub adapter (the `google-genai` Gemini client now exists — see §9)
- Postgres-backed orchestrator implementing the `DETECTED` → ... → `RESOLVED`/`FAILED` state machine
- Any GCP project, IAM role, Pub/Sub topic, or GitHub Copilot enablement (all external dependencies to provision, not build)
- Next.js/React/Tailwind dashboard
- `post-deployment-verification` implementation (depends on the ingestion pipeline existing first)
