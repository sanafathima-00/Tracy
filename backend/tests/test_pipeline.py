"""Tests for the source-agnostic pipeline: parsing, LogEvent construction,
sanitization, deduplication, and error clustering."""

import json

from tracy.ingestion.base import RawRecord
from tracy.ingestion.pipeline import (
    Deduplicator,
    ErrorGrouper,
    Pipeline,
    extract_top_frame_function,
    normalize_message,
)

VALID = {
    "timestamp": "2026-08-14T14:00:00Z",
    "severity": "ERROR",
    "service": "checkout-api",
    "environment": "production",
    "message": "Unhandled exception",
    "error_type": "ZeroDivisionError",
    "request_id": "req-1",
}


def _raw(payload, source: str = "local") -> RawRecord:
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, str):
        payload = payload.encode("utf-8")
    return RawRecord(payload=payload, source=source)


# --- Parsing -----------------------------------------------------------------


def test_valid_json_is_processed():
    result = Pipeline().process(_raw(VALID))
    assert result.event is not None
    assert not result.malformed_json
    assert not result.invalid_schema


def test_malformed_json_is_skipped_not_crashed():
    pipeline = Pipeline()
    result = pipeline.process(_raw(b"not json at all"))
    assert result.malformed_json
    assert result.event is None
    assert pipeline.stats.malformed_json_count == 1


def test_structurally_invalid_json_is_skipped():
    """Valid JSON syntax, but missing a required field."""
    pipeline = Pipeline()
    bad = dict(VALID)
    del bad["severity"]
    result = pipeline.process(_raw(bad))
    assert result.invalid_schema
    assert result.event is None
    assert pipeline.stats.invalid_schema_count == 1


def test_non_object_json_is_skipped():
    pipeline = Pipeline()
    result = pipeline.process(_raw(b"[1, 2, 3]"))
    assert result.invalid_schema


def test_invalid_severity_is_skipped():
    bad = dict(VALID, severity="NOT_A_LEVEL")
    result = Pipeline().process(_raw(bad))
    assert result.invalid_schema


def test_invalid_timestamp_is_skipped():
    bad = dict(VALID, timestamp="not-a-timestamp")
    result = Pipeline().process(_raw(bad))
    assert result.invalid_schema


def test_malformed_then_valid_lines_both_process_correctly():
    """A malformed line must not corrupt or halt processing of the next one."""
    pipeline = Pipeline()
    r1 = pipeline.process(_raw(b"garbage"))
    r2 = pipeline.process(_raw(VALID))
    assert r1.malformed_json
    assert r2.event is not None


# --- LogEvent ------------------------------------------------------------------


def test_required_fields_present_on_log_event():
    event = Pipeline().process(_raw(VALID)).event
    assert event.event_id
    assert event.timestamp
    assert event.severity == "ERROR"
    assert event.service == "checkout-api"
    assert event.message == "Unhandled exception"
    assert event.source == "local"
    assert event.raw_ref


def test_optional_fields_absent_do_not_break_construction():
    minimal = {
        "timestamp": "2026-08-14T14:00:00Z",
        "severity": "INFO",
        "service": "checkout-api",
        "message": "Checkout completed",
    }
    event = Pipeline().process(_raw(minimal)).event
    assert event is not None
    assert event.request_id is None
    assert event.error_type is None
    assert event.stack_trace is None


def test_unknown_and_app_specific_fields_land_in_metadata_not_first_class():
    payload = dict(VALID, product_id="prod-003", quantity=5, endpoint="/checkout", some_future_field="x")
    event = Pipeline().process(_raw(payload)).event
    assert event.metadata["product_id"] == "prod-003"
    assert event.metadata["quantity"] == 5
    assert event.metadata["endpoint"] == "/checkout"
    assert event.metadata["some_future_field"] == "x"
    assert not hasattr(event, "product_id")


def test_source_is_recorded_on_the_event():
    event = Pipeline().process(_raw(VALID, source="local")).event
    assert event.source == "local"


