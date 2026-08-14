# Tracy backend — Phase 2: local log ingestion

Turns raw log lines — today from a local file, later from GCP Pub/Sub — into normalized, deduplicated, clustered records. This phase implements only `LogEvent` and `ErrorCluster`. No GCP, no Gemini, no PostgreSQL, no Codex integration exist in this package yet.

**This does not depend on `checkout-api/`**, and checkout-api does not depend on this. The only connection is a log file on disk.

## Python version

Targets **Python 3.12** (`pyproject.toml` requires `>=3.12,<3.13`).

## Install

From this directory (`backend/`):

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Run the tests

```bash
pytest
```

## Run the local demo

**Step 1 — start checkout-api, redirecting its stdout to a file** (from `checkout-api/`, in its own environment):

```bash
uvicorn app.main:app > checkout-api.log
```

This is the only setup step — checkout-api's logging code is unmodified; it already writes structured JSON to stdout, and this just captures that stream into a file Tracy can read.

**Step 2 — trigger some activity**, including the intentional regression, from another terminal:

```bash
curl -X POST http://127.0.0.1:8000/checkout -H "Content-Type: application/json" \
  -d '{"user_id":"user-123","product_id":"prod-003","quantity":5}'
```

**Step 3 — run Tracy against the log file**, from `backend/`:

```bash
python -u -m tracy ../checkout-api/checkout-api.log --follow
```

The `-u` (unbuffered) flag matters if you're watching output live in a terminal that isn't your own interactive shell, or redirecting Tracy's own output to a file to `tail`: Python block-buffers stdout when it isn't attached to a real terminal, so without `-u` you may see nothing for a while and then a burst of output all at once — confirmed while validating this. Running directly in an interactive terminal without redirecting Tracy's own output doesn't need it.

Tracy will print each normalized `LogEvent` as it appears, and the `ErrorCluster` an ERROR/CRITICAL event lands in. Repeating the trigger request increments the same cluster's count rather than creating a new one. Press Ctrl+C to stop; a summary (processed/duplicate/malformed/invalid/cluster counts) prints on exit.

Note: uvicorn's own access-log line (`INFO:  127.0.0.1:... "POST /checkout HTTP/1.1" 200 OK`) also lands in `checkout-api.log` alongside checkout-api's structured JSON lines, since both currently go to stdout. Tracy correctly treats that line as malformed JSON and skips it (logged at WARNING via Python's standard `logging`, visible on stderr) — this is expected, not an error.

**Without `--follow`** (replay mode): reads the file to EOF once and stops — deterministic, used by the test suite against `tests/fixtures/sample_logs.jsonl`.

## Architecture

```
LocalLogSource ──► RawRecord ──► Pipeline (parse → normalize → sanitize
                                   → LogEvent → deduplicate → ErrorCluster)
```

A future `GCPLogSource` would produce the same `RawRecord` shape (`source="gcp"`) and feed the identical `Pipeline` — only the normalization step gains a GCP-specific branch (currently present as a `NotImplementedError` placeholder in `ingestion/pipeline.py`, so the seam is visible without any `google-cloud-*` import existing anywhere in this package).
