"""Tests for IncidentPackageBuilder / IncidentPackage. No network, no real
Gemini API call -- GeminiIncidentAnalysis instances are constructed by hand
or built through the real deterministic pipeline; only build() is under
test here, never GeminiClient.analyze()."""

import json
from pathlib import Path

import jsonschema
import pytest

from tracy.detection import IncidentDetector
from tracy.gemini import GeminiIncidentAnalysis, Hypothesis
from tracy.incident_package import IncidentPackageBuilder
from tracy.ingestion.base import RawRecord
from tracy.ingestion.pipeline import Pipeline

SCHEMA_PATH = (
    Path(__file__).parent.parent.parent
    / "openspec"
    / "changes"
    / "establish-incident-response-workflow"
    / "incident-package.schema.json"
)

VALID_ERROR = {
    "timestamp": "2026-08-14T14:00:00Z",
    "severity": "ERROR",
    "service": "checkout-api",
    "environment": "production",
    "message": "Unhandled exception",
    "error_type": "ZeroDivisionError",
    "error_message": "float division by zero",
    "endpoint": "/checkout",
    "http_status": 500,
    "request_id": "req-abc",
    "version": "1.4.2",
    "stack_trace": (
        'Traceback (most recent call last):\n'
        '  File "app/main.py", line 142, in checkout\n'
        '    total_price = calculate_total(...)\n'
        '  File "app/pricing.py", line 14, in calculate_total\n'
        "ZeroDivisionError: float division by zero"
    ),
}

ANALYSIS = GeminiIncidentAnalysis(
    summary="This looks like a division-by-zero when stock reaches the requested quantity.",
    impact_description="Checkout requests for the affected product fail with a 500 error.",
    symptoms=["HTTP 500 on POST /checkout", "ZeroDivisionError raised in calculate_total"],
    observed_facts=["ZeroDivisionError occurred 2 times"],  # Gemini's own restatement -- must not leak into the package's observed_facts
    hypotheses=[
        Hypothesis(statement="remaining_after_purchase reached zero", confidence=0.85),
        Hypothesis(statement="unrelated race condition", confidence=0.2),
    ],
    recommended_investigation=["Inspect calculate_total in pricing.py for a zero-guard"],
)


def _incident_and_event(payload=None, occurrences=2):
    payload = payload or VALID_ERROR
    pipeline = Pipeline()
    detector = IncidentDetector()
    result = None
    for i in range(occurrences):
        raw = RawRecord(payload=json.dumps(dict(payload, event_id=f"e{i}")).encode(), source="local")
        result = pipeline.process(raw)
    incident, _ = detector.check(result)
    return incident, result.event


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


# --- Package validation --------------------------------------------------------


def test_builder_produces_valid_package_with_analysis():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.incident_id == incident.incident_id


def test_schema_version_is_exact_existing_contract():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.schema_version == "1.1"


def test_required_fields_present_in_serialized_dict():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, None)
    data = package.to_schema_dict()
    for field in ("incident_id", "schema_version", "severity", "detected_at", "service", "summary", "observed_facts", "confidence_overall"):
        assert field in data


def test_severity_is_a_valid_enum_value():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.severity in ("critical", "high", "medium", "low")


def test_serialization_has_no_null_values_for_unset_optional_fields():
    """The schema declares optional fields with plain (non-nullable) types
    -- a `null` would fail validation. to_schema_dict() must omit, not null,
    fields Tracy/Gemini has no value for."""
    no_version = {k: v for k, v in VALID_ERROR.items() if k != "version"}
    incident, event = _incident_and_event(no_version)
    package = IncidentPackageBuilder().build(incident, event, None)
    data = package.to_schema_dict()
    assert "deployment_information" not in data  # no LogEvent.version in this payload
    assert "suspected_root_cause" not in data  # no hypotheses
    assert None not in data.values()


def test_serialized_package_conforms_to_json_schema_with_analysis(schema):
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    jsonschema.validate(instance=package.to_schema_dict(), schema=schema)


def test_serialized_package_conforms_to_json_schema_without_analysis(schema):
    """The degraded (Gemini-unavailable) path must also be schema-valid."""
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, None)
    jsonschema.validate(instance=package.to_schema_dict(), schema=schema)


# --- Deterministic ownership -----------------------------------------------------


def test_tracy_severity_is_preserved_exactly():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.severity == incident.severity


def test_gemini_incident_analysis_has_no_severity_field_at_all():
    """Structural guarantee: Gemini's output model cannot carry a severity
    value even if a future prompt change tried to elicit one."""
    assert "severity" not in GeminiIncidentAnalysis.model_fields


@pytest.mark.parametrize("severity_payload_severity", ["ERROR", "CRITICAL"])
def test_gemini_cannot_override_severity_across_log_severities(severity_payload_severity):
    payload = dict(VALID_ERROR, severity=severity_payload_severity)
    occurrences = 1 if severity_payload_severity == "CRITICAL" else 2
    incident, event = _incident_and_event(payload, occurrences=occurrences)
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.severity == incident.severity


def test_occurrence_count_comes_from_error_cluster():
    incident, event = _incident_and_event(occurrences=2)
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.error_clusters[0].count == incident.error_cluster.count == 2
    assert package.impact.value == "2"


def test_service_and_environment_come_from_incident():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.service == incident.service
    assert package.environment == incident.environment


def test_timeline_contains_only_deterministic_tracy_timestamps():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    known_timestamps = {incident.error_cluster.first_seen, incident.error_cluster.last_seen, incident.detected_at}
    for entry in package.timeline:
        assert entry.timestamp in known_timestamps
        # No Gemini vocabulary ("hypothesis", "confidence", "root cause") in timeline event text.
        assert "hypothes" not in entry.event.lower()
        assert "root cause" not in entry.event.lower()


