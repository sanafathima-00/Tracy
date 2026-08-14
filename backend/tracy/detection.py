"""Deterministic incident detection: decides when an ErrorCluster is
incident-worthy, and prevents duplicate Incidents for the same underlying
signature.

    PipelineResult{event, cluster} -> IncidentDetector.check() -> (Incident, is_new) | None

No LLM, no statistical/rate/baseline detection here -- see
openspec/changes/establish-incident-response-workflow/tasks.md's Phase 3
section for what's deferred and why. This module never imports from or
modifies ingestion/pipeline.py's classes; it only reads the PipelineResult
they already produce.
"""

import threading
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from tracy.ingestion.pipeline import PipelineResult
from tracy.models import ErrorCluster, Incident, IncidentSeverity, Severity

# A repeated occurrence of the *same* signature is incident-worthy at this
# count. 2, not some larger "safety margin" number: checkout-api's real
# regression already reproduces the identical error twice deterministically
# (see backend/README.md's demo steps), so 2 is what the only real signal
# available today actually supports -- not an arbitrary choice.
REPEATED_ERROR_THRESHOLD = 2

# A single CRITICAL-severity error doesn't need to repeat to matter.
CRITICAL_THRESHOLD = 1

# Deterministic log-severity -> incident-severity translation. The two scales
# are easy to conflate (both called "severity") but are not the same thing --
# see the note above IncidentSeverity in models.py. Total over every log
# severity for correctness, even though Pipeline's CLUSTERABLE_SEVERITIES
# means only CRITICAL/ERROR ever reach this function in practice today.
_SEVERITY_MAP: dict[Severity, IncidentSeverity] = {
    "CRITICAL": "critical",
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "DEBUG": "low",
}


def map_severity(log_severity: Severity) -> IncidentSeverity:
    return _SEVERITY_MAP[log_severity]


def _threshold_for(severity: Severity) -> int:
    return CRITICAL_THRESHOLD if severity == "CRITICAL" else REPEATED_ERROR_THRESHOLD


class IncidentStore:
    """In-memory dict[signature, Incident] -- the same pattern
    ingestion/pipeline.py's ErrorGrouper already uses for its own dict, not
    PostgreSQL. Incidents do not survive a process restart, matching the
    existing accepted limitation of Deduplicator/ErrorGrouper.
    """

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._lock = threading.Lock()

    def get(self, signature: str) -> Incident | None:
        with self._lock:
            return self._incidents.get(signature)

    def record(
        self,
        signature: str,
        cluster: ErrorCluster,
        build: Callable[[], Incident],
    ) -> tuple[Incident, bool]:
        """Get-or-create, atomically: if an Incident already exists for this
        signature, its `error_cluster` snapshot is refreshed in place and
        `is_new=False` is returned. Otherwise `build()` constructs a new one.
        `incident_id` is never regenerated once assigned.
        """
        with self._lock:
            existing = self._incidents.get(signature)
            if existing is not None:
                updated = existing.model_copy(update={"error_cluster": cluster})
                self._incidents[signature] = updated
                return updated, False
            incident = build()
            self._incidents[signature] = incident
            return incident, True

    def all(self) -> list[Incident]:
        with self._lock:
            return list(self._incidents.values())


class IncidentDetector:
    """Deterministic: cluster.count vs. a fixed threshold, nothing else.
    Consumes the PipelineResult Pipeline.process() already returns --
    Pipeline itself is never modified or subclassed.
    """

    def __init__(self, store: IncidentStore | None = None) -> None:
        self._store = store or IncidentStore()

    @property
    def store(self) -> IncidentStore:
        return self._store

    def check(self, result: PipelineResult) -> tuple[Incident, bool] | None:
        """Returns (incident, is_new) if this result is incident-worthy,
        else None. `is_new` distinguishes "just created" from "an existing
        incident's cluster snapshot was refreshed" -- callers use it to
        avoid re-alerting on every repeat occurrence of the same signature.
        """
        cluster = result.cluster
        event = result.event
        if cluster is None or event is None:
            return None

        if cluster.count < _threshold_for(cluster.severity):
            return None

        def build() -> Incident:
            return Incident(
                incident_id=_generate_incident_id(cluster.signature, cluster.first_seen),
                signature=cluster.signature,
                detected_at=datetime.now(timezone.utc),
                service=event.service,
                environment=event.environment,
                affected_component=event.metadata.get("endpoint"),
                severity=map_severity(cluster.severity),
                error_cluster=cluster,
            )

        return self._store.record(cluster.signature, cluster, build)


def _generate_incident_id(signature: str, first_seen: datetime) -> str:
    """Deterministic (not random): a hash of (signature, first_seen) so the
    same underlying incident always resolves to the same ID without needing
    to persist a counter -- consistent with _resolve_event_id's fallback in
    ingestion/pipeline.py. Only called once per signature; IncidentStore
    never regenerates an ID for an existing Incident.
    """
    basis = f"{signature}|{first_seen.isoformat()}"
    return sha256(basis.encode("utf-8")).hexdigest()[:16]
