# Implementation Plan: PI-044 Milestone Forecast v1 (Sprint 4)

## Overview

Implement **PI-044 Milestone Forecast v1** for deterministic schedule milestone forecasting without unsupported probabilistic claims, strictly adhering to `01_PRD.md`, `02_SYSTEM_ARCHITECTURE.md`, `05_AI_AGENT_SPEC.md`, `06_API_SPEC.md`, and `08_DEVELOPMENT_BACKLOG.md`.

## Key Acceptance Criteria

1. **Explicit Forecast Method**: Explicit method enum (`imported_schedule_dates`, `deterministic_float_indicator`) with human-readable methodology descriptions.
2. **Source vs Calculated Projection**: Strict distinction between `source_date`, `projected_date`, `is_calculated_projection`, and `variance_days`.
3. **Limitations & Missing Data**: Explicit `limitations` and `warnings` regarding calendars, network lags, missing dates, or missing float.
4. **No Probabilistic Claims**: Deterministic CPM indicator only with explicit disclaimer preventing false Monte Carlo confidence claims.
5. **AI Tool & Evidence Integration**: Register `get_milestone_forecast` in AI tool registry with evidence citation generator (`[EV: ...]`).
6. **Hexagonal Architecture**: Zero framework or AI dependencies inside `backend/app/domains/schedule/`.

---

## Proposed Tasks

### Task 1: Schedule Forecast Schemas & Deterministic Engine

- [x] File: `backend/app/domains/schedule/schemas.py`
  - Add `ForecastMethod = Literal["imported_schedule_dates", "deterministic_float_indicator"]`
  - Add `MilestoneForecastItem`, `MilestoneForecastSummary`, `MilestoneForecastResponse`
- [x] File: `backend/app/domains/schedule/forecast.py`
  - Implement `compute_milestone_forecast(session, project_id, version_id, method, milestone_id, hours_per_day)`
  - Milestone identification: `activity_type` containing milestone, zero duration, or explicit milestone query.
  - Sourcing vs Projection logic:
    - `imported_schedule_dates`: Uses imported finish date, `is_calculated_projection=False`.
    - `deterministic_float_indicator`: Projects slippage based on negative total float, `is_calculated_projection=True`.
  - Compile limitations and warnings.
- [x] File: `backend/tests/test_milestone_forecast.py`
  - Unit tests for both methods, missing float, completed milestones, explicit limitations, and non-probabilistic disclaimers.

### Task 2: REST API Route & Tenant Guard

- [x] File: `backend/app/api/v1/routes.py`
  - Add `GET /projects/{project_id}/schedule/forecast` with `ProjectAccess` tenant guard.
- [x] File: `backend/tests/test_milestone_forecast_routes.py`
  - Test endpoint with valid and invalid parameters, tenant isolation, and empty/missing data cases.

### Task 3: AI Tool & Evidence Integration

- [x] File: `backend/app/domains/ai/schemas.py` & `tools.py`
  - Register `get_milestone_forecast` tool and `GetMilestoneForecastArgs` validator.
  - Wire tool execution in `tools.py`.
- [x] File: `backend/app/domains/ai/evidence.py`
  - Add evidence builder for `get_milestone_forecast` with `[EV: forecast/...]` citation tags.
- [x] File: `backend/tests/test_ai_milestone_forecast_tool.py`
  - Test tool execution and evidence generation.

### Task 4: Frontend API Client & Monorepo Verification

- [x] File: `frontend/src/lib/api-client.ts`
  - Add `getMilestoneForecast()` with typed response models.
- [x] File: `frontend/src/lib/api-client.test.ts`
  - Add unit tests for `getMilestoneForecast()`.
- [x] Run full monorepo suite: `npm run check` (174 backend tests, 36 frontend tests, ruff, mypy, eslint, tsc).
- [x] Run Next.js production build: `npm --prefix frontend run build`.
