"""Tests for --dispatch wiring in tracy/__main__.py. No real network calls
-- GeminiClient.analyze is stubbed to always return None (so no Gemini call
is ever attempted regardless of ambient GEMINI_API_KEY), and
GitHubDispatcher.dispatch is monkeypatched to record calls instead of
touching the network."""

import sys
from pathlib import Path

import pytest

from tracy import __main__ as tracy_main
from tracy.github_dispatch import DispatchResult

FIXTURE = Path(__file__).parent / "fixtures" / "sample_logs.jsonl"

VALID_ERROR = (
    '{{"timestamp": "2026-08-14T14:00:0{i}Z", "severity": "ERROR", "service": "checkout-api", '
    '"environment": "production", "message": "Unhandled exception", "error_type": "ZeroDivisionError", '
    '"endpoint": "/checkout", "event_id": "cli-test-{i}"}}'
)


@pytest.fixture(autouse=True)
def _no_real_gemini_call(monkeypatch):
    """Guarantees zero real Gemini API calls in this file regardless of
    whether an ambient GEMINI_API_KEY happens to be set in the environment."""
    monkeypatch.setattr("tracy.gemini.GeminiClient.analyze", lambda self, incident, event: None)


def _repeated_error_fixture(tmp_path, occurrences=3):
    path = tmp_path / "repeated.jsonl"
    lines = [VALID_ERROR.format(i=i) for i in range(occurrences)]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_without_dispatch_flag_no_github_call_is_made(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch",
        lambda self, package: calls.append(package) or DispatchResult(True, 204, "x"),
    )
    monkeypatch.setattr(sys, "argv", ["tracy", str(FIXTURE)])

    tracy_main.main()

    assert calls == []


def test_dispatch_flag_dispatches_the_new_incident(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch",
        lambda self, package: calls.append(package) or DispatchResult(True, 204, "x"),
    )
    monkeypatch.setattr(sys, "argv", ["tracy", str(FIXTURE), "--dispatch"])

    tracy_main.main()

    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "[DISPATCHED]" in captured.out


def test_repeated_occurrences_of_the_same_incident_dispatch_only_once(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch",
        lambda self, package: calls.append(package) or DispatchResult(True, 204, "x"),
    )
    fixture = _repeated_error_fixture(tmp_path, occurrences=3)
    monkeypatch.setattr(sys, "argv", ["tracy", str(fixture), "--dispatch"])

    tracy_main.main()

    # 3 occurrences of the same signature: 1st is below threshold (no
    # incident yet), 2nd crosses the threshold (is_new=True -> one dispatch),
    # 3rd is a repeat (is_new=False -> returns before ever reaching dispatch).
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert captured.out.count("[DISPATCHED]") == 1
    assert "[incident updated]" in captured.out
