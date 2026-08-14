"""LocalLogSource: reads a local file line-by-line as RawRecords.

This is the local-development stand-in for a future GCPLogSource. It
deliberately does not spawn checkout-api, does not receive anything pushed
from checkout-api, and does not parse JSON -- it only reads bytes. The
boundary is: checkout-api writes structured JSON to stdout; a human (or a
one-time shell redirect) puts that stream into a file; LocalLogSource reads
that file. checkout-api never needs to know Tracy exists.
"""

import threading
import time
from pathlib import Path

from tracy.ingestion.base import LogSource, OnMessage, RawRecord

DEFAULT_POLL_INTERVAL_SECONDS = 0.2


class LocalLogSource(LogSource):
    def __init__(
        self,
        path: str | Path,
        follow: bool = False,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        """
        Args:
            path: file to read.
            follow: if False (default), read to EOF and return -- deterministic
                "replay" mode, used by tests and one-shot fixture processing.
                If True, keep watching for new lines after reaching EOF, like
                a minimal `tail -f` -- used for the live local demo.
            poll_interval: how long to sleep between EOF checks in follow mode.
                No inotify/watchdog dependency -- a plain sleep-poll loop is
                sufficient at hackathon log volumes.
        """
        self._path = Path(path)
        self._follow = follow
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()

    def listen(self, on_message: OnMessage) -> None:
        with self._path.open("r", encoding="utf-8") as handle:
            while True:
                line = handle.readline()
                if line:
                    self._emit_if_nonblank(line, on_message)
                    continue

                if not self._follow:
                    return

                if self._stop_event.is_set():
                    return

                time.sleep(self._poll_interval)

                if self._stop_event.is_set():
                    return

    def _emit_if_nonblank(self, line: str, on_message: OnMessage) -> None:
        stripped = line.strip()
        if not stripped:
            return
        on_message(RawRecord(payload=stripped.encode("utf-8"), source="local", ack_handle=None))

    def stop(self) -> None:
        self._stop_event.set()
