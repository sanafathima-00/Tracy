Implemented and self-reviewed the localized fix. Exact-stock checkout now applies the maximum 5% clearance discount instead of dividing by zero. Direct pricing and checkout verification passed; the full regression suite hung at TestClient as anticipated. `git diff --check` passed, with only the two intended tracked files changed.

```json
{
  "incident_id": "sample0000000000",
  "implementation_status": "implemented",
  "planning_path": "lightweight",
  "branch": "codex/incident/sample0000000000",
  "files_changed": [
    "checkout-api/app/pricing.py",
    "checkout-api/tests/test_pricing_regression.py"
  ],
  "tests": [
    "PASS: python -m pytest checkout-api/tests/test_pricing_regression.py::test_exact_remaining_stock_uses_maximum_clearance_discount -q (1 passed)",
    "PASS: direct calculate_total(24.99, 5, 5) verification returned 118.70",
    "PASS: direct checkout with prod-003 stock=5 and quantity=5 returned confirmed, total_price=118.70, and stock=0",
    "BLOCKED: full checkout-api pricing regression suite hung in Starlette TestClient with no output and was interrupted after 30 seconds",
    "PASS: git diff --check"
  ],
  "openspec_status": "not_required",
  "root_cause": "The non-bulk pricing branch divided the clearance discount rate by remaining_stock minus quantity without handling zero, although checkout permits quantity to equal available stock.",
  "fix_summary": "Clamp the clearance discount divisor to at least one so exact-stock purchases receive the maximum 5% clearance discount, and replace incident-expecting tests with direct pricing and successful checkout regression coverage.",
  "pr_url": null,
  "review_iterations": 0,
  "failure_reason": null
}
```