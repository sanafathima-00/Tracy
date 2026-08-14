"""Tests for Gemini-based incident interpretation. No network, no real API
key, no billing -- every test either exercises pure functions/Pydantic
validation, or injects a fake stand-in for google.genai.Client. This suite
must pass with GEMINI_API_KEY entirely unset."""

import json

import httpx
import pytest
from pydantic import ValidationError

from tracy.detection import IncidentDetector
from tracy.gemini import (
    MAX_MESSAGE_CHARS,
    MAX_STACK_TRACE_CHARS,
    GeminiClient,
    GeminiIncidentAnalysis,
    Hypothesis,
    build_prompt,
)
from tracy.ingestion.base import RawRecord
from tracy.ingestion.pipeline import Pipeline

VALID_ERROR = {
    "timestamp": "2026-08-14T14:00:00Z",
    "severity": "ERROR",
    "service": "checkout-api",
    "environment": "production",
    "message": "Unhandled exception",
    "error_type": "ZeroDivisionError",
    "error_message": "float division by zero",
    "endpoint": "/checkout",
    "stack_trace": (
        'Traceback (most recent call last):\n'
        '  File "app/main.py", line 142, in checkout\n'
        "    total_price = calculate_total(...)\n"
        '  File "app/pricing.py", line 14, in calculate_total\n'
        "ZeroDivisionError: float division by zero"
    ),
}


def _incident_and_event(payload=None, threshold_hits=2):
    """Runs a payload through the real Pipeline + IncidentDetector to get a
    genuinely-constructed Incident/LogEvent pair, the same way __main__.py
    does -- not a hand-built fixture that could drift from the real shape."""
    payload = payload or VALID_ERROR
    pipeline = Pipeline()
    detector = IncidentDetector()
    result = None
    for i in range(threshold_hits):
        raw = RawRecord(payload=json.dumps(dict(payload, event_id=f"e{i}")).encode(), source="local")
        result = pipeline.process(raw)
    incident, _ = detector.check(result)
    return incident, result.event


class _FakeResponse:
    def __init__(self, parsed=None):
        self.parsed = parsed


class _FakeModels:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeClient:
    def __init__(self, side_effects):
        self.models = _FakeModels(side_effects)


class _FakeRetryableError(Exception):
    """Stands in for a google.genai.errors.APIError with a retryable
    HTTP status code, without needing to construct the real SDK exception
    (which requires a full response_json/response object)."""

    def __init__(self, code):
        super().__init__(f"fake error {code}")
        self.code = code


VALID_ANALYSIS = GeminiIncidentAnalysis(
    summary="checkout-api is returning 500s for /checkout.",
    impact_description="Checkout requests for this product fail.",
    symptoms=["HTTP 500 on POST /checkout"],
    observed_facts=["ZeroDivisionError occurred 2 times"],
    hypotheses=[Hypothesis(statement="Division by zero in pricing logic", confidence=0.7)],
    recommended_investigation=["Inspect calculate_total in pricing.py"],
)


# --- Hypothesis / GeminiIncidentAnalysis validation -----------------------------


def test_hypothesis_accepts_valid_confidence():
    h = Hypothesis(statement="x", confidence=0.5)
    assert h.confidence == 0.5


@pytest.mark.parametrize("confidence", [-0.01, 1.01, -1.0, 2.0])
def test_hypothesis_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValidationError):
        Hypothesis(statement="x", confidence=confidence)


def test_gemini_incident_analysis_valid_dict_parses():
    parsed = GeminiIncidentAnalysis.model_validate(
        {
            "summary": "s",
            "impact_description": "i",
            "symptoms": ["a"],
            "observed_facts": ["b"],
            "hypotheses": [{"statement": "c", "confidence": 0.3}],
            "recommended_investigation": ["d"],
        }
    )
    assert parsed.hypotheses[0].confidence == 0.3


def test_gemini_incident_analysis_missing_required_field_fails():
    with pytest.raises(ValidationError):
        GeminiIncidentAnalysis.model_validate({"summary": "s"})


def test_gemini_incident_analysis_has_no_tracy_owned_or_dangerous_fields():
    """Guards the architectural boundary from the design: Gemini's own
    output model must not be able to carry severity, ids, or anything that
    would let it override Tracy's deterministic data or invent evidence
    Tracy never supplied."""
    forbidden = {
        "severity",
        "incident_id",
        "suspected_root_cause",
        "confidence_overall",
        "relevant_commit",
        "relevant_files",
        "deployment_information",
        "incident_title",
    }
    assert forbidden.isdisjoint(GeminiIncidentAnalysis.model_fields.keys())


# --- Prompt construction ------------------------------------------------------


def test_prompt_contains_incident_evidence():
    incident, event = _incident_and_event()
    prompt = build_prompt(incident, event)
    assert incident.service in prompt
    assert incident.severity in prompt
    assert incident.signature in prompt
    assert str(incident.error_cluster.count) in prompt


