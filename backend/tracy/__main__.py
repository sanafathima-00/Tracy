"""Local ingestion + incident detection demo runner.

    python -m tracy <path-to-log-file>            # replay mode: read to EOF, then stop
    python -m tracy <path-to-log-file> --follow    # follow mode: keep watching, like tail -f

No CLI framework -- just argparse (standard library). Prints each normalized
LogEvent, the ErrorCluster an ERROR/CRITICAL event landed in, and -- new in
Phase 3 -- an [INCIDENT] line the first time a cluster becomes incident-worthy.
Repeated occurrences of an already-detected incident update it silently
(no re-alert spam); see tracy/detection.py.
"""

import argparse
import sys

from tracy.detection import IncidentDetector
from tracy.ingestion.local import DEFAULT_POLL_INTERVAL_SECONDS, LocalLogSource
from tracy.ingestion.pipeline import Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracy local log ingestion demo (Phase 2 + 3)")
    parser.add_argument("log_file", help="Path to the log file to consume (e.g. checkout-api.log)")
    parser.add_argument("--follow", action="store_true", help="Keep watching for new lines, like tail -f")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    args = parser.parse_args()

    pipeline = Pipeline()
    detector = IncidentDetector()
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
        if is_new:
            print(
                "[INCIDENT] new incident detected\n"
                f"    incident_id={incident.incident_id}\n"
                f"    service={incident.service}  severity={incident.severity}\n"
                f"    signature={incident.signature}"
            )
        else:
            print(f"[incident updated] incident_id={incident.incident_id}  cluster_count={incident.error_cluster.count}")

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


if __name__ == "__main__":
    main()
