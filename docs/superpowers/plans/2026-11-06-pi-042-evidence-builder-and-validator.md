# PI-042 — Evidence Builder and Response Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Evidence Builder to extract structured, standardized evidence references from deterministic schedule tools, and the Response Validator to enforce grounding, caveat unevidenced claims, and detect insufficient data conditions before responses are finalized.

**Architecture:**
- Create `backend/app/domains/ai/evidence.py` to build canonical `EvidenceReference` records from all schedule tool outputs (`get_project_overview`, `list_activities`, `get_activity_detail`, `get_activity_relationships`, `get_critical_activities`, `get_float_distribution`, `analyze_schedule_quality`, `compare_project_versions`).
- Create `backend/app/domains/ai/validator.py` to inspect the assistant's formulated response against the extracted evidence, add caveats when claims lack evidence, detect insufficient data, and enforce determinism disclaimers.
- Integrate evidence generation in `backend/app/domains/ai/tools.py` (`execute_tool`).
- Integrate validation pipeline in `backend/app/domains/ai/orchestrator.py` (`run_agent_turn`).
- Update data contracts and schemas in `backend/app/domains/ai/schemas.py` and `frontend/src/lib/api-client.ts`.

---

## Global Constraints

- **Hexagonal Domain Isolation:** `domains/ai/` must never import `fastapi`, `starlette`, `openai`, `app.adapters`, or `app.api`. Verified by `test_architecture.py`.
- **Zero Hallucination Tolerance:** The assistant must not state schedule facts, dates, float hours, or variances without citing or matching deterministic evidence.
- **Insufficient Data Transparency:** When required inputs are absent (e.g. baseline not available, invalid dates, empty project), the system must flag `validation_status="insufficient_data"` and clearly communicate the gap.
- **Deterministic Disclaimer:** Any forward projection or milestone date must be labeled as schedule-derived, never statistical/probabilistic unless independently validated.

---

### Task 1: Evidence Builder Module

**Files:**
- Create: `backend/app/domains/ai/evidence.py`
- Test: `backend/tests/test_ai_evidence.py`

**Interfaces:**
- Produces: `EvidenceReference` Pydantic model, `build_tool_evidence(tool_name, version_id, result_data) -> list[EvidenceReference]`.

- [x] **Step 1: Write unit tests in `test_ai_evidence.py`**
  - Test evidence generation for `get_project_overview` (KPIs, activity counts, data date).
  - Test evidence generation for `get_critical_activities` (activity code, name, float hours, status).
  - Test evidence generation for `get_activity_detail` (dates, remaining duration, baselines).
  - Test evidence generation for `analyze_schedule_quality` (check codes, severity, violations).
  - Test evidence generation for `compare_project_versions` (reconciled deltas, additions, removals).
  - Test evidence formatting with citation labels (`[EV: ...]`).
- [x] **Step 2: Implement `backend/app/domains/ai/evidence.py`**
  - Define `EvidenceReference` model matching Section 7 of `05_AI_AGENT_SPEC.md`.
  - Implement extractor functions for each tool response payload.
  - Generate stable IDs and readable citation tags.
- [x] **Step 3: Run unit tests**
  - `cd backend; uv run pytest tests/test_ai_evidence.py`

---

### Task 2: Response Validator Module

**Files:**
- Create: `backend/app/domains/ai/validator.py`
- Test: `backend/tests/test_ai_validator.py`

**Interfaces:**
- Produces: `ValidatedResponse` model, `validate_response(assistant_text, tools_executed, accumulated_evidence) -> ValidatedResponse`.

- [x] **Step 1: Write unit tests in `test_ai_validator.py`**
  - Test verified response when claims match evidence and cite evidence correctly.
  - Test unevidenced claim detection: if response claims specific numbers/dates not present in evidence, caveat warning is appended.
  - Test insufficient data condition: when tools report missing baseline, empty items, or errors, response status is marked `insufficient_data`.
  - Test probabilistic claim suppression: disclaimer is attached if probabilistic confidence ("90% confidence", "Monte Carlo") is claimed.
- [x] **Step 2: Implement `backend/app/domains/ai/validator.py`**
  - Implement deterministic claim extraction and evidence cross-referencing.
  - Implement caveat generation and disclaimer formatting.
  - Return `ValidatedResponse(content, validation_status, evidence_citations, warnings)`.
- [x] **Step 3: Run unit tests**
  - `cd backend; uv run pytest tests/test_ai_validator.py`

---

### Task 3: Orchestrator & Tool Integration

**Files:**
- Modify: `backend/app/domains/ai/schemas.py`
- Modify: `backend/app/domains/ai/tools.py`
- Modify: `backend/app/domains/ai/orchestrator.py`
- Test: `backend/tests/test_ai_orchestrator.py`
- Test: `backend/tests/test_ai_routes.py`

- [x] **Step 1: Update schemas**
  - Add `EvidenceReference` and `ValidatedResponse` schemas to `schemas.py`.
  - Update `AgentTurnResponse` with `validation_status`, `evidence_citations`, `warnings`.
- [x] **Step 2: Integrate Evidence Builder in `tools.py`**
  - Call `build_tool_evidence()` in `execute_tool()` so `result.evidence_refs` contains validated references.
- [x] **Step 3: Integrate Response Validator in `orchestrator.py`**
  - Pass assistant response through `validate_response()`.
  - Store validated content, citations, and warnings in DB and return in `AgentTurnResponse`.
- [x] **Step 4: Update and run existing orchestrator and route tests**
  - `cd backend; uv run pytest tests/test_ai_orchestrator.py tests/test_ai_routes.py`

---

### Task 4: Frontend Integration & Full Monorepo Verification

**Files:**
- Modify: `frontend/src/lib/api-client.ts`
- Modify: `frontend/src/lib/api-client.test.ts`

- [x] **Step 1: Update frontend types and tests**
  - Add `EvidenceReference`, `ValidationStatus` to `api-client.ts`.
  - Update `AgentTurnResponse` type.
  - Update tests in `api-client.test.ts`.
- [x] **Step 2: Run full monorepo check and build**
  - `npm run check` (backend pytest, ruff lint/format, mypy, frontend tests, eslint, tsc).
  - `npm --prefix frontend run build`.
