---
name: "Incident"
description: "Run Tracy's incident-response lifecycle locally from an Incident Package, for development and testing"
category: "Workflow"
tags: ["incident", "workflow"]
---

Run Tracy's incident-response lifecycle from an Incident Package, in this Claude Code session.

$ARGUMENTS

**Input**: A path to an Incident Package JSON file, or pasted Incident Package JSON. If neither is given, ask for one — do not fabricate an incident to proceed.

**This is the local/dev entry point, not the production path.** In production, Tracy dispatches `.github/workflows/incident-response.yml` directly via the GitHub API (see `codex-handoff`) — no human runs this command in that path. This command exists so the same Skills can be exercised and demoed interactively, without needing a live GCP pipeline or a real GitHub Actions run.

The full lifecycle this command walks through is:

```
investigate-incident → implement-incident-fix → create-incident-pr
→ (Copilot review, handled asynchronously by review-feedback-loop
   once a real PR and a real pull_request_review event exist —
   not simulated by this command)
```

**Steps**

1. Load the Incident Package. If it's missing required fields (`incident_id`, `severity`, `summary`, `observed_facts`, `confidence_overall`), say so and stop rather than guessing the gaps.
2. Invoke **investigate-incident**. Report its Investigation Report, including the chosen planning path (OpenSpec or lightweight).
3. Ask whether to proceed to implementation — do not silently continue into code changes without the user's go-ahead.
4. If yes, invoke **implement-incident-fix**, then **create-incident-pr** if a real GitHub repository and push access are available in this session; otherwise stop after `implement-incident-fix` and report the diff, since opening a real PR isn't meaningful without one.
5. Once a real PR exists, remediation is driven by `review-feedback-loop` through the `incident-review-feedback.yml` workflow when GitHub Copilot posts a review — not by this command continuing to poll or loop.

**Guardrails**
- Never invent an Incident Package field that wasn't provided.
- Never skip straight to implementation without at least reporting the investigation result first.
- Never merge a PR from this command — merge is a human decision, always.
- The automation itself lives in the Skills and the GitHub Actions workflows; this command only sequences them for a local run and reports what happened at each step.
