"""Tests for tracy/implement_cli.py -- the manual tracy-implement trigger.
No real network calls: GitHubDispatcher.dispatch_implementation is
monkeypatched throughout."""

import json
import sys

import pytest

from tracy import implement_cli
from tracy.github_dispatch import DispatchResult

VALID_PACKAGE = {
    "incident_id": "cli-test-incident",
    "schema_version": "1.1",
    "severity": "high",
    "detected_at": "2026-08-15T00:00:06Z",
    "service": "checkout-api",
    "summary": "checkout-api checkout requests are failing with ZeroDivisionError.",
    "observed_facts": [],
    "confidence_overall": 0.9,
}

AUTHORIZED_RESULT = {
    "incident_id": "cli-test-incident",
    "hypothesis_assessments": [
        {
            "statement": "remaining_after_purchase reached zero",
            "tracy_confidence": 0.9,
            "verdict": "confirmed",
            "evidence": ["checkout-api/app/pricing.py:14"],
        }
    ],
    "validated_root_cause": "Division by zero when quantity equals remaining stock",
    "root_cause_evidence": ["checkout-api/app/pricing.py:14"],
    "planning_path": "lightweight",
    "planning_path_reason": "small, localized fix",
}


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_authorized_result_dispatches(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch_implementation",
        lambda self, package, result: calls.append((package, result)) or DispatchResult(True, 204, "dispatched"),
    )
    package_file = _write(tmp_path, "package.json", VALID_PACKAGE)
    result_file = _write(tmp_path, "result.json", AUTHORIZED_RESULT)
    monkeypatch.setattr(sys, "argv", ["implement_cli", str(package_file), str(result_file)])

    implement_cli.main()

    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "[DISPATCHED]" in captured.out


def test_unauthorized_result_does_not_dispatch(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch_implementation",
        lambda self, package, result: calls.append((package, result)) or DispatchResult(True, 204, "dispatched"),
    )
    refuted_result = dict(AUTHORIZED_RESULT, hypothesis_assessments=[
        {"statement": "x", "tracy_confidence": 0.9, "verdict": "refuted", "evidence": []}
    ])
    package_file = _write(tmp_path, "package.json", VALID_PACKAGE)
    result_file = _write(tmp_path, "result.json", refuted_result)
    monkeypatch.setattr(sys, "argv", ["implement_cli", str(package_file), str(result_file)])

    with pytest.raises(SystemExit) as exc_info:
        implement_cli.main()

    assert exc_info.value.code == 1
    assert calls == []
    captured = capsys.readouterr()
    assert "authorized=False" in captured.out
    assert "[NOT DISPATCHED]" in captured.out


def test_mismatched_incident_id_does_not_dispatch(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch_implementation",
        lambda self, package, result: calls.append((package, result)) or DispatchResult(True, 204, "dispatched"),
    )
    mismatched_result = dict(AUTHORIZED_RESULT, incident_id="some-other-incident")
    package_file = _write(tmp_path, "package.json", VALID_PACKAGE)
    result_file = _write(tmp_path, "result.json", mismatched_result)
    monkeypatch.setattr(sys, "argv", ["implement_cli", str(package_file), str(result_file)])

    with pytest.raises(SystemExit) as exc_info:
        implement_cli.main()

    assert exc_info.value.code == 1
    assert calls == []
    captured = capsys.readouterr()
    assert "mismatch" in captured.err


def test_dispatch_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "tracy.github_dispatch.GitHubDispatcher.dispatch_implementation",
        lambda self, package, result: DispatchResult(False, None, "TRACY_GITHUB_TOKEN is not set"),
    )
    package_file = _write(tmp_path, "package.json", VALID_PACKAGE)
    result_file = _write(tmp_path, "result.json", AUTHORIZED_RESULT)
    monkeypatch.setattr(sys, "argv", ["implement_cli", str(package_file), str(result_file)])

    with pytest.raises(SystemExit) as exc_info:
        implement_cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[NOT DISPATCHED]" in captured.err
