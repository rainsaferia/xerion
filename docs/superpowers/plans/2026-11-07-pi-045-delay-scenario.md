# Implementation Plan: PI-045 Delay Scenario v1 (Sprint 4)

## Overview
Implement **PI-045 Delay Scenario v1** for bounded what-if activity delay simulation without mutating source project data, strictly adhering to `01_PRD.md`, `02_SYSTEM_ARCHITECTURE.md`, `05_AI_AGENT_SPEC.md`, `06_API_SPEC.md`, `07_UI_UX_SPEC.md`, and `08_DEVELOPMENT_BACKLOG.md`.

## Key Acceptance Criteria
1. **User selects activity and delay amount/unit**:
   - Inputs: `activity_source_id` (or code/UUID), `delay_value` (> 0), `delay_unit` (`working_days`, `calendar_days`, `hours`), `scenario_name`.
2. **Zero mutation against source schedule rows**:
   - Execution is purely in-memory with optional read-only run persistence in `analysis_runs`. Source `Activity` and `ProjectVersion` rows remain strictly unchanged.
3. **Affected outputs, assumptions, and limitations**:
   - Returns affected activities/milestones, source vs. scenario finish dates, float absorption, net critical path slip, assumptions, and engine limitations.
4. **Graceful handling of insufficient data**:
   - If activity is completed, missing finish dates, or if network data is insufficient, returns limited/insufficient result with clear caveats rather than false-precision dates.
5. **AI Tool & Evidence Integration**:
   - Register `simulate_activity_delay` in AI tool registry with evidence citation generator (`[EV: scenario/...]`).
6. **Hexagonal Domain Isolation**:
   - Zero framework or AI dependencies inside `backend/app/domains/schedule/`.

---

## Proposed Tasks

### Task 1: Delay Scenario Schemas & Deterministic Engine (COMPLETED)
- File: `backend/app/domains/schedule/schemas.py`
  - Added `DelayUnit`, `ImpactType`, `DelayScenarioRequest`, `AffectedScheduleItem`, `DelayScenarioSummary`, `DelayScenarioResponse`
- File: `backend/app/domains/schedule/scenario.py`
  - Implemented `simulate_activity_delay()` with float absorption analysis, direct successor FS links, critical milestone slip, and optional `AnalysisRun` audit record.
- File: `backend/tests/test_delay_scenario.py`
  - Unit tests for float absorption, critical slip, completed activity handling, invalid activity/unit, and zero-mutation verification (4 passed).

### Task 2: REST API Route & Tenant Guard (COMPLETED)
- File: `backend/app/api/v1/routes.py`
  - Added `POST /projects/{project_id}/schedule/scenarios/delay` with `ProjectAccess` tenant guard.
- File: `backend/tests/test_delay_scenario_routes.py`
  - Tested endpoint with valid payloads, completed activity rejection, tenant isolation, and error handling (2 passed).

### Task 3: AI Tool & Evidence Integration (COMPLETED)
- File: `backend/app/domains/ai/schemas.py` & `tools.py`
  - Registered `simulate_activity_delay` tool and `SimulateActivityDelayArgs` validator.
  - Wired tool execution in `tools.py`.
- File: `backend/app/domains/ai/evidence.py`
  - Added evidence builder for `simulate_activity_delay` with `[EV: <code_or_id> scenario_delay=...]` citations.
- File: `backend/tests/test_ai_delay_scenario_tool.py`
  - Tested tool execution, argument validation, and evidence citation generation (3 passed).

### Task 4: Frontend API Client & Monorepo Verification (COMPLETED)
- File: `frontend/src/lib/api-client.ts`
  - Added `simulateDelayScenario(projectId, payload, token)` with typed response models.
- File: `frontend/src/lib/api-client.test.ts`
  - Added unit tests for `simulateDelayScenario()`.
- Run full monorepo suite: `npm run check` (all backend + frontend tests, ruff, mypy, eslint, tsc, Next.js build).
  - Status: All 183 backend tests passed, 37 frontend tests passed, Next.js build succeeded.

