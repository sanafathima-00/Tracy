"""Pydantic models for checkout-api."""

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)


class Product(BaseModel):
    product_id: str
    name: str
    unit_price: float
    stock: int


class Order(BaseModel):
    order_id: str
    user_id: str
    product_id: str
    quantity: int
    total_price: float
    status: str = "confirmed"


class CheckoutResponse(BaseModel):
    order_id: str
    total_price: float
    status: str