def test_prompt_contains_representative_event_evidence():
    incident, event = _incident_and_event()
    prompt = build_prompt(incident, event)
    assert "ZeroDivisionError" in prompt
    assert "calculate_total" in prompt
    assert event.error_message in prompt


def test_stack_trace_is_bounded():
    huge_trace = "x" * 50_000
    payload = dict(VALID_ERROR, stack_trace=huge_trace)
    incident, event = _incident_and_event(payload)
    prompt = build_prompt(incident, event)
    # The bound applies to the truncated stack_trace segment, not the whole prompt.
    stack_trace_section = prompt.split("stack_trace:\n", 1)[1]
    assert len(stack_trace_section) <= MAX_STACK_TRACE_CHARS + len("...[truncated]...\n") + 1


def test_stack_trace_truncation_keeps_the_end():
    huge_trace = "START_MARKER" + ("x" * 50_000) + "END_MARKER"
    payload = dict(VALID_ERROR, stack_trace=huge_trace)
    incident, event = _incident_and_event(payload)
    prompt = build_prompt(incident, event)
    assert "END_MARKER" in prompt
    assert "START_MARKER" not in prompt


def test_message_is_bounded():
    # A payload field distinct from `message` avoids the long value also
    # leaking in unbounded via ErrorCluster.signature, which embeds a
    # normalized copy of `message` as part of Phase 2's existing (and here
    # unmodified) clustering logic -- this test is only about the
    # `message:`/`sample_message:` lines this module itself constructs.
    incident, event = _incident_and_event()
    event.message = "y" * 5000  # mutate post-construction, not part of the signature
    prompt = build_prompt(incident, event)
    message_line = next(line for line in prompt.splitlines() if line.startswith("message: "))
    assert len(message_line) <= len("message: ") + MAX_MESSAGE_CHARS + len("...[truncated]")
    assert "...[truncated]" in message_line


def test_secrets_in_metadata_are_not_included_in_prompt():
    payload = dict(VALID_ERROR, Authorization="Bearer super-secret-token", api_key="sk-fake")
    incident, event = _incident_and_event(payload)
    prompt = build_prompt(incident, event)
    assert "super-secret-token" not in prompt
    assert "sk-fake" not in prompt


# --- GeminiClient: success / parsed handling ------------------------------------


def test_successful_response_returns_parsed_analysis():
    incident, event = _incident_and_event()
    fake_client = _FakeClient([_FakeResponse(parsed=VALID_ANALYSIS)])
    client = GeminiClient(client=fake_client)

    result = client.analyze(incident, event)

    assert result is VALID_ANALYSIS
    assert fake_client.models.calls == 1


def test_empty_parsed_response_returns_none_without_raising():
    incident, event = _incident_and_event()
    fake_client = _FakeClient([_FakeResponse(parsed=None)])
    client = GeminiClient(client=fake_client)

    assert client.analyze(incident, event) is None


# --- Missing API key -------------------------------------------------------------


def test_missing_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    incident, event = _incident_and_event()
    client = GeminiClient(client=None)  # forces the real (unconfigured) key path

    assert client.analyze(incident, event) is None


# --- Retry behavior ---------------------------------------------------------------


def test_retryable_failure_then_success(monkeypatch):
    monkeypatch.setattr("tracy.gemini.time.sleep", lambda seconds: None)
    incident, event = _incident_and_event()
    fake_client = _FakeClient([_FakeRetryableError(429), _FakeResponse(parsed=VALID_ANALYSIS)])
    client = GeminiClient(client=fake_client)

    result = client.analyze(incident, event)

    assert result is VALID_ANALYSIS
    assert fake_client.models.calls == 2


def test_persistent_retryable_failure_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("tracy.gemini.time.sleep", lambda seconds: None)
    incident, event = _incident_and_event()
    fake_client = _FakeClient([_FakeRetryableError(503), _FakeRetryableError(503), _FakeRetryableError(503)])
    client = GeminiClient(client=fake_client)

    result = client.analyze(incident, event)

    assert result is None
    assert fake_client.models.calls == 3  # MAX_ATTEMPTS, never exceeded


def test_network_timeout_is_retried(monkeypatch):
    monkeypatch.setattr("tracy.gemini.time.sleep", lambda seconds: None)
    incident, event = _incident_and_event()
    fake_client = _FakeClient([httpx.ConnectTimeout("timed out"), _FakeResponse(parsed=VALID_ANALYSIS)])
    client = GeminiClient(client=fake_client)

    assert client.analyze(incident, event) is VALID_ANALYSIS


def test_non_retryable_failure_does_not_retry():
    incident, event = _incident_and_event()
    fake_client = _FakeClient([_FakeRetryableError(400)])  # 400 is not in the retryable set
    client = GeminiClient(client=fake_client)

    result = client.analyze(incident, event)

    assert result is None
    assert fake_client.models.calls == 1


def test_unexpected_exception_does_not_escape_the_client():
    incident, event = _incident_and_event()
    fake_client = _FakeClient([ValueError("something the SDK never documented")])
    client = GeminiClient(client=fake_client)

    result = client.analyze(incident, event)  # must not raise

    assert result is None
