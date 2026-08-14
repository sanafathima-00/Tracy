# checkout-api

A small, standalone checkout service used as the monitored "production" application in the Tracy hackathon demo.

## What this is

`checkout-api` is intentionally tiny: one FastAPI app, a fixed in-memory product catalog, and in-memory order storage. It exists only to give Tracy a realistic, controlled system to observe — it is not itself part of Tracy.

**checkout-api does not depend on Tracy.** It has its own dependencies, its own Python environment, and imports nothing from the rest of this repository.

## Install dependencies

From this directory (`checkout-api/`), using Python 3.12:

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Run locally

```bash
uvicorn app.main:app --reload
```

The app listens on `http://127.0.0.1:8000` by default.

## Run tests

```bash
pytest
```

## Endpoints

- `GET /health` — returns `{"status": "ok"}`.
- `POST /checkout` — accepts `{"user_id": "...", "product_id": "...", "quantity": N}`, and returns a confirmed order (`order_id`, `total_price`, `status`) on success. Returns `404` for an unknown product, `409` for insufficient stock, and `422` for an invalid request body.

## Data

The product catalog and all created orders live only in memory for the lifetime of the running process. There is no database. Restarting the app resets everything.

## Logging

Every application log line is a single-line JSON object written to stdout — no third-party logging dependency. Each request gets a request ID (reused from an incoming `X-Request-ID` header if present, otherwise generated), which is included in every log line for that request and echoed back as the `X-Request-ID` response header. Checkout produces business-level log lines (`Checkout completed` / `Product not found` / `Insufficient stock`) in addition to one generic per-request line; unhandled exceptions are logged with a stack trace and turned into a generic `{"detail": "Internal server error", "request_id": "..."}` response — the client never sees exception details.

Configurable via environment variables (all optional, with defaults suitable for local runs):

| Variable | Default |
|---|---|
| `SERVICE_NAME` | `checkout-api` |
| `ENVIRONMENT` | `development` |
| `SERVICE_VERSION` | `local` |

Logs never contain secrets, credentials, tokens, cookies, or full request bodies — only an explicit, whitelisted set of fields is ever written.

Note: uvicorn's own startup/access log lines (e.g. `INFO:     127.0.0.1:... "GET /health HTTP/1.1" 200 OK`) are a separate, non-JSON stream from uvicorn itself — this phase intentionally does not reconfigure uvicorn's own loggers (doing so reliably is fragile, since uvicorn reconfigures them again during its own startup). Only checkout-api's own application log lines are the structured JSON described above.

## Status

The foundation and structured logging are implemented. The intentional production regression used for the Tracy demo, containerization, and any GCP/Tracy/Codex integration are not part of this phase and do not exist yet.
