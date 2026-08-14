---
name: implement-incident-fix
description: Given a completed investigate-incident report, implement the validated fix on an isolated branch/worktree, add a regression test, run the tests, and self-review the diff before handing off to create-incident-pr. Refuses to run without a validated root cause. Never edits code based on an unvalidated hypothesis.
---

# Implement Incident Fix

You implement exactly what `investigate-incident` validated — nothing more, nothing speculative. If you were not given an Investigation Report with a confirmed (or well-evidenced, newly identified) root cause, stop and ask for one instead of fixing what merely "seems related."

## Preconditions

This skill is entered two ways — treat both the same once you're in it:
- **First pass**: an Investigation Report from `investigate-incident` exists, with a root cause backed by evidence (not an unverified hypothesis) and a chosen planning path (OpenSpec or lightweight). If either is missing, go back to `investigate-incident` rather than deciding it here.
- **Remediation pass**: `review-feedback-loop` has handed you specific blocking review findings on an already-open PR/branch. Treat the findings as the thing to fix, scoped exactly as tightly as a first-pass root cause — do not use a remediation pass as an opportunity to make unrelated changes.

## Steps

1. **Create isolation, or reuse it.** First pass: start a dedicated branch or worktree for this fix. Remediation pass: check out the existing incident branch — don't create a second one. Either way, never commit directly to the main branch — this is a hard requirement from `incident-fix-workflow`, not a style preference.

2. **Follow the chosen planning path.**
   - **OpenSpec path**: use `openspec-propose` (or `openspec-explore` then `openspec-update-change`) to create/complete the change's proposal, design, specs delta, and tasks — grounded in the Investigation Report's root cause — then use `openspec-apply-change` to implement it task by task.
   - **Lightweight path**: implement the fix directly, scoped tightly to the validated root cause. Still explain, in the commit/PR description, what was investigated and why this fix follows from it.

3. **Add a regression test that fails without the fix.** Write or extend a test that reproduces the original symptom, confirm it fails against the pre-fix code path (or reason clearly about why it would), then confirm it passes after the fix. If no feasible automated test exists (e.g. it depends on external infrastructure state), say so explicitly in the output — do not silently skip coverage.

4. **Run the full relevant test suite**, not just the new test. Tracy's tests run under pytest — use whatever pytest configuration the repository actually defines (see the `test` skill/command), and do not assume test paths or markers that aren't configured.

5. **Self-review before handing off.** Re-read your own diff against the Investigation Report:
   - Does every changed line trace back to the validated root cause?
   - Is there anything in the diff that isn't explained by the fix (opportunistic refactors, unrelated cleanups)? Flag it explicitly rather than quietly including it — the reviewer and the human approver need to see it called out, not discover it.
   - Do the new/updated tests actually exercise the original failure, not just adjacent code?

6. **Stop here.** This skill never commits, pushes, or touches the PR itself — that's `create-incident-pr` on a first pass, or `review-feedback-loop` on a remediation pass. Hand back your diff, the test results, and your self-review notes to whichever skill invoked you.

## Guardrails

- Refuse to implement against an unvalidated hypothesis — send it back to `investigate-incident` instead.
- Keep the diff scoped to the incident. Anything broader gets flagged, not absorbed silently.
- Never work directly on the main branch.
- Never report a test as passing without having actually run it.
- If implementation reveals the validated root cause was still incomplete (the fix doesn't fully address the symptom once attempted), stop and say so rather than shipping a partial fix as if it were complete.
