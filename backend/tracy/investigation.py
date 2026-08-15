"""The investigation-result contract Phase 5A's read-only Codex run produces
(see .github/workflows/incident-investigation.yml's prompt), and the
deterministic decision gate that decides whether Phase 5B's write-capable
implementation run is authorized to proceed.

    InvestigationResult -> authorize_implementation() -> GateDecision

This gate is the one thing standing between "Codex looked at the repo" and
"Codex is allowed to push a branch and open a PR." It is intentionally
Tracy-owned, deterministic, and independent of both Gemini's original
hypothesis and Codex's own prose -- Codex's *structured* verdict is
authoritative here, never its confidence-sounding narrative, and never
Gemini's `tracy_confidence` value (which is carried through only as
context, never as a gating input). See tasks.md's Phase 5B/5C section for
why this lives in Tracy rather than being trusted to the workflow prompt
alone.
"""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["confirmed", "refuted", "partially_confirmed", "inconclusive"]
PlanningPath = Literal["openspec", "lightweight", "undetermined"]

# Verdicts strong enough to authorize implementation. Deliberately excludes
# "refuted" and "inconclusive" -- see investigate-incident's own skill, step
# 6: "If every hypothesis is refuted or inconclusive, do not invent a
# replacement root cause from speculation... stop for guidance." A
# well-behaved investigation should never pair one of these two verdicts
# with a non-null validated_root_cause in the first place; the gate checks
# both anyway (defense in depth against a malformed or non-compliant
# result), not because it expects to catch a legitimate one.
_AUTHORIZING_VERDICTS = {"confirmed", "partially_confirmed"}


class HypothesisAssessment(BaseModel):
    statement: str
    tracy_confidence: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    evidence: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    """Mirrors the JSON contract embedded in incident-investigation.yml's
    Codex prompt exactly -- same field names, same verdict/planning_path
    vocabulary. Not redesigned here.
    """

    incident_id: str
    hypothesis_assessments: list[HypothesisAssessment] = Field(default_factory=list)
    additional_facts: list[str] = Field(default_factory=list)
    validated_root_cause: str | None = None
    root_cause_evidence: list[str] = Field(default_factory=list)
    planning_path: PlanningPath
    planning_path_reason: str = ""
    undetermined: list[str] = Field(default_factory=list)


class GateDecision(BaseModel):
    authorized: bool
    reason: str


def authorize_implementation(result: InvestigationResult) -> GateDecision:
    """Implementation may proceed only when ALL of the following hold:
      1. `validated_root_cause` is non-null/non-empty -- Codex claims an
         evidence-backed cause, not "I don't know."
      2. At least one hypothesis_assessment carries a "confirmed" or
         "partially_confirmed" verdict -- Codex's own structured judgment,
         never `tracy_confidence` (Gemini's original number) and never the
         prose alone. This is what makes Codex's investigation, not
         Gemini's hypothesis, authoritative for this transition.
      3. `planning_path` is "openspec" or "lightweight" -- "undetermined"
         means Codex could not even decide how to proceed, let alone that
         a fix is warranted.

    Any single failure blocks implementation entirely -- there is no
    partial-authorization path.
    """
    if not result.validated_root_cause or not result.validated_root_cause.strip():
        return GateDecision(
            authorized=False,
            reason="validated_root_cause is null or empty -- investigation did not establish a cause",
        )

    if not any(h.verdict in _AUTHORIZING_VERDICTS for h in result.hypothesis_assessments):
        return GateDecision(
            authorized=False,
            reason=(
                "no hypothesis_assessment carries a 'confirmed' or 'partially_confirmed' "
                "verdict -- Codex's own investigation did not support the claimed root cause"
            ),
        )

    if result.planning_path == "undetermined":
        return GateDecision(
            authorized=False,
            reason="planning_path is 'undetermined' -- Codex could not decide how to proceed",
        )

    return GateDecision(authorized=True, reason="validated_root_cause present, a hypothesis was confirmed or partially confirmed, and planning_path is decided")
