# Tracy — Autonomous Incident Response

**Tracy** turns a production failure into an **investigated, tested, pull-request-ready code change** — without an engineer manually reading logs, digging through git history, writing the fix, and running tests by hand.

```text
Production Error → Log Ingestion → Incident Detection → Gemini Analysis
→ Validated Incident Package → GitHub → Codex Investigation
→ Root Cause Validation → Implementation → Tests → Pull Request
```

**Core principle: Gemini does not get the final say.** Gemini analyzes the incident and proposes hypotheses. Codex then independently investigates those hypotheses against the actual repository — reading source, tests, config, docs, and git history — before touching any code. A hypothesis is a claim to verify, not a fact.

---

## Short Demo

**Please look into the open PR**

<img width="1535" height="163" alt="image" src="https://github.com/user-attachments/assets/ad634672-de14-4a91-a432-d091e7653309" />

<img width="806" height="842" alt="image" src="https://github.com/user-attachments/assets/047ee162-5efc-4018-aaaa-51e2ec2b6b9a" />

<img width="565" height="639" alt="image" src="https://github.com/user-attachments/assets/a081ea7c-5dad-4149-a981-114061072595" />

<img width="576" height="255" alt="image" src="https://github.com/user-attachments/assets/201cecc0-ba3b-4bf4-b76b-d331026fea3c" />

---

### The Problem

The demo uses an intentional `ZeroDivisionError` in the checkout service. When the same error occurs repeatedly, Tracy recognizes it as one incident, not several.

### The Demo Flow

```text
POST /checkout (product_id=prod-003, quantity=5) → HTTP 500
→ Tracy detects the error → same error occurs again → ErrorCluster count=2
→ Incident created → Gemini analyzes the evidence → Incident Package generated
→ GitHub repository_dispatch → Codex investigates the repository
→ Root cause independently validated → Codex implements the fix
→ Tests run → Pull Request created
```

### What It Shows

- **Incident detection** — repeated failures are grouped, not duplicated.
- **AI analysis** — Gemini produces a summary, symptoms, hypotheses (with confidence), and recommended next steps from the structured evidence.
- **Evidence package** — a schema-validated `IncidentPackage` that keeps deterministic facts, AI analysis, evidence references, and hypotheses clearly separate.
- **Independent investigation** — Codex, invoked via GitHub Actions with a **read-only permission profile**, checks Gemini's hypothesis against the real repository instead of trusting it. Read-only means it cannot modify anything during investigation, even if incident data contains malicious or instruction-like text.
- **Fix** — only once the root cause is confirmed does Codex implement it, run the tests, and open a PR.

**Gemini suggests. Codex investigates. Codex only implements after the evidence supports the hypothesis.**

---

## Why It Matters

Traditional incident response requires an engineer to manually connect logs, code, and history. Tracy connects them automatically, closing the gap between **"something is broken"** and **"here is the validated root cause and proposed code change."** It's built around evidence, not blind AI automation.

> **AI should not be trusted simply because it sounds confident.** Gemini reasons about the incident; Codex independently checks that reasoning against the real codebase before anything changes.

**Production failure → Evidence → AI hypothesis → Independent validation → Code change**

---

## Technology

Python · Pydantic · Gemini API · Google GenAI SDK · GitHub Actions · OpenAI Codex · OpenSpec · FastAPI · Pytest · JSON Schema
