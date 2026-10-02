"""Regression coverage for checkout-api clearance pricing.

`calculate_total` (app/pricing.py) applies a clearance discount to any order
below the bulk-discount threshold, sized by how much stock would remain
after the purchase. An exact-stock purchase must use the maximum clearance
discount instead of dividing by zero.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.pricing import calculate_total

# Keep server exceptions in HTTP responses so endpoint regressions are observed
# through the same boundary as production callers.
client = TestClient(app, raise_server_exceptions=False)


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


def test_exact_remaining_stock_uses_maximum_clearance_discount():
    assert calculate_total(unit_price=24.99, quantity=5, remaining_stock=5) == 118.7


def test_buying_exact_remaining_stock_succeeds():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 5},
    )
    assert response.status_code == 200
