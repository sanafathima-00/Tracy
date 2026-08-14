"""In-memory order storage for checkout-api.

Orders exist only for the lifetime of the running process. No database,
no persistence -- this is intentional.
"""

import uuid

from app.models import Order

ORDERS: dict[str, Order] = {}


def create_order(user_id: str, product_id: str, quantity: int, total_price: float) -> Order:
    order = Order(
        order_id=str(uuid.uuid4()),
        user_id=user_id,
        product_id=product_id,
        quantity=quantity,
        total_price=total_price,
    )
    ORDERS[order.order_id] = order
    return order


def get_order(order_id: str) -> Order | None:
    return ORDERS.get(order_id)
