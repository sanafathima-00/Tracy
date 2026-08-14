---
name: review-feedback-loop
description: Triggered by a GitHub pull_request_review event on a tracy-incident-labeled PR. Classifies Copilot's findings as blocking or non-blocking, enforces the 3-attempt remediation cap, and either hands remediation to implement-incident-fix and pushes, or reports READY_FOR_HUMAN / HUMAN_ATTENTION_REQUIRED. Never merges.
---

# Review Feedback Loop

You are the re-entry point for an incident PR every time a review comes in. You run in a fresh GitHub Actions job each time (see `.github/workflows/incident-review-feedback.yml`) — you have no memory of prior iterations except what's visible on the PR itself (its labels, comments, and review history).

**Only act on PRs labeled `tracy-incident`.** If the PR that triggered this run doesn't carry that label, stop immediately — it's not yours to touch.

## Input

The triggering `pull_request_review` event: the PR, the review body/comments, and the review state (`approved`, `changes_requested`, `commented`). Read the PR's own labels and comment history to determine how many remediation attempts have already happened — track this as a `tracy-attempt-N` label (starting at `tracy-attempt-1` on the first remediation), since no other state survives between runs.

## Steps

1. **Read the review.** Copilot's review comments are natural-language, not a structured blocking/non-blocking flag — you have to make that call.

2. **Classify each finding** as:
   - **Blocking**: correctness bugs, security issues, incorrect assumptions about the incident's root cause, missing test coverage for the fix itself, or a regression risk Copilot identified.
   - **Non-blocking**: style preferences, optional suggestions, or observations unrelated to correctness/security/risk.

3. **Check the retry count** (from the `tracy-attempt-N` label, or absence of one = zero attempts so far).
   - **No blocking findings** → skip to step 6 (`READY_FOR_HUMAN`).
   - **Blocking findings present and attempts < 3** → continue to step 4.
   - **Blocking findings present and attempts >= 3** → skip to step 5 (`HUMAN_ATTENTION_REQUIRED`).

4. **Remediate.** Increment the attempt label (`tracy-attempt-N` → `tracy-attempt-N+1`). Hand the blocking findings to `implement-incident-fix` as a remediation pass, scoped exactly to what Copilot flagged — not a chance to make unrelated changes. Once it hands back a diff, commit and push it to the same branch. Pushing triggers Copilot to review again automatically; your job for this run ends here.

5. **Escalate.** If the retry cap is hit with blocking findings still open, label the PR `human-attention-required`, comment on the PR explaining which findings remain unresolved after 3 attempts, and stop. Do not attempt a fourth remediation.

6. **Clear to proceed.** If there are no blocking findings (on the first review, or after remediation succeeds), label the PR `ready-for-human` and state plainly that it's awaiting human approval — never that it's approved or mergeable by this skill.

## Guardrails

- Never act on a PR without the `tracy-incident` label.
- Never exceed the 3-attempt remediation cap — `HUMAN_ATTENTION_REQUIRED` exists specifically to stop an infinite loop.
- Never merge, and never remove a human from the approval step regardless of how clean the review is.
- Never let a remediation pass grow beyond what the specific blocking findings called for.
- If you cannot tell whether a finding is blocking or not, treat it as blocking — a missed non-blocking-vs-blocking call that's too strict costs a review cycle; one that's too lax risks shipping an unaddressed bug.
