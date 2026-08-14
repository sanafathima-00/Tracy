"""Tests for deterministic incident detection: threshold rules, severity
mapping, and duplicate-incident prevention. No LLM, no mocks -- pure
function/state tests, matching test_pipeline.py's style."""

import json
from datetime import datetime, timezone
from pathlib import Path

from tracy.detection import (
    CRITICAL_THRESHOLD,
    REPEATED_ERROR_THRESHOLD,
    IncidentDetector,
    map_severity,
)
from tracy.ingestion.base import RawRecord
from tracy.ingestion.local import LocalLogSource
from tracy.ingestion.pipeline import Pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample_logs.jsonl"

VALID_ERROR = {
    "timestamp": "2026-08-14T14:00:00Z",
    "severity": "ERROR",
    "service": "checkout-api",
    "environment": "production",
    "message": "Unhandled exception",
    "error_type": "ZeroDivisionError",
    "endpoint": "/checkout",
}


def _raw(payload: dict, event_id: str) -> RawRecord:
    return RawRecord(payload=json.dumps(dict(payload, event_id=event_id)).encode("utf-8"), source="local")


# --- Threshold ---------------------------------------------------------------


def test_single_error_below_threshold_is_not_an_incident():
    pipeline = Pipeline()
    detector = IncidentDetector()
    result = pipeline.process(_raw(VALID_ERROR, "e1"))
    assert result.cluster.count == 1
    assert detector.check(result) is None


def test_second_identical_error_reaches_threshold_and_creates_incident():
    pipeline = Pipeline()
    detector = IncidentDetector()
    pipeline.process(_raw(VALID_ERROR, "e1"))
    result = pipeline.process(_raw(VALID_ERROR, "e2"))
    assert result.cluster.count == REPEATED_ERROR_THRESHOLD == 2

    detection = detector.check(result)
    assert detection is not None
    incident, is_new = detection
    assert is_new is True
    assert incident.error_cluster.count == 2


# --- Duplicate prevention ------------------------------------------------------


def test_third_and_fourth_occurrence_return_same_incident_id_not_new():
    pipeline = Pipeline()
    detector = IncidentDetector()
    for event_id in ("e1", "e2"):
        result = pipeline.process(_raw(VALID_ERROR, event_id))
    first_incident, first_is_new = detector.check(result)
    assert first_is_new is True

    result3 = pipeline.process(_raw(VALID_ERROR, "e3"))
    third_incident, third_is_new = detector.check(result3)
    assert third_is_new is False
    assert third_incident.incident_id == first_incident.incident_id
    assert third_incident.error_cluster.count == 3

    result4 = pipeline.process(_raw(VALID_ERROR, "e4"))
    fourth_incident, fourth_is_new = detector.check(result4)
    assert fourth_is_new is False
    assert fourth_incident.incident_id == first_incident.incident_id
    assert fourth_incident.error_cluster.count == 4


# --- Critical ------------------------------------------------------------------


def test_single_critical_error_creates_incident_immediately():
    pipeline = Pipeline()
    detector = IncidentDetector()
    critical = dict(VALID_ERROR, severity="CRITICAL")
    result = pipeline.process(_raw(critical, "e1"))
    assert result.cluster.count == CRITICAL_THRESHOLD == 1

    detection = detector.check(result)
    assert detection is not None
    incident, is_new = detection
    assert is_new is True
    assert incident.severity == "critical"


# --- Service / environment sourcing ---------------------------------------------


def test_service_and_environment_come_from_log_event_not_signature():
    pipeline = Pipeline()
    detector = IncidentDetector()
    payload = dict(VALID_ERROR, environment="staging")
    pipeline.process(_raw(payload, "e1"))
    result = pipeline.process(_raw(payload, "e2"))
    incident, _ = detector.check(result)

    assert incident.service == "checkout-api"
    assert incident.environment == "staging"
    # The signature is opaque and unparsed for these fields -- confirm the
    # detector didn't have to reach into it to get service/environment right.
    assert incident.service == result.event.service
    assert incident.environment == result.event.environment


