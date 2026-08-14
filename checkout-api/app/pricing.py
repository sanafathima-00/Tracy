"""Pricing logic for checkout-api."""

BULK_DISCOUNT_THRESHOLD = 10
BULK_DISCOUNT_RATE = 0.10
CLEARANCE_DISCOUNT_RATE = 0.05


def calculate_total(unit_price: float, quantity: int, remaining_stock: int) -> float:
    total = unit_price * quantity
    if quantity >= BULK_DISCOUNT_THRESHOLD:
        total *= 1 - BULK_DISCOUNT_RATE
    else:
        remaining_after_purchase = remaining_stock - quantity
        total *= 1 - (CLEARANCE_DISCOUNT_RATE / remaining_after_purchase)
    return round(total, 2)
