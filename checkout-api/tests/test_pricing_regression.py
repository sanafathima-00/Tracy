"""Documents a real, currently-present production regression in checkout-api.

`calculate_total` (app/pricing.py) applies a clearance discount to any order
below the bulk-discount threshold, sized by how much stock would remain
after the purchase. When a purchase would exhaust the remaining stock
exactly, that calculation divides by zero.

This file intentionally contains tests with two different outcomes:
- Tests documenting *current* (buggy) behavior, which pass today.
- One test documenting the *correct* behavior once fixed, marked `xfail`
  because it does not pass today. Once the regression is fixed, this test
  should start passing -- `strict=True` means an unexpected pass is itself
  reported as a failure, forcing the `xfail` marker to be removed as part
  of the fix rather than silently left behind.

Do not fix the underlying bug to make this file fully green -- that is a
separate, later task.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.logging_config import JsonFormatter
from app.main import app

# raise_server_exceptions=False: most tests in this file expect to observe
# the actual 500 response our exception handler produces, not have the
# underlying exception re-raised into the test (TestClient's default).
client = TestClient(app, raise_server_exceptions=False)


class _ListHandler(logging.Handler):
    """Captures formatted log lines in memory for assertion."""

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


# --- Sanity: healthy behavior is unaffected ---------------------------------


def test_healthy_checkout_still_succeeds():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-002", "quantity": 1},
    )
    assert response.status_code == 200


def test_existing_validation_behavior_unaffected():
    assert client.post(
        "/checkout", json={"user_id": "user-123", "product_id": "prod-001", "quantity": 0}
    ).status_code == 422
    assert client.post(
        "/checkout", json={"user_id": "user-123", "product_id": "does-not-exist", "quantity": 1}
    ).status_code == 404
    assert client.post(
        "/checkout", json={"user_id": "user-123", "product_id": "prod-003", "quantity": 999}
    ).status_code == 409


def test_regression_produces_structured_error_log(captured_logs):
    """The real regression (not a mocked exception) must go through the same
    structured-logging path as any other unhandled exception."""
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 5},
        headers={"X-Request-ID": "regression-log-check"},
    )
    assert response.status_code == 500

    error_events = [json.loads(line) for line in captured_logs.lines if json.loads(line)["severity"] == "ERROR"]
    assert len(error_events) == 1
    event = error_events[0]
    assert event["service"] == "checkout-api"
    assert event["environment"]
    assert event["request_id"] == "regression-log-check"
    assert event["endpoint"] == "/checkout"
    assert event["http_method"] == "POST"
    assert event["http_status"] == 500
    assert event["error_type"] == "ZeroDivisionError"
    assert "error_message" in event
    assert "stack_trace" in event
    assert "pricing.py" in event["stack_trace"]
    assert "timestamp" in event
    # No secret/credential-shaped content anywhere in any line for this request.
    for line in captured_logs.lines:
        assert "Authorization" not in line and "password" not in line.lower()


# --- Current (buggy) behavior: documents the regression as it exists today --


def test_regression_exact_remaining_stock_currently_returns_500():
    """prod-003 is seeded with stock=5. Buying exactly 5 crashes pricing."""
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 5},
        headers={"X-Request-ID": "regression-check-1"},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "request_id": "regression-check-1"}


def test_regression_is_deterministic_across_repeated_attempts():
    """The same request must reliably fail, not just once. The exception
    occurs before stock is decremented, so repeating it doesn't "use up"
    the failure -- it should reproduce every time."""
    for _ in range(3):
        response = client.post(
            "/checkout",
            json={"user_id": "user-123", "product_id": "prod-003", "quantity": 5},
        )
        assert response.status_code == 500


def test_partial_purchase_below_remaining_stock_still_succeeds():
    """A purchase that does not exhaust remaining stock must not crash -- the
    defect is specific to the exact-exhaustion case, not the clearance
    pricing path in general. Uses a different product than the exhaustion
    tests above so it doesn't mutate prod-003's stock and affect them."""
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-004", "quantity": 3},
    )
    assert response.status_code == 200


# --- Expected behavior once fixed -------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known regression in app/pricing.py: buying exactly a product's "
        "remaining stock divides by zero. Remove this xfail once fixed."
    ),
)
def test_buying_exact_remaining_stock_should_eventually_succeed():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 5},
    )
    assert response.status_code == 200
