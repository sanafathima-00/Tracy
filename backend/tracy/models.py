"""Canonical, source-agnostic models produced by Tracy's ingestion pipeline.

See openspec/changes/establish-incident-response-workflow/design.md's "Entity
abstractions" section for the original sketch (timestamp, service, severity,
message, raw_ref for LogEvent; signature, count, first_seen, last_seen,
sample_message, severity for ErrorCluster). `event_id` and `source` are
additions this phase needs for deduplication and multi-source support --
extensions of that sketch, not a departure from it.

ErrorCluster's fields intentionally match incident-package.schema.json's
error_clusters[] shape exactly. That schema is not modified or duplicated
here -- this is the internal model that eventually feeds it.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]

# "gcp" is not implemented in this phase (no google-cloud-* imports exist
# anywhere in this package) -- it is declared here only so LogEvent's shape
# does not need to change when GCPLogSource is eventually built.
SourceName = Literal["local", "gcp"]


class LogEvent(BaseModel):
    """One normalized log line, regardless of which LogSource produced it."""

    # Canonical / required
    event_id: str
    timestamp: datetime
    severity: Severity
    service: str
    message: str
    source: SourceName
    raw_ref: str

    # Optional, well-known
    environment: str | None = None
    version: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    stack_trace: str | None = None

    # Producer-specific context (e.g. checkout-api's product_id/quantity/
    # order_id/http_method/endpoint/http_status/latency_ms) lives here, never
    # as first-class fields -- this is what keeps LogEvent provider-agnostic.
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorCluster(BaseModel):
    """A deduplicated group of LogEvents sharing an error signature.

    Only ERROR/CRITICAL LogEvents are ever clustered -- see
    ingestion/pipeline.py's ErrorGrouper.
    """

    signature: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_message: str
    severity: Severity
