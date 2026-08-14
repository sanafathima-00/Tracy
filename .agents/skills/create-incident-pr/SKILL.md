---
name: create-incident-pr
description: Given a self-reviewed fix from implement-incident-fix, commit it, open a GitHub PR with a structured incident-fix description, label it as a Tracy incident PR, and let GitHub Copilot's automatic review run. Does not handle later review cycles — that's review-feedback-loop. Never merges.
---

# Create Incident PR

You package a validated, self-reviewed fix into a reviewable PR. Your job ends once the PR is open and labeled — GitHub Copilot's automatic review then runs on its own, and any later review cycle is `review-feedback-loop`'s job, not yours. You never merge (see `pr-review-workflow`; merge is a human decision, always).

## Preconditions

- `implement-incident-fix` has produced a diff, test results, and self-review notes on an isolated branch/worktree, from a first-pass investigation (not a remediation — that path doesn't come back through this skill).

## Steps

1. **Commit.** Write a commit message that states the incident and the fix, not just the mechanical change.

2. **Push and open the PR** with a structured description covering:
   - **Incident summary** — restate Tracy's human-readable summary
   - **Root cause** — the validated cause from the Investigation Report, with its evidence, not the original unverified hypothesis
   - **Fix** — what changed and why it addresses the root cause
   - **Test results** — what was run, what passed, and whether a regression test was added (or why not)
   - **Risk** — scope of the change, anything flagged during self-review as broader than the incident, and what could go wrong

3. **Label the PR `tracy-incident`.** This is how `review-feedback-loop` (triggered separately by `pull_request_review` events) knows this PR is one it's allowed to act on. Skipping this silently breaks the remediation loop — treat it as a required step, not a nicety.

4. **Do not request review manually.** GitHub Copilot's automatic code review is enabled at the repository level and reviews the PR on open (and again on every later push) without a manual trigger. If you find Copilot review is not enabled, say so plainly rather than assuming it ran.

5. **Stop here.** Report the PR URL and that it's awaiting Copilot's automatic review. Do not wait for the review result in this skill — that's `review-feedback-loop`'s job once the `pull_request_review` event fires.

## Guardrails

- Never merge, and never imply that opening the PR or a clean review means merged.
- Never claim Copilot reviewed the PR if repository-level automatic review isn't actually enabled.
- Never skip the `tracy-incident` label — it's the only thing that lets the remediation loop find this PR later.
- Don't loop on review results yourself — that responsibility belongs entirely to `review-feedback-loop`.
