"""Manual, explicit trigger for Phase 5B/5C: given a completed
IncidentPackage and a Codex-produced InvestigationResult (both as JSON
files -- e.g. the package Tracy already built, and the trailing JSON block
from a completed Phase 5A investigation-result.md, downloaded from the
GitHub Actions run's artifact), decides whether implementation is
authorized and, if so, dispatches `tracy-implement`.

    python -m tracy.implement_cli <incident_package.json> <investigation_result.json>

This is deliberately a separate, manual command from tracy/__main__.py's
--dispatch flag -- the safe progression is incident detected ->
investigation -> a human's controlled decision to proceed -> implementation,
never automatic (see this phase's spec and
openspec/changes/establish-incident-response-workflow/tasks.md). Tracy has
no way to know an investigation completed or what it concluded without a
human supplying the result; this command is that supply point.
"""

import argparse
import sys

from tracy.github_dispatch import GitHubDispatcher
from tracy.incident_package import IncidentPackage
from tracy.investigation import InvestigationResult, authorize_implementation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decide and dispatch tracy-implement for a completed Phase 5A investigation."
    )
    parser.add_argument("incident_package_file", help="Path to a JSON file matching IncidentPackage's schema")
    parser.add_argument(
        "investigation_result_file",
        help="Path to a JSON file matching InvestigationResult's schema (Codex's investigation-result.md's trailing JSON block)",
    )
    args = parser.parse_args()

    package = IncidentPackage.model_validate_json(_read(args.incident_package_file))
    investigation_result = InvestigationResult.model_validate_json(_read(args.investigation_result_file))

    if package.incident_id != investigation_result.incident_id:
        print(
            f"[NOT DISPATCHED] incident_id mismatch: package={package.incident_id!r} "
            f"investigation_result={investigation_result.incident_id!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    decision = authorize_implementation(investigation_result)
    print(f"Gate decision: authorized={decision.authorized} -- {decision.reason}")
    if not decision.authorized:
        print("[NOT DISPATCHED] implementation not authorized by investigation result.")
        raise SystemExit(1)

    result = GitHubDispatcher().dispatch_implementation(package, investigation_result)
    if result.success:
        print(f"[DISPATCHED] tracy-implement sent for incident_id={package.incident_id} (status {result.status_code})")
    else:
        print(f"[NOT DISPATCHED] {result.message}", file=sys.stderr)
        raise SystemExit(1)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    main()
