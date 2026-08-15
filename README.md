# Tracy — Autonomous Incident Response

## What I Built

**Tracy** is an autonomous incident-response system that turns a production failure into an **investigated and actionable code change**.

Instead of requiring an engineer to manually:

1. Find the error in logs
2. Group repeated failures
3. Understand what went wrong
4. Inspect the repository
5. Check Git history
6. Implement a fix
7. Run tests
8. Create a pull request

Tracy automates this workflow.

```text
Production Error
      ↓
Log Ingestion
      ↓
Incident Detection
      ↓
Gemini Analysis
      ↓
Validated Incident Package
      ↓
GitHub
      ↓
Codex Investigation
      ↓
Root Cause Validation
      ↓
Implementation
      ↓
Tests
      ↓
Pull Request
```

The important design principle is that **Gemini does not get the final say**.

Gemini analyzes the incident and proposes hypotheses.

**Codex independently investigates those hypotheses against the actual repository before making changes.**

---

## Short Demo

### The Problem

The demo uses an intentional `ZeroDivisionError` in the checkout service.

When the same production error occurs repeatedly, Tracy detects that these are not separate incidents.

It groups them into a single incident.

### The Demo Flow

```text
POST /checkout
product_id = prod-003
quantity = 5
        ↓
HTTP 500
        ↓
Tracy detects the error
        ↓
Same error occurs again
        ↓
ErrorCluster count = 2
        ↓
Incident created
        ↓
Gemini analyzes the evidence
        ↓
Incident Package generated
        ↓
GitHub repository_dispatch
        ↓
Codex investigates the repository
        ↓
Root cause independently validated
        ↓
Codex implements the fix
        ↓
Tests run
        ↓
Pull Request created
```

### What the Demo Shows

**1. Incident detection**

Tracy recognizes repeated failures and avoids creating duplicate incidents.

**2. AI analysis**

Gemini analyzes the structured evidence and produces:

* Human-readable summary
* Symptoms
* Hypotheses
* Confidence
* Recommended investigation

**3. Evidence package**

Tracy creates a schema-validated `IncidentPackage`.

It separates:

* Deterministic facts
* AI-generated analysis
* Evidence references
* Hypotheses

**4. Independent investigation**

The Incident Package is handed to Codex through GitHub Actions.

Codex investigates:

* Source code
* Tests
* Configuration
* Documentation
* Git history

Codex treats Gemini's hypothesis as a **claim to verify**, not as truth.

**5. Fix**

After the root cause is confirmed, Codex can implement the fix, run the tests, and create a pull request.

---

### GitHub Actions

Codex was integrated into the incident-response pipeline through GitHub Actions.

The investigation workflow uses a **read-only permission profile**.

This means the investigation phase cannot modify the repository, even if incident data contains malicious or instruction-like text.

The workflow is:

```text
Tracy
  ↓
IncidentPackage
  ↓
repository_dispatch
  ↓
GitHub Actions
  ↓
Codex
  ↓
Read-only investigation
  ↓
Root cause validation
```

This creates an important safety boundary:

**Gemini suggests.
Codex investigates.
Codex only implements after the evidence supports the hypothesis.**

---

## Why It Matters

Traditional incident response requires engineers to manually connect several pieces of information.

Tracy connects those pieces automatically.

It reduces the work between:

**"Something is broken"**

and

**"Here is the validated root cause and proposed code change."**

The system is designed around **evidence rather than blind AI automation**.

---

## Technology

* **Python**
* **Pydantic**
* **Gemini API**
* **Google GenAI SDK**
* **GitHub Actions**
* **OpenAI Codex**
* **OpenSpec**
* **FastAPI**
* **Pytest**
* **JSON Schema**

---

## Key Principle

> **AI should not be trusted simply because it sounds confident.**

Tracy uses Gemini for reasoning, but Codex independently checks that reasoning against the real codebase before a change is made.

**Production failure → Evidence → AI hypothesis → Independent validation → Code change**