# --- Sanitization ----------------------------------------------------------------


def test_authorization_field_stripped_from_metadata():
    payload = dict(VALID, Authorization="Bearer secret-value")
    event = Pipeline().process(_raw(payload)).event
    assert "Authorization" not in event.metadata
    assert "authorization" not in {k.lower() for k in event.metadata}
    assert "secret-value" not in json.dumps(event.metadata)


def test_cookie_field_stripped():
    payload = dict(VALID, cookie="session=abc123")
    event = Pipeline().process(_raw(payload)).event
    assert not any("cookie" in k.lower() for k in event.metadata)


def test_password_field_stripped():
    payload = dict(VALID, password="hunter2")
    event = Pipeline().process(_raw(payload)).event
    assert not any("password" in k.lower() for k in event.metadata)


def test_token_field_stripped():
    payload = dict(VALID, access_token="abc.def.ghi")
    event = Pipeline().process(_raw(payload)).event
    assert not any("token" in k.lower() for k in event.metadata)


def test_api_key_field_stripped_both_spellings():
    payload = dict(VALID, api_key="sk-123", apiKey="sk-456")
    event = Pipeline().process(_raw(payload)).event
    assert "api_key" not in event.metadata
    assert "apiKey" not in event.metadata


def test_secret_field_stripped():
    payload = dict(VALID, client_secret="shh")
    event = Pipeline().process(_raw(payload)).event
    assert not any("secret" in k.lower() for k in event.metadata)


def test_sanitization_is_case_insensitive():
    payload = dict(VALID, AUTHORIZATION="Bearer x", Password="y")
    event = Pipeline().process(_raw(payload)).event
    assert event.metadata == {}


# --- Deduplication ---------------------------------------------------------------


def test_exact_duplicate_event_id_is_ignored():
    pipeline = Pipeline()
    payload = dict(VALID, event_id="evt-fixed-1")
    first = pipeline.process(_raw(payload))
    second = pipeline.process(_raw(payload))
    assert not first.duplicate
    assert second.duplicate
    assert pipeline.stats.duplicate_count == 1


def test_different_events_sharing_request_id_are_not_treated_as_duplicates():
    """checkout-api emits two log lines per request sharing one request_id
    (its own 'Checkout completed' and 'HTTP request completed' lines). These
    must not collide into a single fallback event_id."""
    pipeline = Pipeline()
    line_a = {
        "timestamp": "2026-08-14T14:00:00Z",
        "severity": "INFO",
        "service": "checkout-api",
        "message": "Checkout completed",
        "request_id": "req-shared",
    }
    line_b = {
        "timestamp": "2026-08-14T14:00:00.500Z",
        "severity": "INFO",
        "service": "checkout-api",
        "message": "HTTP request completed",
        "request_id": "req-shared",
    }
    result_a = pipeline.process(_raw(line_a))
    result_b = pipeline.process(_raw(line_b))
    assert not result_a.duplicate
    assert not result_b.duplicate
    assert result_a.event.event_id != result_b.event.event_id


def test_identical_fallback_identity_is_deduplicated():
    """Two records with no explicit event_id, but identical timestamp/
    service/severity/message/request_id, resolve to the same fallback hash
    and are treated as duplicates -- e.g. the same file line re-read after
    a restart."""
    pipeline = Pipeline()
    first = pipeline.process(_raw(VALID))
    second = pipeline.process(_raw(dict(VALID)))
    assert not first.duplicate
    assert second.duplicate


def test_duplicate_does_not_inflate_error_cluster_count():
    pipeline = Pipeline()
    payload = dict(VALID, event_id="evt-dup-cluster")
    pipeline.process(_raw(payload))
    pipeline.process(_raw(payload))
    clusters = pipeline.grouper.clusters()
    assert len(clusters) == 1
    assert clusters[0].count == 1