# --- Gemini integration -----------------------------------------------------------


def test_gemini_summary_appears_in_package_summary():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert ANALYSIS.summary in package.summary


def test_gemini_impact_description_appears():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.impact.description == ANALYSIS.impact_description


def test_gemini_symptoms_appear():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.symptoms == ANALYSIS.symptoms


def test_gemini_hypotheses_appear_with_statement_and_confidence():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert [(h.statement, h.confidence) for h in package.hypotheses] == [
        (h.statement, h.confidence) for h in ANALYSIS.hypotheses
    ]


def test_highest_confidence_hypothesis_determines_confidence_overall():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.confidence_overall == 0.85  # max(0.85, 0.2)


def test_highest_confidence_hypothesis_determines_suspected_root_cause():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.suspected_root_cause == "remaining_after_purchase reached zero"


def test_zero_hypotheses_produces_confidence_overall_zero_and_no_root_cause():
    incident, event = _incident_and_event()
    no_hypotheses = ANALYSIS.model_copy(update={"hypotheses": []})
    package = IncidentPackageBuilder().build(incident, event, no_hypotheses)
    assert package.confidence_overall == 0.0
    assert package.suspected_root_cause is None
    assert "suspected_root_cause" not in package.to_schema_dict()


# --- Facts vs hypotheses -----------------------------------------------------------


def test_observed_facts_contain_deterministic_evidence():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    joined = " ".join(f.statement for f in package.observed_facts)
    assert "ZeroDivisionError" in joined
    assert "2 time(s)" in joined
    assert incident.service in joined


def test_gemini_hypothesis_text_never_appears_in_observed_facts():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    joined = " ".join(f.statement for f in package.observed_facts)
    for hypothesis in ANALYSIS.hypotheses:
        assert hypothesis.statement not in joined


def test_geminis_own_observed_facts_field_is_never_copied_into_the_package():
    """GeminiIncidentAnalysis.observed_facts is Gemini's own restatement of
    evidence -- the package's observed_facts must come only from Tracy's
    build logic, never a pass-through of Gemini's list."""
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    package_statements = {f.statement for f in package.observed_facts}
    assert not package_statements.intersection(ANALYSIS.observed_facts)


def test_unsupported_gemini_impact_claims_do_not_override_deterministic_metric():
    dangerous_analysis = ANALYSIS.model_copy(
        update={"impact_description": "This cost the business $50,000 and affected 10,000 users."}
    )
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, dangerous_analysis)
    # Gemini's prose is allowed in `description`, but the deterministic
    # metric/value must remain Tracy's occurrence count, never overridden.
    assert package.impact.metric == "occurrence_count"
    assert package.impact.value == str(incident.error_cluster.count)


# --- Correlations ---------------------------------------------------------------


def test_correlated_events_always_empty():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.correlated_events == []


def test_related_incident_ids_always_empty():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.related_incident_ids == []


# --- Deployment -------------------------------------------------------------------


def test_version_is_preserved_when_available():
    incident, event = _incident_and_event()  # VALID_ERROR includes version="1.4.2"
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.deployment_information.version == "1.4.2"


def test_missing_version_does_not_fabricate_deployment_information():
    no_version = {k: v for k, v in VALID_ERROR.items() if k != "version"}
    incident, event = _incident_and_event(no_version)
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.deployment_information is None
    assert "deployment_information" not in package.to_schema_dict()


def test_commit_and_deployed_at_are_never_fabricated():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    assert package.deployment_information.commit is None
    assert package.deployment_information.deployed_at is None
    assert package.relevant_commit is None
    assert package.relevant_files == []


# --- Security --------------------------------------------------------------------


def test_sensitive_metadata_never_reaches_the_package():
    payload = dict(VALID_ERROR, Authorization="Bearer super-secret-token", api_key="sk-fake-key")
    incident, event = _incident_and_event(payload)
    # Simulate a hypothetical unsanitized metadata leak reaching the event,
    # bypassing Pipeline's own sanitizer, to prove the builder itself never
    # dumps arbitrary metadata into the package regardless.
    event.metadata["Authorization"] = "Bearer super-secret-token"
    event.metadata["api_key"] = "sk-fake-key"
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    dumped = json.dumps(package.to_schema_dict())
    assert "super-secret-token" not in dumped
    assert "sk-fake-key" not in dumped


def test_gemini_api_key_env_var_name_never_appears_in_package():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, ANALYSIS)
    dumped = json.dumps(package.to_schema_dict())
    assert "GEMINI_API_KEY" not in dumped


# --- Gemini failure / degraded mode -------------------------------------------------


def test_package_can_be_created_when_analysis_is_none():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, None)
    assert package.incident_id == incident.incident_id


def test_deterministic_fields_survive_gemini_failure():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, None)
    assert package.severity == incident.severity
    assert package.service == incident.service
    assert package.error_clusters[0].count == incident.error_cluster.count


def test_no_fake_gemini_content_is_inserted_on_failure():
    incident, event = _incident_and_event()
    package = IncidentPackageBuilder().build(incident, event, None)
    assert package.symptoms == []
    assert package.hypotheses == []
    assert package.recommended_investigation == []
    assert package.confidence_overall == 0.0
    assert package.suspected_root_cause is None
    assert package.summary == _bare_title(incident, event)


def _bare_title(incident, event) -> str:
    from tracy.incident_package import _deterministic_title

    return _deterministic_title(incident, event)
