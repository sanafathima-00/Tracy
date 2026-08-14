"""In-memory product catalog for checkout-api.

A fixed, hardcoded catalog is intentional: this application has no database.
`prod-003` is seeded with a small stock (5) on purpose -- a later phase will
use it as the deterministic trigger for an intentionally planted incident.
No such bug exists yet; stock here just needs to be small and predictable.
"""

from app.models import Product

PRODUCTS: dict[str, Product] = {
    "prod-001": Product(product_id="prod-001", name="Wireless Mouse", unit_price=19.99, stock=50),
    "prod-002": Product(product_id="prod-002", name="Mechanical Keyboard", unit_price=79.99, stock=30),
    "prod-003": Product(product_id="prod-003", name="USB-C Hub", unit_price=24.99, stock=5),
    "prod-004": Product(product_id="prod-004", name="Webcam", unit_price=49.99, stock=20),
    "prod-005": Product(product_id="prod-005", name="Laptop Stand", unit_price=34.99, stock=15),
}


def get_product(product_id: str) -> Product | None:
    return PRODUCTS.get(product_id)


def has_sufficient_stock(product: Product, quantity: int) -> bool:
    return product.stock >= quantity


def decrement_stock(product_id: str, quantity: int) -> None:
    PRODUCTS[product_id].stock -= quantity
