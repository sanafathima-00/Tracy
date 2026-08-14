"""End-to-end local test: LocalLogSource -> Pipeline -> LogEvent -> ErrorCluster,
driven entirely by the fixture file. No GCP, no Gemini, no PostgreSQL, no
live checkout-api process -- this proves the ingestion path works using only
what Phase 2 actually implements.
"""

from pathlib import Path

from tracy.ingestion.local import LocalLogSource
from tracy.ingestion.pipeline import Pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample_logs.jsonl"


def test_fixture_flows_end_to_end_into_events_and_clusters():
    pipeline = Pipeline()
    source = LocalLogSource(FIXTURE, follow=False)

    events = []
    source.listen(lambda raw: events.append((raw, pipeline.process(raw))))

    results = [result for _, result in events]

    # 8 lines in the fixture: 6 valid JSON objects, 1 malformed JSON,
    # 1 structurally invalid (missing severity).
    valid = [r for r in results if r.event is not None]
    assert len(valid) == 6
    assert pipeline.stats.malformed_json_count == 1
    assert pipeline.stats.invalid_schema_count == 1
    assert pipeline.stats.processed_count == 6

    # No accidental duplicates: the two lines sharing request_id="req-100"
    # have different messages/timestamps and must both survive.
    assert pipeline.stats.duplicate_count == 0

    # The two ZeroDivisionError lines (different request_id, different stack
    # trace line numbers) must collapse into exactly one cluster.
    clusters = pipeline.grouper.clusters()
    assert len(clusters) == 1
    assert clusters[0].count == 2
    assert clusters[0].severity == "ERROR"
    assert "checkout-api" in clusters[0].signature
    assert "calculate_total" in clusters[0].signature

    # The WARNING and the two INFO lines must not have produced clusters.
    non_error_results = [
        r for r in results if r.event is not None and r.event.severity in ("INFO", "WARNING")
    ]
    assert len(non_error_results) == 4
    assert all(r.cluster is None for r in non_error_results)

    # The sanitization-test line's secrets must never have reached any event.
    sanitized_event = next(r.event for r in valid if r.event.service == "some-other-future-producer")
    assert "Authorization" not in sanitized_event.metadata
    assert "api_key" not in sanitized_event.metadata
    assert sanitized_event.metadata.get("user") == "someone"  # non-secret fields survive


def test_fixture_regression_lines_are_individually_correct():
    """Spot-check the two real regression-shaped lines specifically."""
    pipeline = Pipeline()
    source = LocalLogSource(FIXTURE, follow=False)

    error_events = []

    def on_message(raw):
        result = pipeline.process(raw)
        if result.event is not None and result.event.severity == "ERROR":
            error_events.append(result.event)

    source.listen(on_message)

    assert len(error_events) == 2
    for event in error_events:
        assert event.error_type == "ZeroDivisionError"
        assert event.service == "checkout-api"
        assert "pricing.py" in event.stack_trace
        assert event.metadata["endpoint"] == "/checkout"
        assert event.metadata["http_status"] == 500
