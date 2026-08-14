"""Gemini-based incident interpretation.

Takes a deterministic Incident (already detected, already deduplicated, its
severity already decided by detection.py) plus one representative LogEvent,
and asks Gemini to explain it: a summary, plain-language error explanation,
root-cause hypotheses with confidence, and recommended investigation steps.

Gemini is never responsible for detecting an incident, assigning its
severity, or deciding whether it is a duplicate -- all of that already
happened before this module is ever called. GeminiIncidentAnalysis
deliberately omits severity, incident_id, suspected_root_cause, and
confidence_overall: the first two are Tracy-owned, and the latter two are
meant to be derived later from `hypotheses` (max-confidence entry) rather
than asked of Gemini as separate fields it could self-contradict against.
It also omits anything about commits, files, deployments, or business
impact -- Tracy supplies no evidence for any of that yet, and asking for it
would only invite the model to invent it.

If Gemini is unavailable, misconfigured, or returns something that fails to
validate, GeminiClient.analyze() returns None. The Incident this module
received was already valid before this call and is completely unaffected by
a Gemini failure -- nothing here can un-detect an incident.
"""

import logging
import os
import time

from google import genai
from google.genai import types
from httpx import RequestError
from pydantic import BaseModel, Field

from tracy.models import Incident, LogEvent

logger = logging.getLogger("tracy.gemini")

# Matches design.md's already-finalized stack decision -- not changed here.
MODEL_NAME = "gemini-3.6-flash"

# Bounds on what goes into the prompt (see production-log-ingestion's
# aggregation-before-LLM-exposure requirement: aggregated evidence only,
# never a raw/unbounded log stream). Chosen generously relative to what
# checkout-api's real regression actually produces (~400 char stack trace),
# not tuned to any observed pathological case.
MAX_STACK_TRACE_CHARS = 2000
MAX_MESSAGE_CHARS = 500

MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1, 2)  # sleep before attempt 2, then before attempt 3

# HTTP status codes worth retrying: rate limit + transient server-side
# failures. Anything else (400 bad request, 401/403 auth, 404) won't be
# fixed by retrying.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Belt-and-suspenders key-name check. checkout-api's logging_config.py and
# Tracy's own ingestion/pipeline.py._sanitize have already stripped these
# from LogEvent.metadata by the time it reaches here -- this is a third,
# cheap pass at the external-API boundary, not a replacement for either.
# Like both of those, it matches key *names* only; it does not scan
# stack_trace/message free text for embedded secret-shaped values (see the
# module docstring in ingestion/pipeline.py for the same accepted
# limitation, and tasks.md's Phase 4 section for why a regex-based text
# scanner is deliberately not built here).
_FORBIDDEN_KEY_SUBSTRINGS = (
    "authorization",
    "cookie",
    "password",
    "api_key",
    "apikey",
    "token",
    "secret",
)

SYSTEM_PROMPT = """You are Tracy, an automated incident-analysis system for production software.

You will receive deterministic evidence about a detected incident: which
service and environment it occurred in, an error signature and how many
times it has occurred, and one representative log event including its
stack trace.

The supplied evidence is authoritative and complete for what Tracy knows.
Do not invent facts. Do not assume commits, files, deployments, traffic
counts, user counts, business impact, infrastructure state, or any other
information that is not present in the supplied evidence.

Clearly distinguish observed facts from hypotheses. Observed facts must be
directly supported by the supplied evidence. Hypotheses are inferences and
must include a confidence score from 0.0 to 1.0 that reflects how well the
evidence actually supports them -- not how plausible the explanation sounds
in general.

Never present a hypothesis as a confirmed root cause. If the evidence is
insufficient to support any confident hypothesis, say so explicitly and
recommend what should be investigated next instead of guessing.

Never repeat, restate, or expose credentials, passwords, tokens,
authorization values, or other secrets, even if one appears to be present
in the supplied evidence.

Use concise, technical language suitable for an engineer investigating a
production incident. Return only the requested structured output."""


class Hypothesis(BaseModel):
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)


class GeminiIncidentAnalysis(BaseModel):
    """Gemini's interpretation of one Incident. See the module docstring
    for why severity/incident_id/suspected_root_cause/confidence_overall/
    commit-or-deployment fields are deliberately not here.
    """

    summary: str
    impact_description: str
    symptoms: list[str]
    observed_facts: list[str]
    hypotheses: list[Hypothesis]
    recommended_investigation: list[str]