def test_affected_component_derived_from_event_metadata_endpoint():
    pipeline = Pipeline()
    detector = IncidentDetector()
    pipeline.process(_raw(VALID_ERROR, "e1"))
    result = pipeline.process(_raw(VALID_ERROR, "e2"))
    incident, _ = detector.check(result)
    assert incident.affected_component == "/checkout"


def test_affected_component_is_none_when_endpoint_absent():
    pipeline = Pipeline()
    detector = IncidentDetector()
    no_endpoint = {k: v for k, v in VALID_ERROR.items() if k != "endpoint"}
    pipeline.process(_raw(no_endpoint, "e1"))
    result = pipeline.process(_raw(no_endpoint, "e2"))
    incident, _ = detector.check(result)
    assert incident.affected_component is None


# --- Non-error events -----------------------------------------------------------


def test_info_event_never_reaches_incident_detection():
    pipeline = Pipeline()
    detector = IncidentDetector()
    info = {
        "timestamp": "2026-08-14T14:00:00Z",
        "severity": "INFO",
        "service": "checkout-api",
        "message": "Checkout completed",
    }
    result = pipeline.process(_raw(info, "e1"))
    assert result.cluster is None
    assert detector.check(result) is None


def test_warning_event_never_reaches_incident_detection():
    pipeline = Pipeline()
    detector = IncidentDetector()
    warning = {
        "timestamp": "2026-08-14T14:00:00Z",
        "severity": "WARNING",
        "service": "checkout-api",
        "message": "Insufficient stock",
    }
    result = pipeline.process(_raw(warning, "e1"))
    assert result.cluster is None
    assert detector.check(result) is None


def test_result_with_no_event_returns_none():
    detector = IncidentDetector()
    pipeline = Pipeline()
    malformed = pipeline.process(RawRecord(payload=b"not json", source="local"))
    assert detector.check(malformed) is None


# --- Multiple incidents ----------------------------------------------------------


def test_two_different_signatures_produce_two_different_incidents():
    pipeline = Pipeline()
    detector = IncidentDetector()
    error_a = dict(VALID_ERROR, error_type="ZeroDivisionError")
    error_b = dict(VALID_ERROR, error_type="KeyError")

    pipeline.process(_raw(error_a, "a1"))
    result_a = pipeline.process(_raw(error_a, "a2"))
    incident_a, _ = detector.check(result_a)

    pipeline.process(_raw(error_b, "b1"))
    result_b = pipeline.process(_raw(error_b, "b2"))
    incident_b, _ = detector.check(result_b)

    assert incident_a.incident_id != incident_b.incident_id
    assert len(detector.store.all()) == 2


# --- Severity mapping ------------------------------------------------------------


def test_map_severity_is_deterministic_and_total():
    assert map_severity("CRITICAL") == "critical"
    assert map_severity("ERROR") == "high"
    assert map_severity("WARNING") == "medium"
    assert map_severity("INFO") == "low"
    assert map_severity("DEBUG") == "low"


# --- End-to-end (fixture) ---------------------------------------------------------


def test_fixture_end_to_end_produces_exactly_one_incident():
    """The fixture's two ZeroDivisionError lines (same signature, different
    request_id/stack-trace line numbers) must collapse into exactly one
    Incident, at severity 'high', with a stable incident_id."""
    pipeline = Pipeline()
    detector = IncidentDetector()
    seen_incident_ids = []

    def on_message(raw):
        result = pipeline.process(raw)
        detection = detector.check(result)
        if detection is not None:
            incident, _ = detection
            seen_incident_ids.append(incident.incident_id)

    LocalLogSource(FIXTURE, follow=False).listen(on_message)

    incidents = detector.store.all()
    assert len(incidents) == 1
    assert incidents[0].service == "checkout-api"
    assert incidents[0].severity == "high"
    assert incidents[0].error_cluster.count == 2
    assert len(set(seen_incident_ids)) == 1


def test_detected_at_is_a_real_utc_timestamp():
    pipeline = Pipeline()
    detector = IncidentDetector()
    pipeline.process(_raw(VALID_ERROR, "e1"))
    result = pipeline.process(_raw(VALID_ERROR, "e2"))
    incident, _ = detector.check(result)
    assert isinstance(incident.detected_at, datetime)
    assert incident.detected_at.tzinfo is not None
    assert incident.detected_at <= datetime.now(timezone.utc)
