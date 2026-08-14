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

`Incident` (Phase 3) is a deliberately small subset of design.md's eventual
Postgres `Incident` row and of incident-package.schema.json's full
IncidentPackage: it carries only what a deterministic rule can assert
without judgment (see backend/tracy/detection.py). Everything
Gemini-authored -- summary, impact, hypotheses, suspected_root_cause,
recommended_investigation, and the rest -- is absent on purpose. Grow this
model with additive optional fields in later phases; do not replace it with
a differently-named class, or the two "Incident" concepts will need
reconciling later.
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


# The business-impact scale incident-package.schema.json's top-level
# `severity` (and its `error_clusters[].severity`) actually uses -- distinct
# from LogEvent/ErrorCluster's log-level Severity above. The two are easy to
# conflate because both are called "severity"; see detection.py's
# map_severity for the deterministic translation between them.
IncidentSeverity = Literal["critical", "high", "medium", "low"]


class Incident(BaseModel):
    """A deterministically detected, incident-worthy ErrorCluster.

    One Incident per qualifying signature (see detection.py's IncidentStore)
    -- not a merge of multiple signatures, and not built from semantic
    similarity. `service`/`environment`/`affected_component` are read from
    the triggering LogEvent, never parsed out of ErrorCluster.signature:
    ErrorCluster does not expose those as structured fields today.
    """

    incident_id: str
    signature: str
    detected_at: datetime
    service: str
    environment: str | None = None
    affected_component: str | None = None
    severity: IncidentSeverity
    error_cluster: ErrorCluster
