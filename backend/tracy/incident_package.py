"""Assembles a validated, schema-conformant IncidentPackage from a
deterministic Incident, its triggering LogEvent, and an optional
GeminiIncidentAnalysis.

    Incident + LogEvent + (GeminiIncidentAnalysis | None) -> IncidentPackageBuilder -> IncidentPackage

This is the final step of the pipeline:

    RawRecord -> Pipeline -> LogEvent -> ErrorCluster -> IncidentDetector
    -> Incident -> GeminiClient -> GeminiIncidentAnalysis
    -> IncidentPackageBuilder -> IncidentPackage

`IncidentPackage`'s shape mirrors
openspec/changes/establish-incident-response-workflow/incident-package.schema.json
field-for-field -- it is not redesigned here. That schema declares every
optional property with a plain (non-nullable) JSON type, so an absent value
must be *omitted* from the serialized JSON, never emitted as `null`; see
`IncidentPackage.to_schema_dict()`.

Every field below is either:
  - Tracy-owned (deterministic, read directly from Incident/LogEvent/
    ErrorCluster -- Gemini never touches these), or
  - Gemini-owned (copied verbatim from GeminiIncidentAnalysis when present),
    or
  - deliberately left at the schema's empty representation (`[]`, `0.0`, or
    omitted) when neither Tracy nor Gemini actually has evidence for it --
    correlated_events, related_incident_ids, deployment commit/timestamp,
    relevant_commit/relevant_files, and documentation_context all fall in
    this last category in the current system, and stay that way regardless
    of whether Gemini succeeded or failed (see PART D/E of this phase's
    spec -- there is no correlation or deployment-commit evidence source
    anywhere in Tracy today, so nothing here can honestly fill them).

Gemini failure (None `analysis`) never removes or blocks the package: every
Tracy-owned field is still populated, and every Gemini-owned field simply
takes its schema-valid empty form instead of being fabricated.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from tracy.detection import map_severity
from tracy.gemini import GeminiIncidentAnalysis, Hypothesis
from tracy.models import Incident, IncidentSeverity, LogEvent

SCHEMA_VERSION: Literal["1.1"] = "1.1"


class ImpactInfo(BaseModel):
    """Maps to the schema's `impact` object. `description` is Gemini's
    interpretation; `metric`/`value` are Tracy's deterministic occurrence
    count -- never a business metric (revenue, users, traffic) Tracy has no
    evidence for.
    """

    description: str | None = None
    metric: str | None = None
    value: str | None = None


class PackageErrorCluster(BaseModel):
    """The schema's `error_clusters[]` shape. Deliberately not a reuse of
    `tracy.models.ErrorCluster`: that model's `severity` is typed to the
    log-level scale (`CRITICAL`/`ERROR`/...), while the schema's
    `error_clusters[].severity` uses the business-impact scale
    (`critical`/`high`/...) -- the same mismatch documented in
    `detection.py` and `design.md`. This is the one place that conversion
    (`detection.map_severity`) is actually applied when assembling a
    package; `ErrorCluster` itself is never modified.
    """

    signature: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_message: str | None = None
    severity: IncidentSeverity


class EvidenceRef(BaseModel):
    log_query_or_reference: str | None = None
    timestamp: datetime | None = None
    count: int | None = None


class ObservedFact(BaseModel):
    """A statement Tracy's own evidence directly proves. Built exclusively
    from Incident/LogEvent/ErrorCluster fields -- see
    `IncidentPackageBuilder._build_observed_facts`. Gemini never
    contributes to this list; its interpretation lives in `summary`/
    `symptoms`/`hypotheses` instead, which are clearly separate fields.
    """

    statement: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CorrelatedEvent(BaseModel):
    description: str
    timestamp: datetime
    source: str | None = None


class TimelineEvent(BaseModel):
    timestamp: datetime
    event: str


class DeploymentInfo(BaseModel):
    version: str | None = None
    deployed_at: datetime | None = None
    commit: str | None = None


class IncidentPackage(BaseModel):
    """Mirrors incident-package.schema.json field-for-field. See the module
    docstring for the Tracy-owned vs. Gemini-owned split.
    """

    incident_id: str
    schema_version: Literal["1.1"] = SCHEMA_VERSION
    severity: IncidentSeverity
    detected_at: datetime
    environment: str | None = None
    service: str
    affected_component: str | None = None
    impact: ImpactInfo | None = None
    summary: str
    symptoms: list[str] = Field(default_factory=list)
    error_clusters: list[PackageErrorCluster] = Field(default_factory=list)
    observed_facts: list[ObservedFact] = Field(default_factory=list)
    correlated_events: list[CorrelatedEvent] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    suspected_root_cause: str | None = None
    confidence_overall: float = Field(ge=0.0, le=1.0)
    deployment_information: DeploymentInfo | None = None
    relevant_commit: str | None = None
    relevant_files: list[str] = Field(default_factory=list)
    documentation_context: list[str] = Field(default_factory=list)
    recommended_investigation: list[str] = Field(default_factory=list)
    log_references: list[str] = Field(default_factory=list)
    related_incident_ids: list[str] = Field(default_factory=list)

    def to_schema_dict(self) -> dict:
        """The JSON-serializable form that actually conforms to
        incident-package.schema.json: every optional field the schema
        declares with a plain (non-nullable) type is omitted when unset,
        never emitted as `null` (`additionalProperties: false` plus
        non-nullable types means a `null` value would fail validation).
        """
        return self.model_dump(mode="json", exclude_none=True)


def _deterministic_title(incident: Incident, event: LogEvent) -> str:
    """A concrete, factual first sentence for `summary` -- entirely
    Tracy-owned (service/affected_component/error_type), never Gemini's
    words. Deliberately not a separate schema field: incident-package.
    schema.json has no `title`, so adding one would be schema drift (see
    PART B1 of this phase's spec) -- this is just the lead sentence of the
    one `summary` string the schema actually has.
    """
    component = (incident.affected_component or "").strip("/")
    component_phrase = f"{component} " if component else ""
    error_type = event.error_type or "an unspecified error"
    return f"{incident.service} {component_phrase}requests are failing with {error_type}."


def _build_summary(incident: Incident, event: LogEvent, analysis: GeminiIncidentAnalysis | None) -> str:
    title = _deterministic_title(incident, event)
    if analysis is None or not analysis.summary:
        return title
    return f"{title} {analysis.summary}"


def _build_impact(cluster_count: int, analysis: GeminiIncidentAnalysis | None) -> ImpactInfo:
    return ImpactInfo(
        description=analysis.impact_description if analysis else None,
        metric="occurrence_count",
        value=str(cluster_count),
    )


def _build_error_cluster(incident: Incident) -> PackageErrorCluster:
    cluster = incident.error_cluster
    return PackageErrorCluster(
        signature=cluster.signature,
        count=cluster.count,
        first_seen=cluster.first_seen,
        last_seen=cluster.last_seen,
        sample_message=cluster.sample_message,
        severity=map_severity(cluster.severity),
    )


def _build_observed_facts(incident: Incident, event: LogEvent) -> list[ObservedFact]:
    """Every statement here must be directly provable from Tracy's own
    data -- no inference, no Gemini. See the module docstring.
    """
    cluster = incident.error_cluster
    error_label = event.error_type or "This error"

    facts = [
        ObservedFact(
            statement=(
                f"{error_label} occurred {cluster.count} time(s) in service "
                f"'{incident.service}'" + (f" ({incident.environment})" if incident.environment else "")
            ),
            evidence=[
                EvidenceRef(
                    log_query_or_reference=event.raw_ref,
                    timestamp=cluster.last_seen,
                    count=cluster.count,
                )
            ],
        ),
        ObservedFact(
            statement=f"First observed at {cluster.first_seen.isoformat()}, most recently at {cluster.last_seen.isoformat()}.",
            evidence=[EvidenceRef(timestamp=cluster.first_seen), EvidenceRef(timestamp=cluster.last_seen)],
        ),
    ]

    if incident.affected_component:
        http_status = event.metadata.get("http_status")
        statement = f"Requests to '{incident.affected_component}' were affected"
        if http_status is not None:
            statement += f" (HTTP {http_status})"
        statement += "."
        facts.append(
            ObservedFact(
                statement=statement,
                evidence=[EvidenceRef(log_query_or_reference=event.raw_ref, timestamp=event.timestamp)],
            )
        )

    if event.error_message:
        facts.append(
            ObservedFact(
                statement=f"The error message was: {event.error_message}",
                evidence=[EvidenceRef(log_query_or_reference=event.raw_ref, timestamp=event.timestamp)],
            )
        )

    if event.request_id:
        facts.append(
            ObservedFact(
                statement=f"At least one occurrence was recorded under request_id '{event.request_id}'.",
                evidence=[EvidenceRef(log_query_or_reference=event.raw_ref, timestamp=event.timestamp)],
            )
        )

    return facts


def _build_timeline(incident: Incident) -> list[TimelineEvent]:
    """Every entry corresponds to a real timestamp Tracy already has --
    never a Gemini-invented event. See PART B4.
    """
    cluster = incident.error_cluster
    events = [TimelineEvent(timestamp=cluster.first_seen, event="First occurrence observed")]
    if cluster.last_seen != cluster.first_seen:
        events.append(TimelineEvent(timestamp=cluster.last_seen, event="Most recent occurrence observed"))
    events.append(TimelineEvent(timestamp=incident.detected_at, event="Tracy detected this as an incident"))
    return sorted(events, key=lambda e: e.timestamp)


def _top_hypothesis(analysis: GeminiIncidentAnalysis | None) -> Hypothesis | None:
    if analysis is None or not analysis.hypotheses:
        return None
    return max(analysis.hypotheses, key=lambda h: h.confidence)


def _confidence_overall(analysis: GeminiIncidentAnalysis | None) -> float:
    """Never Gemini's own self-reported number (it doesn't have one --
    GeminiIncidentAnalysis has no confidence_overall field at all). Always
    the maximum confidence across its own hypotheses, so this can never
    contradict them. See PART B8.
    """
    top = _top_hypothesis(analysis)
    return top.confidence if top else 0.0


def _suspected_root_cause(analysis: GeminiIncidentAnalysis | None) -> str | None:
    """Derived from the same top hypothesis as `_confidence_overall`, never
    asked of Gemini as an independent field -- see PART B9.
    """
    top = _top_hypothesis(analysis)
    return top.statement if top else None


def _build_deployment_information(event: LogEvent) -> DeploymentInfo | None:
    """Only `version` is ever populated (from LogEvent.version, when
    checkout-api's own SERVICE_VERSION env var produced one) -- `commit`/
    `deployed_at` have no evidence source anywhere in Tracy today and are
    never fabricated. See PART E.
    """
    if not event.version:
        return None
    return DeploymentInfo(version=event.version)


class IncidentPackageBuilder:
    """Deterministic except for consuming an already-produced
    GeminiIncidentAnalysis (or None). Does not call Gemini itself -- the
    caller runs GeminiClient.analyze() first and hands the result (or None
    on failure) to build(). No service/repository/factory layers.
    """

    def build(
        self,
        incident: Incident,
        event: LogEvent,
        analysis: GeminiIncidentAnalysis | None,
    ) -> IncidentPackage:
        cluster = incident.error_cluster
        package = IncidentPackage(
            incident_id=incident.incident_id,
            severity=incident.severity,
            detected_at=incident.detected_at,
            environment=incident.environment,
            service=incident.service,
            affected_component=incident.affected_component,
            impact=_build_impact(cluster.count, analysis),
            summary=_build_summary(incident, event, analysis),
            symptoms=list(analysis.symptoms) if analysis else [],
            error_clusters=[_build_error_cluster(incident)],
            observed_facts=_build_observed_facts(incident, event),
            correlated_events=[],  # PART D: no correlation evidence source exists yet
            timeline=_build_timeline(incident),
            hypotheses=list(analysis.hypotheses) if analysis else [],
            suspected_root_cause=_suspected_root_cause(analysis),
            confidence_overall=_confidence_overall(analysis),
            deployment_information=_build_deployment_information(event),
            relevant_commit=None,  # Codex's job later -- no repository access here
            relevant_files=[],
            documentation_context=[],
            recommended_investigation=list(analysis.recommended_investigation) if analysis else [],
            log_references=[event.raw_ref] if event.raw_ref else [],
            related_incident_ids=[],  # PART D: no cross-incident correlation exists yet
        )
        return package  # Pydantic already validated this on construction
