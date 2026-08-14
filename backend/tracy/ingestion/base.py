"""The common interface every log source implements, and the raw envelope
they hand to the pipeline. The pipeline never imports LocalLogSource (or,
later, GCPLogSource) directly -- it only ever sees a LogSource and a
RawRecord. Nothing in this module is GCP-specific; it contains no
google-cloud-* imports and none are needed to implement it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from tracy.models import SourceName


@dataclass
class RawRecord:
    """What a LogSource hands to the pipeline for one incoming record.

    `payload` is raw bytes -- the source does not parse JSON. That
    separation matters: it's what lets the exact same Pipeline consume
    records from a local file today and from GCP Pub/Sub later without
    either source needing to know how the payload will eventually be
    interpreted.

    `ack_handle` is optional because local records have nothing to
    acknowledge -- only a future GCP Pub/Sub message would carry a real
    handle here. Where present, it is expected to expose .ack()/.nack(),
    matching google-cloud-pubsub's own Message object -- Tracy does not
    invent a separate ack protocol.
    """

    payload: bytes
    source: SourceName
    ack_handle: Any | None = None


OnMessage = Callable[[RawRecord], object]


class LogSource(ABC):
    """Common interface for anything that can feed raw log records into Tracy.

    Deliberately callback-based and synchronous, not an async generator:
    this matches google-cloud-pubsub's own SubscriberClient.subscribe()
    shape (callback-driven, running on its own background threads), so a
    future GCP adapter can wrap the real SDK almost directly instead of
    bridging it into asyncio. `listen` is expected to run inside a
    background thread if the caller wants to keep doing other work.
    """

    @abstractmethod
    def listen(self, on_message: OnMessage) -> None:
        """Block, invoking on_message for each record, until stop() is called."""

    @abstractmethod
    def stop(self) -> None:
        """Signal listen() to return."""
