"""Tests for checkout-api's structured logging: request IDs, request-level
and checkout-level log events, unhandled-exception handling, and the
JSON-per-line shape every log line must have.
"""

import json
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.logging_config import JsonFormatter
from app.main import app

client = TestClient(app)


class _ListHandler(logging.Handler):
    """Captures formatted log lines in memory instead of writing to stdout,
    so tests can assert on exactly what would have been emitted."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def captured_logs():
    handler = _ListHandler()
    logger = logging.getLogger("checkout_api")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def _events(handler: _ListHandler) -> list[dict]:
    return [json.loads(line) for line in handler.lines]


# --- Request ID -------------------------------------------------------------


def test_request_id_generated_when_absent():
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_reused_when_provided():
    response = client.get("/health", headers={"X-Request-ID": "my-custom-id"})
    assert response.headers["X-Request-ID"] == "my-custom-id"


# --- Successful checkout -----------------------------------------------------


def test_successful_checkout_logs_info_event(captured_logs):
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-001", "quantity": 2},
        headers={"X-Request-ID": "req-success-1"},
    )
    assert response.status_code == 200

    checkout_events = [e for e in _events(captured_logs) if e["message"] == "Checkout completed"]
    assert len(checkout_events) == 1
    event = checkout_events[0]
    assert event["severity"] == "INFO"
    assert event["service"] == "checkout-api"
    assert event["environment"]
    assert event["request_id"] == "req-success-1"
    assert event["endpoint"] == "/checkout"
    assert event["http_method"] == "POST"
    assert event["http_status"] == 200
    assert "latency_ms" in event
    assert event["product_id"] == "prod-001"
    assert event["quantity"] == 2
    assert "order_id" in event


# --- Unknown product ----------------------------------------------------------


def test_unknown_product_logs_warning_event(captured_logs):
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "does-not-exist", "quantity": 1},
        headers={"X-Request-ID": "req-404-1"},
    )
    assert response.status_code == 404

    warning_events = [e for e in _events(captured_logs) if e["message"] == "Product not found"]
    assert len(warning_events) == 1
    event = warning_events[0]
    assert event["severity"] == "WARNING"
    assert event["http_status"] == 404
    assert event["product_id"] == "does-not-exist"
    assert event["request_id"] == "req-404-1"


# --- Insufficient stock --------------------------------------------------------


def test_insufficient_stock_logs_warning_event(captured_logs):
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 999},
        headers={"X-Request-ID": "req-409-1"},
    )
    assert response.status_code == 409

    warning_events = [e for e in _events(captured_logs) if e["message"] == "Insufficient stock"]
    assert len(warning_events) == 1
    event = warning_events[0]
    assert event["severity"] == "WARNING"
    assert event["http_status"] == 409
    assert event["product_id"] == "prod-003"
    assert event["quantity"] == 999
    assert event["request_id"] == "req-409-1"


# --- Unexpected exception -------------------------------------------------------


def test_unexpected_exception_returns_generic_500_and_logs_error(captured_logs):
    # TestClient defaults to re-raising server exceptions (raise_server_exceptions=True),
    # which would surface the raw RuntimeError in the test itself instead of letting
    # our registered exception handler produce its response -- disable that here so we
    # can assert on the actual HTTP response the handler returns.
    local_client = TestClient(app, raise_server_exceptions=False)
    with patch("app.main.get_product", side_effect=RuntimeError("simulated failure for testing")):
        response = local_client.post(
            "/checkout",
            json={"user_id": "user-123", "product_id": "prod-001", "quantity": 1},
            headers={"X-Request-ID": "req-500-1"},
        )

    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error", "request_id": "req-500-1"}
    # The client must never see the exception type/message.
    assert "RuntimeError" not in json.dumps(body)
    assert "simulated failure" not in json.dumps(body)
    assert response.headers["X-Request-ID"] == "req-500-1"

    error_events = [e for e in _events(captured_logs) if e["severity"] == "ERROR"]
    assert len(error_events) == 1
    event = error_events[0]
    assert event["error_type"] == "RuntimeError"
    assert event["error_message"] == "simulated failure for testing"
    assert "stack_trace" in event
    assert "RuntimeError" in event["stack_trace"]
    assert event["request_id"] == "req-500-1"
    assert event["http_status"] == 500


# --- Shape: valid, one-event-per-line JSON ---------------------------------------


def test_every_captured_log_line_is_valid_single_line_json(captured_logs):
    client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-002", "quantity": 1},
    )
    assert captured_logs.lines
    for line in captured_logs.lines:
        assert "\n" not in line
        parsed = json.loads(line)  # must not raise
        assert "timestamp" in parsed
        assert "severity" in parsed
        assert "service" in parsed
        assert "environment" in parsed
        assert "message" in parsed


# --- Security: sensitive data never logged ---------------------------------------


def test_authorization_header_and_secrets_never_appear_in_logs(captured_logs):
    client.get("/health", headers={"Authorization": "Bearer super-secret-token-value"})
    for line in captured_logs.lines:
        assert "super-secret-token-value" not in line
        assert "Authorization" not in line
        assert "authorization" not in line
