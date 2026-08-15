# Tracy

Tracy is an autonomous production-incident-to-resolution system built for a hackathon. It watches a monitored application's logs, deterministically detects incidents, asks Gemini to explain them, assembles a validated, schema-conformant Incident Package, and hands it to Codex (via GitHub Actions) to independently investigate the codebase and git history — before any code is ever changed.

```
checkout-api (monitored demo app)
      │ structured JSON logs
      ▼
Tracy: LocalLogSource → Pipeline → LogEvent → ErrorCluster
      │
      ▼
IncidentDetector → Incident (deterministic, no LLM)
      │
      ▼
GeminiClient → GeminiIncidentAnalysis (interpretation, never the decision-maker)
      │
      ▼
IncidentPackageBuilder → validated IncidentPackage
      │
      ▼ (manual --dispatch flag)
GitHub repository_dispatch → GitHub Actions → Codex (:read-only) → investigate-incident
      │
      ▼
structured investigation result  (read-only — no commits, no PRs, yet)
```

## Responsibility split

- **Tracy** owns log ingestion/normalization, deterministic incident detection, and handing Gemini's interpretation into a validated package.
- **Gemini** owns interpretation only — summary, hypotheses with confidence, recommended investigation steps. It never decides severity, never decides whether an incident exists, and is never trusted blindly.
- **Codex** owns independent repository/git-history investigation (read-only today; write-capable phases are intentionally not built yet).
- **Humans** own every merge decision — nothing in this system merges automatically.

## Repository layout

- [`checkout-api/`](checkout-api/README.md) — a small, standalone FastAPI service used as the monitored "production" application, with an intentionally planted regression.
- [`backend/`](backend/README.md) — Tracy itself: the ingestion pipeline, incident detection, Gemini integration, Incident Package builder, and GitHub dispatch.
- [`openspec/`](openspec/changes/establish-incident-response-workflow/) — the spec-driven design and task tracking for this project (see `design.md`, `tasks.md`, and the capability specs under `specs/`).
- [`.agents/skills/`](.agents/skills/) — the Codex-facing skills (`investigate-incident`, `implement-incident-fix`, `create-incident-pr`, `review-feedback-loop`) that define what Codex is and isn't allowed to do at each stage.
- [`.github/workflows/`](.github/workflows/) — `incident-investigation.yml` (read-only Codex investigation, implemented) and `incident-response.yml`/`incident-review-feedback.yml` (write-capable fix/PR/review workflows, scaffolded but not yet exercised).

## Current status

Implemented and tested: local log ingestion, deterministic incident detection and deduplication, Gemini-based incident analysis with graceful degradation, a validated `IncidentPackage` builder (checked against its JSON Schema, not just Pydantic), and a read-only Tracy → GitHub → Codex investigation path. The live GitHub Actions → Codex loop has been wired and locally validated but not yet exercised on a real workflow run. Write-capable Codex execution (implementing fixes, opening PRs) is deliberately not implemented — see `openspec/changes/establish-incident-response-workflow/tasks.md` for the exact, honestly-tracked status of every piece.

## Local development

See [`backend/README.md`](backend/README.md) and [`checkout-api/README.md`](checkout-api/README.md) for setup and how to run the local demo end-to-end.
