Bootstrap the Tracy development environment. Run this when setting up for the first time or after a fresh clone.

Tracy's dependency stack, services, and environment variables are not yet fixed, so don't assume any of them. Before doing anything:

1. **Discover what's actually committed to the repo**, such as a `package.json`, `pyproject.toml`/`requirements.txt`, a `Makefile`, a `docker-compose.yml`, or a dedicated setup script.
2. **Environment file** — only if the repo actually has an `.env.example` (or similar template): check if `.env` exists, and if not, copy the template and tell the user to review it and fill in any secrets it defines before continuing. Do not invent variable names that aren't already in the template.
3. **Install dependencies and start services** using whatever install/build/compose targets the repo already defines. Run them in the order the repo's own docs or scripts imply.
4. **Verify the environment came up**, using whatever health check or verification the repo already defines (e.g. a documented health endpoint, a `make` target, a smoke test). Don't invent a port or endpoint that isn't established in the repo.
5. **Done** — summarize what was set up and how to reach it, based only on what's actually configured.

If any step fails, stop and report the error clearly — do not proceed past a failed step. If the repository doesn't yet define a setup process, say so plainly and ask the user what they'd like this skill to automate, rather than fabricating steps.
