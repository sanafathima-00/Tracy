"""Local ingestion + incident detection + Gemini analysis demo runner.

    python -m tracy <path-to-log-file>            # replay mode: read to EOF, then stop
    python -m tracy <path-to-log-file> --follow    # follow mode: keep watching, like tail -f

No CLI framework -- just argparse (standard library). Prints each normalized
LogEvent, the ErrorCluster an ERROR/CRITICAL event landed in, an [INCIDENT]
line the first time a cluster becomes incident-worthy (Phase 3), and now --
Phase 4 -- a Gemini-generated analysis of that new incident, or a clear
"[AI analysis unavailable]" note if Gemini can't be reached. Gemini is only
ever called once per newly-detected incident, never on repeat occurrences of
one already seen (see tracy/detection.py's is_new flag) -- this keeps the
demo deterministic and avoids burning free-tier quota on noise.
"""

import argparse
import sys

from tracy.detection import IncidentDetector
from tracy.gemini import GeminiClient
from tracy.ingestion.local import DEFAULT_POLL_INTERVAL_SECONDS, LocalLogSource
from tracy.ingestion.pipeline import Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracy local log ingestion demo (Phase 2 + 3 + 4)")
    parser.add_argument("log_file", help="Path to the log file to consume (e.g. checkout-api.log)")
    parser.add_argument("--follow", action="store_true", help="Keep watching for new lines, like tail -f")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    args = parser.parse_args()

    pipeline = Pipeline()
    detector = IncidentDetector()
    gemini = GeminiClient()
    source = LocalLogSource(args.log_file, follow=args.follow, poll_interval=args.poll_interval)

    def on_message(raw) -> None:
        result = pipeline.process(raw)
        if result.malformed_json or result.invalid_schema:
            return
        if result.duplicate:
            print(f"[duplicate, skipped] event_id={result.event.event_id}")
            return
        event = result.event
        print(f"LogEvent  {event.severity:<8} {event.service:<14} {event.message}  (event_id={event.event_id[:12]}...)")
        if result.cluster is not None:
            print(f"    -> ErrorCluster count={result.cluster.count}  signature={result.cluster.signature}")

        detection = detector.check(result)
        if detection is None:
            return
        incident, is_new = detection
        if not is_new:
            print(f"[incident updated] incident_id={incident.incident_id}  cluster_count={incident.error_cluster.count}")
            return

        print(
            "[INCIDENT] new incident detected\n"
            f"    incident_id={incident.incident_id}\n"
            f"    service={incident.service}  severity={incident.severity}\n"
            f"    signature={incident.signature}"
        )

        analysis = gemini.analyze(incident, event)
        if analysis is None:
            print("[AI analysis unavailable]")
            return
        print(
            "[AI ANALYSIS]\n"
            f"    summary: {analysis.summary}\n"
            f"    impact: {analysis.impact_description}\n"
            f"    top hypothesis: {_top_hypothesis(analysis)}\n"
            f"    recommended investigation: {'; '.join(analysis.recommended_investigation) or '(none)'}"
        )

    print(f"Tracy local ingestion -- reading {args.log_file} ({'follow' if args.follow else 'replay'} mode)")
    print("Press Ctrl+C to stop.\n" if args.follow else "")

    try:
        source.listen(on_message)
    except KeyboardInterrupt:
        source.stop()
    finally:
        stats = pipeline.stats
        print(
            f"\nSummary: {stats.processed_count} processed, "
            f"{stats.duplicate_count} duplicates, "
            f"{stats.malformed_json_count} malformed JSON, "
            f"{stats.invalid_schema_count} invalid schema, "
            f"{len(pipeline.grouper.clusters())} error cluster(s), "
            f"{len(detector.store.all())} incident(s)",
            file=sys.stderr,
        )


def _top_hypothesis(analysis) -> str:
    if not analysis.hypotheses:
        return "(none -- insufficient evidence per Gemini)"
    best = max(analysis.hypotheses, key=lambda h: h.confidence)
    return f"{best.statement} (confidence={best.confidence:.2f})"


if __name__ == "__main__":
    main()
