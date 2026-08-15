"""Dispatches a validated IncidentPackage to GitHub as a repository_dispatch
event (event_type "tracy-investigate"), for the read-only Codex investigation
workflow at .github/workflows/incident-investigation.yml to pick up.

This module never calls Gemini and never touches Incident/IncidentPackage
construction -- both already exist and are already valid before dispatch()
is ever called. A failed (or skipped) dispatch never invalidates either.

Dispatch is manual/opt-in only -- see __main__.py's --dispatch flag. This
module does not decide *when* to dispatch; it only sends what it's given,
once, per incident_id, for the lifetime of this process.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from tracy.incident_package import IncidentPackage

logger = logging.getLogger("tracy.github_dispatch")

GITHUB_API_BASE = "https://api.github.com"

# Distinct from the existing "tracy-incident" event type already used by
# .github/workflows/incident-response.yml (the write-capable, unimplemented
# Phase 5B/5C workflow) -- this phase adds a new, separate, read-only
# workflow and must not collide with or trigger that one.
EVENT_TYPE = "tracy-investigate"

MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1, 2)  # sleep before attempt 2, then before attempt 3

# Rate limit + transient server-side failures are worth retrying. Anything
# else (401/403 auth, 404 unknown repo, 422 malformed payload) won't be
# fixed by retrying -- same philosophy as gemini.py's _is_retryable.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class DispatchResult:
    success: bool
    status_code: int | None
    message: str


def _load_token() -> str:
    token = os.environ.get("TRACY_GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "TRACY_GITHUB_TOKEN is not set -- GitHub dispatch is unavailable. "
            "The Incident/IncidentPackage already produced are unaffected; "
            "see backend/README.md to configure it."
        )
    return token


def _load_repository() -> tuple[str, str]:
    repo = os.environ.get("TRACY_GITHUB_REPOSITORY")
    if not repo or "/" not in repo:
        raise RuntimeError(
            "TRACY_GITHUB_REPOSITORY is not set, or not in 'owner/repo' form -- "
            "GitHub dispatch is unavailable. The Incident/IncidentPackage "
            "already produced are unaffected."
        )
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise RuntimeError(f"TRACY_GITHUB_REPOSITORY={repo!r} is not in 'owner/repo' form.")
    return owner, name


def _send_request(url: str, headers: dict, body: bytes) -> int:
    """Isolated in its own function so tests can monkeypatch just this call
    instead of the whole urllib stack. Returns the HTTP status code on any
    response; raises urllib.error.HTTPError/URLError on failure, exactly
    like urllib.request.urlopen does -- callers handle both identically.
    Stdlib only -- no `requests`/`httpx` dependency for a single POST call.
    """
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def _is_retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES


class GitHubDispatcher:
    """Sends a repository_dispatch event carrying one IncidentPackage,
    wrapped under a single top-level `incident_package` client_payload key
    (GitHub's repository_dispatch API caps client_payload at 10 top-level
    properties -- IncidentPackage has far more fields than that, so it
    cannot be sent as client_payload directly).

    Owns a small in-memory set of successfully-dispatched incident_ids --
    the same pattern as Deduplicator/IncidentStore elsewhere in this
    codebase, not a database. incident_id is deterministic/stable across a
    Tracy restart (see detection.py), so this only protects within one
    process's lifetime -- sufficient for this phase; persistent dedup
    storage is explicitly out of scope.
    """

    def __init__(self) -> None:
        self._dispatched_ids: set[str] = set()
        self._lock = threading.Lock()

    def dispatch(self, package: IncidentPackage) -> DispatchResult:
        with self._lock:
            if package.incident_id in self._dispatched_ids:
                logger.info(
                    "Skipping dispatch for incident_id=%s -- already dispatched this process",
                    package.incident_id,
                )
                return DispatchResult(
                    success=False,
                    status_code=None,
                    message="already dispatched this process (deduplicated)",
                )

        try:
            token = _load_token()
            owner, repo = _load_repository()
        except RuntimeError as exc:
            logger.warning("GitHub dispatch unavailable: %s", exc)
            return DispatchResult(success=False, status_code=None, message=str(exc))

        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = json.dumps(
            {
                "event_type": EVENT_TYPE,
                "client_payload": {"incident_package": package.to_schema_dict()},
            }
        ).encode("utf-8")

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                status = _send_request(url, headers, body)
            except urllib.error.HTTPError as exc:
                if attempt < MAX_ATTEMPTS and _is_retryable_status(exc.code):
                    logger.warning(
                        "GitHub dispatch retry %d/%d after HTTP %d",
                        attempt,
                        MAX_ATTEMPTS - 1,
                        exc.code,
                    )
                    time.sleep(_BACKOFF_SECONDS[attempt - 1])
                    continue
                logger.warning(
                    "GitHub dispatch failed for incident_id=%s: HTTP %d",
                    package.incident_id,
                    exc.code,
                )
                return DispatchResult(
                    success=False,
                    status_code=exc.code,
                    message=f"GitHub API returned HTTP {exc.code}",
                )
            except urllib.error.URLError as exc:
                if attempt < MAX_ATTEMPTS:
                    logger.warning(
                        "GitHub dispatch retry %d/%d after network error: %s",
                        attempt,
                        MAX_ATTEMPTS - 1,
                        type(exc).__name__,
                    )
                    time.sleep(_BACKOFF_SECONDS[attempt - 1])
                    continue
                logger.warning(
                    "GitHub dispatch failed for incident_id=%s: network error",
                    package.incident_id,
                )
                return DispatchResult(
                    success=False,
                    status_code=None,
                    message="network error contacting GitHub",
                )
            else:
                with self._lock:
                    self._dispatched_ids.add(package.incident_id)
                logger.info("Dispatched incident_id=%s to %s/%s", package.incident_id, owner, repo)
                return DispatchResult(success=True, status_code=status, message="dispatched")

        return DispatchResult(success=False, status_code=None, message="GitHub dispatch failed after retries")
