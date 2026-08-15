"""Tests for GitHub repository_dispatch integration. No real network calls
-- tracy.github_dispatch._send_request is monkeypatched throughout. This
suite must pass with TRACY_GITHUB_TOKEN/TRACY_GITHUB_REPOSITORY entirely
unset and no network access."""

import json
import urllib.error

import pytest

from tracy.detection import IncidentDetector
from tracy.gemini import GeminiIncidentAnalysis, Hypothesis
from tracy.github_dispatch import EVENT_TYPE, DispatchResult, GitHubDispatcher
from tracy.incident_package import IncidentPackageBuilder
from tracy.ingestion.base import RawRecord
from tracy.ingestion.pipeline import Pipeline

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


def _package(payload=None, event_id_prefix="e"):
    payload = payload or VALID_ERROR
    pipeline = Pipeline()
    detector = IncidentDetector()
    result = None
    for i in range(2):
        raw = RawRecord(payload=json.dumps(dict(payload, event_id=f"{event_id_prefix}{i}")).encode(), source="local")
        result = pipeline.process(raw)
    incident, _ = detector.check(result)
    return IncidentPackageBuilder().build(incident, result.event, ANALYSIS)


def _set_config(monkeypatch, token="ghp_fake_token_value", repo="someone/somerepo"):
    if token is None:
        monkeypatch.delenv("TRACY_GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRACY_GITHUB_TOKEN", token)
    if repo is None:
        monkeypatch.delenv("TRACY_GITHUB_REPOSITORY", raising=False)
    else:
        monkeypatch.setenv("TRACY_GITHUB_REPOSITORY", repo)


