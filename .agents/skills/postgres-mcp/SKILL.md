---
name: postgres-mcp
description: Set up or verify a local Postgres MCP server that lets the agent query the project's Postgres database conversationally. Deferred until Tracy has a Postgres database and a real `.env` with DATABASE_URL — use when asked to connect the agent to Postgres, "start the postgres MCP", talk to the database, or check whether the DB MCP server is up.
---

# Postgres MCP

**Status: deferred.** Tracy does not yet have a database or a `DATABASE_URL` configured. This skill is a generic recipe for wiring a local Postgres MCP proxy for whatever project it runs in — do not attempt it until the Tracy repository actually defines a Postgres `DATABASE_URL` (e.g. in a real, non-example `.env`). If asked to run this before that exists, say so and stop rather than inventing connection details.

Connects the agent to a project's Postgres database via a **local** `crystaldba/postgres-mcp` Docker container (nothing is installed on the remote host — it only opens a network connection to the DB).

## Setup

1. Require a real `.env` with `DATABASE_URL`. Do not use `.env.example` (its URL is a local default).
2. Derive a plain `postgresql://user:pass@host:port/db` URI from `DATABASE_URL` (strip any async driver suffix, e.g. `+asyncpg`). Never print credentials.
3. Write `.mcp.json` at the repo root (gitignore it — it holds credentials):

   ```json
   {
     "mcpServers": {
       "postgres": {
         "command": "docker",
         "args": ["run", "-i", "--rm", "-e", "DATABASE_URI", "crystaldba/postgres-mcp", "--access-mode=restricted"],
         "env": { "DATABASE_URI": "postgresql://USER:PASS@HOST:5432/DB" }
       }
     }
   }
   ```
4. `docker pull crystaldba/postgres-mcp` if the image is missing.
5. Tell the user to **restart Claude Code** (or approve the new server) — `.mcp.json` is read at startup.

## Modes

- `--access-mode=restricted` — read-only with protections. Default; safe for a shared or remote DB.
- `--access-mode=unrestricted` — allows writes/DDL. Only when the user explicitly needs migrations.

## Verify

- Confirm auth + reachability: `docker run -i --rm postgres psql "<URI>" -c "select version();"`.
- If the `mcp__postgres__*` tools are loaded, call `list_schemas` — a result means the server is live for this session.
- The container is `--rm` and lives only for the session; it won't appear in `docker ps` between sessions.
