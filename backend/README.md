# Tracy backend — local log ingestion, incident detection, and Gemini analysis

Turns raw log lines — today from a local file, later from GCP Pub/Sub — into normalized, deduplicated, clustered records (Phase 2), deterministically decides when a cluster is incident-worthy (Phase 3), and asks Gemini to explain a newly-detected incident (Phase 4). No GCP, no PostgreSQL, no Codex integration exist in this package yet.

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

## Gemini analysis (optional)

Once an incident is detected (Phase 3), Tracy can ask Gemini to explain it — a summary, plain-language error explanation, root-cause hypotheses with confidence, and recommended investigation steps. This is entirely optional: **deterministic incident detection works fully without it**, and the normal test suite (`pytest`) never needs a real API key or network access.

To enable it, set `GEMINI_API_KEY` in your shell before running the demo:

**PowerShell:**
```powershell
$env:GEMINI_API_KEY="your-key-here"
```

**bash:**
```bash
export GEMINI_API_KEY="your-key-here"
```

Get a free-tier key from [Google AI Studio](https://aistudio.google.com/) — no Cloud Billing account is required for the free tier.

- **Never commit this key.** It is read from the environment only; nothing in this repository writes it to a file, logs it, or includes it in any Incident/analysis output.
- If `GEMINI_API_KEY` is not set (or Gemini is unreachable, rate-limited, or returns something that doesn't validate), the demo prints `[AI analysis unavailable]` and continues normally — the deterministic `Incident` it already detected is unaffected either way.
- Gemini is only called once per *newly*-detected incident, never on repeat occurrences of one already seen — this keeps the demo deterministic and avoids burning free-tier quota on noise.

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
                                        │
                                        ▼
                              IncidentDetector (deterministic thresholds)
                                        │
                                (Incident, is_new)
                                        │  only if is_new
                                        ▼
                                  GeminiClient.analyze(incident, event)
                                        │
                          GeminiIncidentAnalysis | None ("unavailable")
```

A future `GCPLogSource` would produce the same `RawRecord` shape (`source="gcp"`) and feed the identical `Pipeline` — only the normalization step gains a GCP-specific branch (currently present as a `NotImplementedError` placeholder in `ingestion/pipeline.py`, so the seam is visible without any `google-cloud-*` import existing anywhere in this package).

Gemini never decides whether an incident exists, its severity, or whether it's a duplicate — `IncidentDetector` already decided all of that deterministically, with no LLM involved, before `GeminiClient` is ever called (see `tracy/detection.py` and `tracy/gemini.py`). A Gemini failure never invalidates the `Incident` it was asked to explain.
