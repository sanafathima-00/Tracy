"""Unit tests for LocalLogSource. The source only reads bytes and produces
RawRecords -- it does not parse JSON, so malformed lines still reach the
pipeline as raw records (parsing failure is the pipeline's concern).
"""

from pathlib import Path

from tracy.ingestion.base import RawRecord
from tracy.ingestion.local import LocalLogSource


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "events.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_replay_mode_reads_all_lines_and_returns(tmp_path):
    path = _write(tmp_path, ['{"i": 1}', '{"i": 2}', '{"i": 3}'])
    source = LocalLogSource(path, follow=False)

    received: list[RawRecord] = []
    source.listen(received.append)  # must return on its own -- no stop() needed

    assert len(received) == 3
    assert all(r.source == "local" for r in received)
    assert all(r.ack_handle is None for r in received)
    assert received[0].payload == b'{"i": 1}'


def test_replay_mode_skips_blank_lines(tmp_path):
    path = tmp_path / "events.log"
    path.write_text('{"i": 1}\n\n   \n{"i": 2}\n', encoding="utf-8")
    source = LocalLogSource(path, follow=False)

    received: list[RawRecord] = []
    source.listen(received.append)

    assert len(received) == 2


def test_replay_mode_on_empty_file_yields_nothing(tmp_path):
    path = tmp_path / "empty.log"
    path.write_text("", encoding="utf-8")
    source = LocalLogSource(path, follow=False)

    received: list[RawRecord] = []
    source.listen(received.append)

    assert received == []


def test_malformed_lines_still_reach_the_pipeline_as_raw_records(tmp_path):
    """The source's job is only to produce bytes -- it must not try to
    parse or validate JSON itself, so a non-JSON line is still delivered."""
    path = _write(tmp_path, ["not json at all", '{"i": 1}'])
    source = LocalLogSource(path, follow=False)

    received: list[RawRecord] = []
    source.listen(received.append)

    assert len(received) == 2
    assert received[0].payload == b"not json at all"


def test_follow_mode_picks_up_lines_appended_after_start(tmp_path):
    path = tmp_path / "events.log"
    path.write_text('{"i": 1}\n', encoding="utf-8")
    source = LocalLogSource(path, follow=True, poll_interval=0.02)

    received: list[RawRecord] = []

    def on_message(raw: RawRecord) -> None:
        received.append(raw)
        if len(received) == 1:
            # Append a second line once the first has been seen, then stop
            # once the second arrives -- deterministic without sleeping in
            # the test itself.
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"i": 2}\n')
        elif len(received) == 2:
            source.stop()

    source.listen(on_message)

    assert len(received) == 2
    assert received[1].payload == b'{"i": 2}'


def test_follow_mode_stop_causes_listen_to_return(tmp_path):
    path = tmp_path / "events.log"
    path.write_text("", encoding="utf-8")
    source = LocalLogSource(path, follow=True, poll_interval=0.02)

    import threading

    def stop_soon() -> None:
        import time

        time.sleep(0.1)
        source.stop()

    threading.Thread(target=stop_soon, daemon=True).start()

    # If stop() didn't work, this would block forever and the test would
    # hang/timeout rather than fail cleanly -- that's an acceptable and
    # standard way to assert "this returns" for a blocking call.
    source.listen(lambda raw: None)
