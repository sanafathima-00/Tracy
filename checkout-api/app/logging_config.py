"""Structured JSON logging for checkout-api.

Every application log entry is a single-line JSON object written to stdout,
shaped so a future Cloud Logging pipeline (via Tracy's production-log-ingestion
capability) can parse it directly. No third-party logging dependency is used
-- this is Python's standard `logging` module plus a small formatter.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

SERVICE_NAME = os.environ.get("SERVICE_NAME", "checkout-api")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "local")

# Set by request middleware for the duration of one request; read by the
# formatter so route code never has to thread request_id through every log
# call by hand.
request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Explicit whitelist of fields a log call may attach via `extra={...}`.
# Anything not in this list is silently dropped -- this is what makes "only
# log what we explicitly decided to log" true, rather than aspirational.
_EXTRA_FIELDS = (
    "http_method",
    "endpoint",
    "http_status",
    "latency_ms",
    "product_id",
    "quantity",
    "order_id",
    "error_type",
    "error_message",
)

# Defense in depth on top of the whitelist above: if any of these names ever
# ended up in `extra` by mistake, they are stripped before the line is ever
# written, not just "not expected to be there".
_FORBIDDEN_FIELDS = {
    "authorization",
    "cookie",
    "password",
    "api_key",
    "token",
    "secret",
}


class JsonFormatter(logging.Formatter):
    """Renders one LogRecord as one single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": _iso_timestamp(record.created),
            "severity": record.levelname,
            "service": SERVICE_NAME,
            "environment": ENVIRONMENT,
            "version": SERVICE_VERSION,
            "message": record.getMessage(),
        }

        request_id = request_id_ctx_var.get()
        if request_id:
            payload["request_id"] = request_id

        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)

        for forbidden in _FORBIDDEN_FIELDS:
            payload.pop(forbidden, None)

        return json.dumps(payload, default=str)


def _iso_timestamp(epoch_seconds: float) -> str:
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return checkout-api's application logger.

    Deliberately scoped to a named logger, not the root logger: reconfiguring
    uvicorn's own access/error loggers is a known source of ordering bugs
    (uvicorn reconfigures its own loggers again during server startup), and
    is out of scope here -- this only guarantees that checkout-api's own
    application log lines are structured JSON, one per line.
    """
    logger = logging.getLogger("checkout_api")
    logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
