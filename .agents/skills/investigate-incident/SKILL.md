---
name: investigate-incident
description: Given a Tracy Incident Package, independently investigate the codebase, git history, configuration, tests, and documentation to validate or refute Tracy's suspected root cause, then decide whether the fix needs full OpenSpec planning or a lightweight path. Use when handed an incident to investigate — via the /incident command or a manually-provided Incident Package file. Never implements a fix.
---

# Investigate Incident

You are acting as the engineering investigator described in Tracy's `incident-fix-workflow` spec. Your job is to find out whether Tracy's hypothesis is actually right — not to trust it, and not to fix anything yet.

**This skill investigates only. It never writes application code.** If you find yourself about to edit a file to fix something, stop — that belongs to `implement-incident-fix`, and only after this skill's verdict says a fix is warranted.

## Input

An Incident Package — either a file path you're given, JSON pasted into the conversation, or (in the GitHub Actions execution path) a file written to the workspace by the triggering workflow. It should match the schema in `openspec/changes/establish-incident-response-workflow/incident-package.schema.json` (or, if that change has since been archived, `openspec/specs/incident-context/spec.md` and wherever the schema was promoted to). If the package is missing required fields (`incident_id`, `severity`, `summary`, `observed_facts`, `confidence_overall`), say so and ask for a complete one rather than guessing the missing pieces. Use `symptoms` and `error_clusters` as your starting evidence — they're already aggregated and are what Gemini judged most relevant; you should not need raw logs to begin.

**Execution context**: when this skill runs via `openai/codex-action` in `.github/workflows/incident-response.yml`, you're on a fresh checkout of the repository for this run only — nothing persists from any earlier run beyond what's in the Incident Package and this repository's own history.

## Steps

1. **Restate the claim, don't inherit it.** Read the package's `hypotheses` array. For each hypothesis, state it back explicitly as a claim to test: "Tracy's hypothesis: `<statement>` (confidence: `<confidence>`)." Do the same for `observed_facts` (these are the only things you can treat as already proven) and `correlated_events` (related in time, not proven causal — treat as leads, not conclusions).

2. **Investigate the codebase.**
   - Search the repository for the affected component/service named in the package (`affected_component`, `service`, `relevant_files`).
   - Read the relevant code paths and their existing tests.
   - Check configuration, Docker, and deployment files touching that area, if present. **Never copy a secret value (API key, credential, token) into your investigation report or anything downstream — reference the variable name only.**

3. **Investigate git history.**
   - `git log` on the affected files/paths, focused on the window around `deployment_information` / `timeline` if present.
   - `git show` / `git diff` on any commit or merge that plausibly touches the failure.
   - `git blame` the specific lines implicated by the hypothesis, if any.
   - Explicitly check whether a recent deployment or merge lines up with the incident's start time — this is exactly the kind of correlation Tracy flags but cannot confirm from logs alone.

4. **Investigate documentation.**
   - README and `docs/` for the affected area, if any exist.
   - `openspec/specs/<capability>/spec.md` for any capability whose documented behavior touches the incident — a fix that would contradict a spec's SHALL/MUST requirement is a signal the spec (not just the code) may need to change.

5. **Render a verdict per hypothesis**: `confirmed`, `refuted`, `partially confirmed`, or `inconclusive` — each with the specific evidence (file:line, commit SHA, test name, spec reference) that supports it. Never accept a hypothesis on timing correlation alone if the code/config/history doesn't back it up; conversely, never reject one just because Tracy's confidence was low, if your own investigation confirms it.

6. **If every hypothesis is refuted or inconclusive**, do not invent a replacement root cause from speculation. Report what you ruled out, what you found instead (if anything), and stop for guidance rather than guessing.

7. **Decide the planning path**, per `incident-fix-workflow`:
   - **Use OpenSpec** (hand off to `openspec-propose` / `openspec-explore` for a proper change) when the fix would change behavior described by an existing spec, touches multiple components, or is otherwise a meaningful production change.
   - **Use the lightweight path** (go straight to `implement-incident-fix`) only for a small, localized fix that changes no documented requirement — e.g. a null check, a config value, a query typo.
   - When unsure, prefer OpenSpec — the cost of an unnecessary proposal is much lower than an undocumented behavior change reaching production again.

## Output: Investigation Report

Produce a report with:
- `incident_id` and a one-line restatement of the original symptom
- Each hypothesis, its verdict, and its evidence
- The validated (or newly identified) root cause, stated as a claim you can defend with evidence — not as a copy of Tracy's hypothesis
- Chosen planning path (OpenSpec or lightweight) and why
- Anything you could not determine, stated plainly rather than papered over

## Guardrails

- Never implement, edit, or stage a code change in this skill.
- Never present a correlation or an unverified hypothesis as a confirmed root cause.
- Never fabricate evidence (a commit SHA, a line number, a test result) — if you didn't check it, say you didn't.
- If the Incident Package itself looks wrong (contradicts what you find in the repo), say so — Tracy's output is a lead, not ground truth.
- Never put a secret value into the Investigation Report, a commit, or a PR description — variable names only.
