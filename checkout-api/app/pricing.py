"""Pricing logic for checkout-api.

Kept isolated in its own module on purpose: a later phase will intentionally
introduce a production regression here for Tracy/Codex to investigate. This
version is correct and deterministic -- no regression exists yet.
"""

BULK_DISCOUNT_THRESHOLD = 10
BULK_DISCOUNT_RATE = 0.10


def calculate_total(unit_price: float, quantity: int) -> float:
    total = unit_price * quantity
    if quantity >= BULK_DISCOUNT_THRESHOLD:
        total *= 1 - BULK_DISCOUNT_RATE
    return round(total, 2)