def _truncate(text: str, max_chars: int, keep_end: bool = False) -> str:
    if len(text) <= max_chars:
        return text
    if keep_end:
        # Python tracebacks read outer -> inner; the actual exception line
        # is always last, so the tail is what matters most when bounding.
        return "...[truncated]...\n" + text[-max_chars:]
    return text[:max_chars] + "...[truncated]"


def _strip_forbidden_keys(metadata: dict) -> dict:
    return {
        key: value
        for key, value in metadata.items()
        if not any(bad in key.lower() for bad in _FORBIDDEN_KEY_SUBSTRINGS)
    }


def build_prompt(incident: Incident, event: LogEvent) -> str:
    """Bounded, deterministic prompt text built from exactly two things:
    the Incident (Tracy's own decision, already made) and one representative
    LogEvent (the triggering occurrence) -- never a raw log stream.
    """
    cluster = incident.error_cluster
    metadata = _strip_forbidden_keys(event.metadata)
    stack_trace = _truncate(event.stack_trace or "(none)", MAX_STACK_TRACE_CHARS, keep_end=True)
    sample_message = _truncate(cluster.sample_message, MAX_MESSAGE_CHARS)
    event_message = _truncate(event.message, MAX_MESSAGE_CHARS)

    return (
        "Incident evidence (Tracy-generated, deterministic):\n"
        f"service: {incident.service}\n"
        f"environment: {incident.environment}\n"
        f"affected_component: {incident.affected_component}\n"
        f"severity: {incident.severity}\n"
        f"signature: {incident.signature}\n"
        f"occurrence_count: {cluster.count}\n"
        f"first_seen: {cluster.first_seen.isoformat()}\n"
        f"last_seen: {cluster.last_seen.isoformat()}\n"
        f"sample_message: {sample_message}\n"
        "\n"
        "Representative log event (one example occurrence):\n"
        f"timestamp: {event.timestamp.isoformat()}\n"
        f"error_type: {event.error_type}\n"
        f"error_message: {event.error_message}\n"
        f"message: {event_message}\n"
        f"request_id: {event.request_id}\n"
        f"trace_id: {event.trace_id}\n"
        f"version: {event.version}\n"
        f"metadata: {metadata}\n"
        f"stack_trace:\n{stack_trace}\n"
    )


def _load_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set -- Gemini analysis is unavailable. "
            "Tracy's deterministic incident detection is unaffected; see "
            "backend/README.md to configure it."
        )
    return api_key


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in _RETRYABLE_STATUS_CODES
    # Network-level failures (timeout, connection refused, DNS, ...) from
    # the SDK's underlying HTTP transport carry no HTTP status code at all.
    return isinstance(exc, RequestError)


class GeminiClient:
    """Single-shot, synchronous wrapper around google-genai's structured
    output. One public method; no agent/session/tool-calling concepts --
    a bounded classification task doesn't need any of that.
    """

    def __init__(self, client: genai.Client | None = None) -> None:
        # Lazily constructed if not injected, so a missing API key only
        # matters the first time analyze() actually needs a real client --
        # tests that inject their own fake client never touch this at all.
        self._client = client

    def _client_or_create(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=_load_api_key())
        return self._client

    def analyze(self, incident: Incident, event: LogEvent) -> GeminiIncidentAnalysis | None:
        try:
            client = self._client_or_create()
        except RuntimeError as exc:
            logger.warning("Gemini analysis unavailable: %s", exc)
            return None

        prompt = build_prompt(incident, event)
        logger.info("Gemini analysis started for incident_id=%s", incident.incident_id)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=GeminiIncidentAnalysis,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 -- must never escape to the pipeline
                if attempt < MAX_ATTEMPTS and _is_retryable(exc):
                    logger.warning(
                        "Gemini analysis retry %d/%d (incident_id=%s) after %s",
                        attempt,
                        MAX_ATTEMPTS - 1,
                        incident.incident_id,
                        type(exc).__name__,
                    )
                    time.sleep(_BACKOFF_SECONDS[attempt - 1])
                    continue
                logger.warning(
                    "Gemini analysis unavailable for incident_id=%s: %s",
                    incident.incident_id,
                    type(exc).__name__,
                )
                return None

            if response.parsed is None:
                logger.warning(
                    "Gemini analysis unavailable for incident_id=%s: response did not "
                    "match the expected structured format",
                    incident.incident_id,
                )
                return None

            logger.info("Gemini analysis succeeded for incident_id=%s", incident.incident_id)
            return response.parsed

        return None
