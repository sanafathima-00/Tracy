"""Source-agnostic ingestion pipeline:

    RawRecord -> parse -> normalize -> sanitize -> LogEvent
             -> deduplicate -> ErrorCluster (ERROR/CRITICAL only)

Nothing here knows or cares whether a RawRecord came from LocalLogSource or
a future GCPLogSource -- normalization is the one place source-specific
shape differences are absorbed (see _normalize_local below); everything
after it is uniform. Gemini, IncidentPackage, PostgreSQL, and Codex are
deliberately out of scope for this phase.
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from tracy.ingestion.base import RawRecord
from tracy.models import ErrorCluster, LogEvent

logger = logging.getLogger("tracy.ingestion.pipeline")

REQUIRED_FIELDS = ("timestamp", "severity", "service", "message")
VALID_SEVERITIES = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
CLUSTERABLE_SEVERITIES = {"CRITICAL", "ERROR"}

DEFAULT_DEDUPE_TTL_SECONDS = 3600
DEFAULT_DEDUPE_MAX_ENTRIES = 10_000

# Fields that map directly onto LogEvent's own named attributes. Everything
# else in a raw record's dict lands in metadata -- this is what keeps
# LogEvent stable as new producer-specific fields show up.
_KNOWN_LOG_EVENT_FIELDS = {
    "event_id",
    "timestamp",
    "severity",
    "service",
    "environment",
    "version",
    "message",
    "error_type",
    "error_message",
    "stack_trace",
    "request_id",
    "trace_id",
    "span_id",
    "raw_ref",
}

# Case-insensitive substring match against metadata *keys*. Deliberately not
# a DLP system: this catches known credential-shaped field NAMES only, not
# secret-shaped values embedded in free text (message/stack_trace). That is
# an accepted, documented limitation -- see the module docstring in
# checkout-api/app/logging_config.py for the same trade-off made there.
_FORBIDDEN_KEY_SUBSTRINGS = (
    "authorization",
    "cookie",
    "password",
    "api_key",
    "apikey",
    "token",
    "secret",
)

_STACK_FRAME_RE = re.compile(r'File "[^"]*", line \d+, in (\w+)')
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_DIGIT_RE = re.compile(r"\d+")


def normalize_message(message: str) -> str:
    """Replace values that vary per-occurrence (UUIDs, quoted literals,
    numbers) with placeholders, so the same underlying error doesn't split
    into multiple clusters just because it mentions a different id each time.
    Order matters: UUIDs and quoted strings first, since they themselves
    contain digits that the digit pass would otherwise mangle first.
    """
    normalized = _UUID_RE.sub("<uuid>", message)
    normalized = _QUOTED_RE.sub("<str>", normalized)
    normalized = _DIGIT_RE.sub("#", normalized)
    return normalized


def extract_top_frame_function(stack_trace: str | None) -> str:
    """Returns the innermost function name from a Python traceback (the last
    "File ..., line N, in FUNCTION" entry -- the actual failure site, not an
    outer caller). Deliberately ignores the line number, so an unrelated
    change elsewhere in the file that shifts line numbers doesn't split one
    real defect into separate clusters.
    """
    if not stack_trace:
        return "unknown"
    matches = _STACK_FRAME_RE.findall(stack_trace)
    return matches[-1] if matches else "unknown"


def _sanitize(data: dict) -> dict:
    """Strips any key whose name resembles a credential, from the top level
    and from a nested `metadata` dict if present. Conservative and
    deterministic: matches field NAMES only, case-insensitively, by
    substring -- catches `api_key`, `Authorization`, `user_token`, etc.
    Does not scan message/stack_trace text for secret-shaped values.
    """

    def _clean(d: dict) -> dict:
        cleaned = {}
        for key, value in d.items():
            lowered = key.lower()
            if any(bad in lowered for bad in _FORBIDDEN_KEY_SUBSTRINGS):
                continue
            cleaned[key] = value
        return cleaned

    sanitized = _clean(data)
    if isinstance(sanitized.get("metadata"), dict):
        sanitized["metadata"] = _clean(sanitized["metadata"])
    return sanitized


class Deduplicator:
    """Bounded, in-memory, TTL-based event_id dedup.

    Hackathon-grade, not a globally perfect identity mechanism: no
    Redis/Postgres, just a dict with a time-based sweep. This is sufficient
    because Pub/Sub-style at-least-once redelivery happens within seconds to
    minutes, not days, and the failure mode of losing this on a restart is
    "a message might get reprocessed once" -- not corruption.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_DEDUPE_TTL_SECONDS,
        max_entries: int = DEFAULT_DEDUPE_MAX_ENTRIES,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def seen_before(self, event_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            if event_id in self._seen:
                return True
            self._seen[event_id] = now
            if len(self._seen) > self._max_entries:
                oldest_id = min(self._seen, key=self._seen.__getitem__)
                del self._seen[oldest_id]
            return False

    def _sweep(self, now: float) -> None:
        expired = [event_id for event_id, seen_at in self._seen.items() if now - seen_at > self._ttl_seconds]
        for event_id in expired:
            del self._seen[event_id]


class ErrorGrouper:
    """Deterministic error clustering by
    (environment, service, error_type, top stack frame, normalized message, endpoint).

    Only ERROR/CRITICAL LogEvents are ever passed in -- see Pipeline.process.
    No embeddings, no LLM: a plain composite string, chosen to be readable
    for debugging as well as stable.
    """

    def __init__(self) -> None:
        self._clusters: dict[str, ErrorCluster] = {}
        self._lock = threading.Lock()

    @staticmethod
    def signature_for(event: LogEvent) -> str:
        environment = event.environment or "unknown"
        error_type = event.error_type or "unknown"
        top_frame = extract_top_frame_function(event.stack_trace)
        normalized_message = normalize_message(event.message)
        endpoint = event.metadata.get("endpoint", "unknown")
        return f"{environment}:{event.service}:{error_type}:{top_frame}:{normalized_message}:{endpoint}"

    def add(self, event: LogEvent) -> ErrorCluster | None:
        if event.severity not in CLUSTERABLE_SEVERITIES:
            return None

        signature = self.signature_for(event)
        with self._lock:
            existing = self._clusters.get(signature)
            if existing is None:
                cluster = ErrorCluster(
                    signature=signature,
                    count=1,
                    first_seen=event.timestamp,
                    last_seen=event.timestamp,
                    sample_message=event.message,
                    severity=event.severity,
                )
            else:
                cluster = existing.model_copy(
                    update={
                        "count": existing.count + 1,
                        "last_seen": max(existing.last_seen, event.timestamp),
                    }
                )
            self._clusters[signature] = cluster
            return cluster

    def clusters(self) -> list[ErrorCluster]:
        with self._lock:
            return list(self._clusters.values())


@dataclass
class PipelineResult:
    event: LogEvent | None = None
    cluster: ErrorCluster | None = None
    duplicate: bool = False
    malformed_json: bool = False
    invalid_schema: bool = False
    error: str | None = None


@dataclass
class PipelineStats:
    malformed_json_count: int = 0
    invalid_schema_count: int = 0
    duplicate_count: int = 0
    processed_count: int = 0


class Pipeline:
    """Turns RawRecords into deduplicated, grouped LogEvents. Source-agnostic:
    the only source-aware code is `_normalize`, dispatched by `raw.source`.
    """

    def __init__(
        self,
        deduplicator: Deduplicator | None = None,
        grouper: ErrorGrouper | None = None,
    ) -> None:
        self._dedup = deduplicator or Deduplicator()
        self._grouper = grouper or ErrorGrouper()
        self.stats = PipelineStats()

    @property
    def grouper(self) -> ErrorGrouper:
        return self._grouper

    def process(self, raw: RawRecord) -> PipelineResult:
        try:
            decoded = json.loads(raw.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.stats.malformed_json_count += 1
            logger.warning("Skipping malformed JSON log entry: %s", exc)
            return PipelineResult(malformed_json=True, error=str(exc))

        if not isinstance(decoded, dict):
            self.stats.invalid_schema_count += 1
            logger.warning("Skipping log entry: expected a JSON object, got %s", type(decoded).__name__)
            return PipelineResult(invalid_schema=True, error="payload is not a JSON object")

        try:
            self._validate(decoded)
        except ValueError as exc:
            self.stats.invalid_schema_count += 1
            logger.warning("Skipping structurally invalid log entry: %s", exc)
            return PipelineResult(invalid_schema=True, error=str(exc))

        normalized = self._normalize(decoded, raw.source)
        normalized = _sanitize(normalized)

        event = LogEvent(**normalized)
        self.stats.processed_count += 1

        if self._dedup.seen_before(event.event_id):
            self.stats.duplicate_count += 1
            logger.debug("Duplicate event_id=%s -- not re-clustered", event.event_id)
            return PipelineResult(event=event, duplicate=True)

        cluster = self._grouper.add(event)
        return PipelineResult(event=event, cluster=cluster)

    @staticmethod
    def _validate(decoded: dict) -> None:
        missing = [field_name for field_name in REQUIRED_FIELDS if not decoded.get(field_name)]
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")
        if decoded["severity"] not in VALID_SEVERITIES:
            raise ValueError(f"invalid severity: {decoded['severity']!r}")
        _parse_timestamp(decoded["timestamp"])

    def _normalize(self, decoded: dict, source: str) -> dict:
        if source == "gcp":
            # Not implemented in this phase -- no GCP code exists anywhere in
            # this package. This branch exists only so the dispatch point is
            # visible for where GCP-specific unwrapping (jsonPayload/resource/
            # labels/insertId/trace) will eventually live, per design.md.
            raise NotImplementedError("GCP normalization is not implemented in Phase 2")
        return self._normalize_local(decoded)

    @staticmethod
    def _normalize_local(decoded: dict) -> dict:
        metadata = {k: v for k, v in decoded.items() if k not in _KNOWN_LOG_EVENT_FIELDS}
        event_id = _resolve_event_id(decoded)
        return {
            "event_id": event_id,
            "timestamp": _parse_timestamp(decoded["timestamp"]),
            "severity": decoded["severity"],
            "service": decoded["service"],
            "environment": decoded.get("environment"),
            "version": decoded.get("version"),
            "message": decoded["message"],
            "error_type": decoded.get("error_type"),
            "error_message": decoded.get("error_message"),
            "stack_trace": decoded.get("stack_trace"),
            "request_id": decoded.get("request_id"),
            "trace_id": decoded.get("trace_id"),
            "span_id": decoded.get("span_id"),
            "source": "local",
            "raw_ref": decoded.get("raw_ref") or event_id,
            "metadata": metadata,
        }


def _resolve_event_id(decoded: dict) -> str:
    """Resolution priority (see production-log-ingestion analysis):
    1. An explicit `event_id` field, if the raw log already carries one.
    2. GCP's `insertId`, if present (won't occur for local logs today, but
       checked for forward compatibility with hand-authored GCP-shaped
       fixtures).
    3. A deterministic hash fallback.

    The fallback is intentionally NOT request_id alone: checkout-api can
    (and does) emit multiple log lines sharing one request_id -- e.g. its
    own "Checkout completed" and "HTTP request completed" lines for the same
    request. Hashing (timestamp, service, severity, message, request_id)
    together disambiguates those from each other while still collapsing a
    truly re-delivered identical line into one event_id.

    This is a hackathon-grade fallback, not a globally unique identity
    mechanism: two genuinely different events that happen to share all five
    of these values within the same microsecond would collide. That's an
    accepted, documented limitation at this scale.
    """
    if decoded.get("event_id"):
        return str(decoded["event_id"])
    if decoded.get("insertId"):
        return str(decoded["insertId"])

    basis = "|".join(
        str(decoded.get(field_name, ""))
        for field_name in ("timestamp", "service", "severity", "message", "request_id")
    )
    return sha256(basis.encode("utf-8")).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
