Run static analysis (linting and type checking) across the Tracy repository.

Tracy's toolchain is not yet fixed, so don't assume specific package managers, linters, or a monorepo layout. Before running anything:

1. **Discover what's actually configured.** Look for signals already committed to the repo, such as `package.json` scripts (`lint`, `typecheck`, `type-check`), a `pyproject.toml`/`ruff`/`mypy`/`flake8` config, a `Makefile` with a `check`/`lint` target, or CI workflow files that already run static analysis.
2. **Run only what you find**, in parallel where independent. If the repo has multiple packages/workspaces, run the relevant check in each one you discover — don't invent packages that don't exist.
3. **Report per check**: which passed (no issues found), which failed (with the relevant error output).
4. If any check fails, do NOT auto-fix. Report the issues clearly so the user can decide what to fix — only suggest fixes if asked.
5. **If no static analysis tooling is configured yet**, say so plainly rather than fabricating a command. Suggest asking the user what they'd like set up.
