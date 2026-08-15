"""Tests for GitHubDispatcher.dispatch_implementation() -- the tracy-implement
event. No real network calls -- tracy.github_dispatch._send_request is
monkeypatched throughout. Must pass with TRACY_GITHUB_TOKEN/
TRACY_GITHUB_REPOSITORY entirely unset and no network access."""

import json

import pytest

from tracy.detection import IncidentDetector
from tracy.gemini import GeminiIncidentAnalysis, Hypothesis
from tracy.github_dispatch import EVENT_TYPE_IMPLEMENT, GitHubDispatcher
from tracy.incident_package import IncidentPackageBuilder
from tracy.ingestion.base import RawRecord
from tracy.ingestion.pipeline import Pipeline
from tracy.investigation import HypothesisAssessment, InvestigationResult

VALID_ERROR = {
    "timestamp": "2026-08-14T14:00:00Z",
    "severity": "ERROR",
    "service": "checkout-api",
    "environment": "production",
    "message": "Unhandled exception",
    "error_type": "ZeroDivisionError",
    "endpoint": "/checkout",
}

ANALYSIS = GeminiIncidentAnalysis(
    summary="Looks like a division by zero.",
    impact_description="Checkout requests fail.",
    symptoms=["HTTP 500 on /checkout"],
    observed_facts=["ZeroDivisionError occurred 2 times"],
    hypotheses=[Hypothesis(statement="remaining_after_purchase reached zero", confidence=0.9)],
    recommended_investigation=["Inspect calculate_total in pricing.py"],
)


def _package():
    pipeline = Pipeline()
    detector = IncidentDetector()
    result = None
    for i in range(2):
        raw = RawRecord(payload=json.dumps(dict(VALID_ERROR, event_id=f"e{i}")).encode(), source="local")
        result = pipeline.process(raw)
    incident, _ = detector.check(result)
    return IncidentPackageBuilder().build(incident, result.event, ANALYSIS)


def _authorized_result(incident_id, **overrides):
    defaults = dict(
        incident_id=incident_id,
        hypothesis_assessments=[
            HypothesisAssessment(
                statement="remaining_after_purchase reached zero",
                tracy_confidence=0.9,
                verdict="confirmed",
                evidence=["checkout-api/app/pricing.py:14"],
            )
        ],
        validated_root_cause="Division by zero when quantity equals remaining stock",
        root_cause_evidence=["checkout-api/app/pricing.py:14"],
        planning_path="lightweight",
        planning_path_reason="small, localized fix",
    )
    defaults.update(overrides)
    return InvestigationResult(**defaults)


def _set_config(monkeypatch, token="ghp_fake_token_value", repo="someone/somerepo"):
    monkeypatch.setenv("TRACY_GITHUB_TOKEN", token)
    monkeypatch.setenv("TRACY_GITHUB_REPOSITORY", repo)


class _Recorder:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": dict(headers), "body": body})
        effect = self._responses.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


# --- Authorized dispatch ---------------------------------------------------------


def test_authorized_result_is_dispatched(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    result = GitHubDispatcher().dispatch_implementation(package, _authorized_result(package.incident_id))

    assert result.success is True
    assert len(recorder.calls) == 1


def test_event_type_is_tracy_implement(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    GitHubDispatcher().dispatch_implementation(package, _authorized_result(package.incident_id))

    sent = json.loads(recorder.calls[0]["body"])
    assert sent["event_type"] == EVENT_TYPE_IMPLEMENT == "tracy-implement"


def test_payload_contains_both_incident_package_and_investigation_result(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()
    investigation_result = _authorized_result(package.incident_id)

    GitHubDispatcher().dispatch_implementation(package, investigation_result)

    sent = json.loads(recorder.calls[0]["body"])
    assert set(sent["client_payload"].keys()) == {"incident_package", "investigation_result"}
    assert sent["client_payload"]["incident_package"] == package.to_schema_dict()
    assert sent["client_payload"]["investigation_result"]["validated_root_cause"] == investigation_result.validated_root_cause


def test_this_is_a_distinct_event_type_from_investigate(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204, 204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    dispatcher = GitHubDispatcher()
    package = _package()

    dispatcher.dispatch(package)
    dispatcher.dispatch_implementation(package, _authorized_result(package.incident_id))

    sent_investigate = json.loads(recorder.calls[0]["body"])
    sent_implement = json.loads(recorder.calls[1]["body"])
    assert sent_investigate["event_type"] == "tracy-investigate"
    assert sent_implement["event_type"] == "tracy-implement"


# --- Gate blocks unauthorized results, before any network call --------------------


def test_refuted_verdict_blocks_dispatch_without_network_call(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()
    bad_result = _authorized_result(
        package.incident_id,
        hypothesis_assessments=[
            HypothesisAssessment(statement="x", tracy_confidence=0.9, verdict="refuted", evidence=[])
        ],
    )

    result = GitHubDispatcher().dispatch_implementation(package, bad_result)

    assert result.success is False
    assert "not authorized" in result.message
    assert len(recorder.calls) == 0


def test_null_root_cause_blocks_dispatch(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()
    bad_result = _authorized_result(package.incident_id, validated_root_cause=None)

    result = GitHubDispatcher().dispatch_implementation(package, bad_result)

    assert result.success is False
    assert len(recorder.calls) == 0


def test_undetermined_planning_path_blocks_dispatch(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()
    bad_result = _authorized_result(package.incident_id, planning_path="undetermined")

    result = GitHubDispatcher().dispatch_implementation(package, bad_result)

    assert result.success is False
    assert len(recorder.calls) == 0


def test_mismatched_incident_id_blocks_dispatch(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()
    mismatched_result = _authorized_result("a-completely-different-incident-id")

    result = GitHubDispatcher().dispatch_implementation(package, mismatched_result)

    assert result.success is False
    assert "mismatch" in result.message
    assert len(recorder.calls) == 0


# --- Dedup, separate from tracy-investigate's dedup set --------------------------


def test_duplicate_implementation_dispatch_is_skipped(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    dispatcher = GitHubDispatcher()
    package = _package()
    investigation_result = _authorized_result(package.incident_id)

    first = dispatcher.dispatch_implementation(package, investigation_result)
    second = dispatcher.dispatch_implementation(package, investigation_result)

    assert first.success is True
    assert second.success is False
    assert "already dispatched" in second.message
    assert len(recorder.calls) == 1


def test_investigate_dispatch_does_not_block_a_later_implementation_dispatch(monkeypatch):
    """The two event types track dedup independently -- having already sent
    tracy-investigate for an incident must not skip its later tracy-implement."""
    _set_config(monkeypatch)
    recorder = _Recorder([204, 204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    dispatcher = GitHubDispatcher()
    package = _package()

    investigate_result = dispatcher.dispatch(package)
    implement_result = dispatcher.dispatch_implementation(package, _authorized_result(package.incident_id))

    assert investigate_result.success is True
    assert implement_result.success is True
    assert len(recorder.calls) == 2


# --- Secrets never leak (same guarantee as dispatch()) ----------------------------


def test_token_never_appears_in_implementation_payload(monkeypatch):
    secret_token = "ghp_super_secret_value_12345"
    _set_config(monkeypatch, token=secret_token)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    GitHubDispatcher().dispatch_implementation(package, _authorized_result(package.incident_id))

    assert secret_token not in recorder.calls[0]["body"].decode("utf-8")
