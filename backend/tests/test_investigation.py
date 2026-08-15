"""Tests for the InvestigationResult contract and the implementation
decision gate. Pure model/logic tests -- no network, no Codex, no GitHub."""

import pytest
from pydantic import ValidationError

from tracy.investigation import (
    GateDecision,
    HypothesisAssessment,
    InvestigationResult,
    authorize_implementation,
)

BASE_HYPOTHESIS = {
    "statement": "remaining_after_purchase reached zero",
    "tracy_confidence": 0.85,
    "verdict": "confirmed",
    "evidence": ["checkout-api/app/pricing.py:14", "commit 91166e4"],
}


def _result(**overrides) -> InvestigationResult:
    defaults = dict(
        incident_id="abc123",
        hypothesis_assessments=[HypothesisAssessment(**BASE_HYPOTHESIS)],
        additional_facts=[],
        validated_root_cause="Division by zero when quantity equals remaining stock",
        root_cause_evidence=["checkout-api/app/pricing.py:14"],
        planning_path="lightweight",
        planning_path_reason="small, localized fix; no documented requirement changes",
        undetermined=[],
    )
    defaults.update(overrides)
    return InvestigationResult(**defaults)


# --- Model validation --------------------------------------------------------


def test_valid_result_parses():
    result = _result()
    assert result.incident_id == "abc123"
    assert result.hypothesis_assessments[0].verdict == "confirmed"


def test_verdict_vocabulary_is_fixed():
    with pytest.raises(ValidationError):
        HypothesisAssessment(statement="x", tracy_confidence=0.5, verdict="rejected", evidence=[])


def test_planning_path_vocabulary_is_fixed():
    with pytest.raises(ValidationError):
        _result(planning_path="full_rewrite")


def test_tracy_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        HypothesisAssessment(statement="x", tracy_confidence=1.5, verdict="confirmed", evidence=[])


def test_missing_planning_path_is_required():
    with pytest.raises(ValidationError):
        InvestigationResult(incident_id="abc123")


def test_validated_root_cause_defaults_to_none():
    result = InvestigationResult(incident_id="abc123", planning_path="undetermined")
    assert result.validated_root_cause is None
    assert result.hypothesis_assessments == []


# --- Gate: authorized cases --------------------------------------------------


def test_confirmed_root_cause_openspec_is_authorized():
    result = _result(planning_path="openspec")
    decision = authorize_implementation(result)
    assert decision.authorized is True


def test_confirmed_root_cause_lightweight_is_authorized():
    result = _result(planning_path="lightweight")
    decision = authorize_implementation(result)
    assert decision.authorized is True


def test_partially_confirmed_is_sufficient_to_authorize():
    result = _result(
        hypothesis_assessments=[HypothesisAssessment(**{**BASE_HYPOTHESIS, "verdict": "partially_confirmed"})]
    )
    assert authorize_implementation(result).authorized is True


def test_one_confirmed_among_mixed_verdicts_is_sufficient():
    """At least one authorizing verdict is enough -- other hypotheses can be
    refuted/inconclusive without blocking the gate."""
    result = _result(
        hypothesis_assessments=[
            HypothesisAssessment(**{**BASE_HYPOTHESIS, "statement": "a", "verdict": "refuted"}),
            HypothesisAssessment(**{**BASE_HYPOTHESIS, "statement": "b", "verdict": "confirmed"}),
            HypothesisAssessment(**{**BASE_HYPOTHESIS, "statement": "c", "verdict": "inconclusive"}),
        ]
    )
    assert authorize_implementation(result).authorized is True


# --- Gate: blocked cases ------------------------------------------------------


def test_refuted_only_is_not_authorized():
    result = _result(
        hypothesis_assessments=[HypothesisAssessment(**{**BASE_HYPOTHESIS, "verdict": "refuted"})],
    )
    decision = authorize_implementation(result)
    assert decision.authorized is False
    assert "confirmed" in decision.reason or "verdict" in decision.reason


def test_inconclusive_only_is_not_authorized():
    result = _result(
        hypothesis_assessments=[HypothesisAssessment(**{**BASE_HYPOTHESIS, "verdict": "inconclusive"})],
    )
    assert authorize_implementation(result).authorized is False


def test_null_root_cause_is_not_authorized():
    result = _result(validated_root_cause=None)
    decision = authorize_implementation(result)
    assert decision.authorized is False
    assert "root_cause" in decision.reason


def test_empty_string_root_cause_is_not_authorized():
    result = _result(validated_root_cause="   ")
    assert authorize_implementation(result).authorized is False


def test_undetermined_planning_path_is_not_authorized():
    result = _result(planning_path="undetermined")
    decision = authorize_implementation(result)
    assert decision.authorized is False
    assert "planning_path" in decision.reason


def test_no_hypotheses_at_all_is_not_authorized():
    result = _result(hypothesis_assessments=[])
    assert authorize_implementation(result).authorized is False


def test_high_tracy_confidence_alone_does_not_bypass_the_gate():
    """A high Gemini-originated tracy_confidence must never substitute for
    Codex's own verdict -- the gate reads .verdict, not .tracy_confidence."""
    result = _result(
        hypothesis_assessments=[
            HypothesisAssessment(**{**BASE_HYPOTHESIS, "tracy_confidence": 0.99, "verdict": "refuted"})
        ]
    )
    assert authorize_implementation(result).authorized is False


def test_gate_decision_is_a_plain_model():
    decision = authorize_implementation(_result())
    assert isinstance(decision, GateDecision)
    assert isinstance(decision.reason, str) and decision.reason