class _Recorder:
    """Captures every call to _send_request without touching the network."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": dict(headers), "body": body})
        effect = self._responses.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _http_error(code):
    return urllib.error.HTTPError(
        url="https://api.github.com/repos/someone/somerepo/dispatches",
        code=code,
        msg="error",
        hdrs=None,
        fp=None,
    )


# --- Successful dispatch / payload shape ----------------------------------------


def test_successful_dispatch(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is True
    assert result.status_code == 204
    assert len(recorder.calls) == 1


def test_correct_url_and_event_type(monkeypatch):
    _set_config(monkeypatch, repo="acme/widgets")
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    GitHubDispatcher().dispatch(_package())

    call = recorder.calls[0]
    assert call["url"] == "https://api.github.com/repos/acme/widgets/dispatches"
    sent = json.loads(call["body"])
    assert sent["event_type"] == EVENT_TYPE == "tracy-investigate"


def test_incident_package_wrapped_under_single_top_level_key(monkeypatch):
    """client_payload must have exactly one top-level property -- GitHub
    caps client_payload at 10, and IncidentPackage has far more fields than
    that."""
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    GitHubDispatcher().dispatch(package)

    sent = json.loads(recorder.calls[0]["body"])
    assert list(sent["client_payload"].keys()) == ["incident_package"]
    assert len(sent["client_payload"]) == 1


def test_package_serialized_through_to_schema_dict(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    GitHubDispatcher().dispatch(package)

    sent = json.loads(recorder.calls[0]["body"])
    assert sent["client_payload"]["incident_package"] == package.to_schema_dict()


def test_existing_package_fields_preserved_in_payload(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    package = _package()

    GitHubDispatcher().dispatch(package)

    sent_package = json.loads(recorder.calls[0]["body"])["client_payload"]["incident_package"]
    assert sent_package["incident_id"] == package.incident_id
    assert sent_package["severity"] == package.severity
    assert sent_package["hypotheses"][0]["statement"] == ANALYSIS.hypotheses[0].statement


# --- Missing / invalid configuration -----------------------------------------------


def test_missing_token_returns_failure_without_network_call(monkeypatch):
    _set_config(monkeypatch, token=None)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is False
    assert "TRACY_GITHUB_TOKEN" in result.message
    assert len(recorder.calls) == 0


@pytest.mark.parametrize("bad_repo", [None, "", "no-slash-here", "/missing-owner", "missing-name/"])
def test_missing_or_invalid_repository_returns_failure(monkeypatch, bad_repo):
    _set_config(monkeypatch, repo=bad_repo)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is False
    assert len(recorder.calls) == 0


# --- Retry behavior ----------------------------------------------------------------


def test_authentication_failure_does_not_retry(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([_http_error(401)])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is False
    assert result.status_code == 401
    assert len(recorder.calls) == 1


def test_forbidden_does_not_retry(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([_http_error(403)])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is False
    assert len(recorder.calls) == 1


def test_transient_failure_retries_then_succeeds(monkeypatch):
    _set_config(monkeypatch)
    monkeypatch.setattr("tracy.github_dispatch.time.sleep", lambda seconds: None)
    recorder = _Recorder([_http_error(503), 204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is True
    assert len(recorder.calls) == 2


def test_persistent_transient_failure_eventually_returns_failure(monkeypatch):
    _set_config(monkeypatch)
    monkeypatch.setattr("tracy.github_dispatch.time.sleep", lambda seconds: None)
    recorder = _Recorder([_http_error(503), _http_error(503), _http_error(503)])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is False
    assert len(recorder.calls) == 3  # MAX_ATTEMPTS, never exceeded


def test_network_error_retries(monkeypatch):
    _set_config(monkeypatch)
    monkeypatch.setattr("tracy.github_dispatch.time.sleep", lambda seconds: None)
    recorder = _Recorder([urllib.error.URLError("connection refused"), 204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert result.success is True
    assert len(recorder.calls) == 2


# --- Secrets never leak -----------------------------------------------------------


def test_token_never_appears_in_payload_body(monkeypatch):
    secret_token = "ghp_super_secret_value_12345"
    _set_config(monkeypatch, token=secret_token)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    GitHubDispatcher().dispatch(_package())

    assert secret_token not in recorder.calls[0]["body"].decode("utf-8")


def test_token_appears_only_in_authorization_header_not_elsewhere(monkeypatch):
    secret_token = "ghp_super_secret_value_12345"
    _set_config(monkeypatch, token=secret_token)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    GitHubDispatcher().dispatch(_package())

    headers = recorder.calls[0]["headers"]
    assert headers["Authorization"] == f"Bearer {secret_token}"
    non_auth_values = json.dumps({k: v for k, v in headers.items() if k != "Authorization"})
    assert secret_token not in non_auth_values


def test_token_never_appears_in_result_message(monkeypatch):
    secret_token = "ghp_super_secret_value_12345"
    _set_config(monkeypatch, token=secret_token)
    recorder = _Recorder([_http_error(500), _http_error(500), _http_error(500)])
    monkeypatch.setattr("tracy.github_dispatch.time.sleep", lambda seconds: None)
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)

    result = GitHubDispatcher().dispatch(_package())

    assert secret_token not in result.message


def test_missing_token_error_message_names_the_variable_not_a_value(monkeypatch):
    _set_config(monkeypatch, token=None)

    result = GitHubDispatcher().dispatch(_package())

    assert "TRACY_GITHUB_TOKEN" in result.message
    assert "ghp_" not in result.message  # no accidental token-shaped value


# --- Duplicate incident dedup -------------------------------------------------------


def test_duplicate_incident_id_is_not_dispatched_twice(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    dispatcher = GitHubDispatcher()
    package = _package()

    first = dispatcher.dispatch(package)
    second = dispatcher.dispatch(package)

    assert first.success is True
    assert second.success is False
    assert "already dispatched" in second.message
    assert len(recorder.calls) == 1  # the second call never touched the network


def test_different_incident_ids_are_both_dispatched(monkeypatch):
    _set_config(monkeypatch)
    recorder = _Recorder([204, 204])
    monkeypatch.setattr("tracy.github_dispatch._send_request", recorder)
    dispatcher = GitHubDispatcher()

    package_a = _package(dict(VALID_ERROR, error_type="ZeroDivisionError"), event_id_prefix="a")
    package_b = _package(dict(VALID_ERROR, error_type="KeyError"), event_id_prefix="b")
    assert package_a.incident_id != package_b.incident_id

    result_a = dispatcher.dispatch(package_a)
    result_b = dispatcher.dispatch(package_b)

    assert result_a.success is True
    assert result_b.success is True
    assert len(recorder.calls) == 2
