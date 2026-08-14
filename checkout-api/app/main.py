"""FastAPI application for checkout-api.

Structured logging is implemented here: every request gets a request ID,
every request produces one request-level log line, checkout produces
additional business-level log lines, and unhandled exceptions are caught,
logged with a stack trace, and turned into a safe generic 500 response.

The intentional production regression and any external integration (GCP,
Tracy, Codex) remain explicitly out of scope for this phase.
"""

import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.catalog import decrement_stock, get_product, has_sufficient_stock
from app.logging_config import configure_logging, request_id_ctx_var
from app.models import CheckoutRequest, CheckoutResponse
from app.orders import create_order
from app.pricing import calculate_total

logger = configure_logging()

app = FastAPI(title="checkout-api")


def charge_payment(user_id: str, amount: float) -> bool:
    """Stubbed payment call. Always succeeds. Makes no external call."""
    return True


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Assigns/reuses a request ID for the duration of the request, and logs
    exactly one request-level line per request (success or failure) -- the
    access-log equivalent, distinct from checkout's own business-level logs.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # Stored on request.state too: BaseHTTPMiddleware runs the downstream app
    # in a separate task, and this contextvar does not reliably survive into
    # that task's context for a later exception handler to read. request.state
    # is the same Request object throughout, so it's the reliable channel.
    request.state.request_id = request_id
    token = request_id_ctx_var.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "HTTP request completed",
            extra={
                "http_method": request.method,
                "endpoint": request.url.path,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response
    finally:
        request_id_ctx_var.reset(token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches anything a route didn't handle itself, logs it with a stack
    trace, and returns a generic, safe response -- the client never sees the
    exception message or traceback.
    """
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )
    # Re-set explicitly: see the comment in request_context_middleware --
    # this handler may run in a different task context than the middleware,
    # so the formatter needs the contextvar set again in *this* context.
    request_id_ctx_var.set(request_id)
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        extra={
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "http_method": request.method,
            "endpoint": request.url.path,
            "http_status": 500,
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/checkout", response_model=CheckoutResponse)
def checkout(request: CheckoutRequest) -> CheckoutResponse:
    start = time.perf_counter()

    product = get_product(request.product_id)
    if product is None:
        logger.warning(
            "Product not found",
            extra={
                "product_id": request.product_id,
                "http_method": "POST",
                "endpoint": "/checkout",
                "http_status": 404,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        raise HTTPException(status_code=404, detail=f"Product '{request.product_id}' not found")

    if not has_sufficient_stock(product, request.quantity):
        logger.warning(
            "Insufficient stock",
            extra={
                "product_id": request.product_id,
                "quantity": request.quantity,
                "http_method": "POST",
                "endpoint": "/checkout",
                "http_status": 409,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient stock for '{request.product_id}': "
                f"requested {request.quantity}, available {product.stock}"
            ),
        )

    total_price = calculate_total(product.unit_price, request.quantity)

    charge_payment(request.user_id, total_price)

    decrement_stock(request.product_id, request.quantity)
    order = create_order(
        user_id=request.user_id,
        product_id=request.product_id,
        quantity=request.quantity,
        total_price=total_price,
    )

    logger.info(
        "Checkout completed",
        extra={
            "product_id": request.product_id,
            "quantity": request.quantity,
            "order_id": order.order_id,
            "http_method": "POST",
            "endpoint": "/checkout",
            "http_status": 200,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        },
    )

    return CheckoutResponse(order_id=order.order_id, total_price=order.total_price, status=order.status)
