"""Foundation tests for checkout-api.

Covers only the current phase's behavior. The future intentional production
regression is deliberately not tested here.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_successful_checkout():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-001", "quantity": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["total_price"] > 0
    assert "order_id" in body


def test_unknown_product_returns_404():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "does-not-exist", "quantity": 1},
    )
    assert response.status_code == 404


def test_insufficient_stock_returns_409():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-003", "quantity": 999},
    )
    assert response.status_code == 409


def test_invalid_quantity_returns_422():
    response = client.post(
        "/checkout",
        json={"user_id": "user-123", "product_id": "prod-001", "quantity": 0},
    )
    assert response.status_code == 422