def test_deduplicator_is_bounded():
    dedup = Deduplicator(max_entries=2)
    assert not dedup.seen_before("a")
    assert not dedup.seen_before("b")
    assert not dedup.seen_before("c")
    assert len(dedup._seen) <= 2


# --- Error clustering ---------------------------------------------------------------


def test_error_creates_a_cluster():
    result = Pipeline().process(_raw(dict(VALID, severity="ERROR")))
    assert result.cluster is not None
    assert result.cluster.count == 1


def test_critical_creates_a_cluster():
    result = Pipeline().process(_raw(dict(VALID, severity="CRITICAL")))
    assert result.cluster is not None


def test_info_does_not_create_a_cluster():
    payload = dict(VALID, severity="INFO", error_type=None)
    result = Pipeline().process(_raw(payload))
    assert result.cluster is None


def test_warning_does_not_create_a_cluster():
    payload = dict(VALID, severity="WARNING", error_type=None)
    result = Pipeline().process(_raw(payload))
    assert result.cluster is None


def test_repeated_same_error_increments_count():
    pipeline = Pipeline()
    pipeline.process(_raw(dict(VALID, event_id="e1")))
    pipeline.process(_raw(dict(VALID, event_id="e2")))
    pipeline.process(_raw(dict(VALID, event_id="e3")))
    clusters = pipeline.grouper.clusters()
    assert len(clusters) == 1
    assert clusters[0].count == 3


def test_different_request_ids_remain_in_the_same_cluster():
    pipeline = Pipeline()
    pipeline.process(_raw(dict(VALID, event_id="e1", request_id="req-a")))
    pipeline.process(_raw(dict(VALID, event_id="e2", request_id="req-b")))
    assert len(pipeline.grouper.clusters()) == 1


def test_different_stack_trace_line_numbers_remain_in_the_same_cluster():
    pipeline = Pipeline()
    trace_1 = 'File "app/pricing.py", line 14, in calculate_total\nZeroDivisionError: x'
    trace_2 = 'File "app/pricing.py", line 21, in calculate_total\nZeroDivisionError: x'
    pipeline.process(_raw(dict(VALID, event_id="e1", stack_trace=trace_1)))
    pipeline.process(_raw(dict(VALID, event_id="e2", stack_trace=trace_2)))
    assert len(pipeline.grouper.clusters()) == 1
    assert pipeline.grouper.clusters()[0].count == 2


def test_different_endpoints_create_separate_clusters():
    pipeline = Pipeline()
    pipeline.process(_raw(dict(VALID, event_id="e1", endpoint="/checkout")))
    pipeline.process(_raw(dict(VALID, event_id="e2", endpoint="/admin")))
    assert len(pipeline.grouper.clusters()) == 2


def test_different_environments_create_separate_clusters():
    pipeline = Pipeline()
    pipeline.process(_raw(dict(VALID, event_id="e1", environment="production")))
    pipeline.process(_raw(dict(VALID, event_id="e2", environment="staging")))
    assert len(pipeline.grouper.clusters()) == 2


def test_extract_top_frame_function_takes_innermost_frame():
    trace = (
        'File "app/main.py", line 142, in checkout\n'
        '    total_price = calculate_total(...)\n'
        'File "app/pricing.py", line 14, in calculate_total\n'
        "ZeroDivisionError: float division by zero"
    )
    assert extract_top_frame_function(trace) == "calculate_total"


def test_extract_top_frame_function_handles_missing_trace():
    assert extract_top_frame_function(None) == "unknown"


def test_normalize_message_replaces_uuids_numbers_and_quoted_strings():
    message = "Insufficient stock for 'prod-003': requested 999, available 5"
    normalized = normalize_message(message)
    assert "999" not in normalized
    assert "'prod-003'" not in normalized
    assert normalized == "Insufficient stock for <str>: requested #, available #"


def test_normalize_message_handles_uuid():
    message = "order 123e4567-e89b-12d3-a456-426614174000 failed"
    normalized = normalize_message(message)
    assert "<uuid>" in normalized
    assert "123e4567" not in normalized
