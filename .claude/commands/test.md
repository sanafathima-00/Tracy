Run the test suite(s) that actually exist in the Tracy repository.

Tracy's test tooling and package layout are not yet fixed, so don't assume a specific test runner or a fixed set of packages. Before running anything:

1. **Discover what's actually configured.** Look for signals already committed to the repo, such as a `package.json` `test` script, a `pytest`/`tox`/`unittest` config, a `Makefile` with a `test` target, or existing test directories/files.
2. **Run every test suite you find** — if the repo has multiple packages/workspaces, run each one's tests rather than guessing which matters.
3. **Report a clear pass/fail summary per suite.** Do not stop early on a failure — run everything you found and report all results at the end.
4. Do not silently modify unrelated files while investigating a failure, and do not claim tests passed without actually having run them.
5. **If no tests or test tooling exist yet**, say so plainly rather than fabricating a command or claiming success.
