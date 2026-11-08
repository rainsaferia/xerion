# PI-047 CSV/XLSX Activity Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement PI-047 CSV/XLSX activity export with filters, version scoping, explicit units, source identifiers, private storage, short-lived signed downloads, AI tool integration, and frontend client support.

**Architecture:** A domain-driven tabular export engine (`backend/app/domains/reporting/tabular_exporter.py`) generates UTF-8-BOM CSV and styled openpyxl XLSX from filtered schedule activities without mutating database records. The binary file is saved to private storage via `StorageAdapter`. The REST API endpoint `POST /api/v1/projects/{project_id}/exports/activities` initiates the export, creates a `Report` record, and returns report metadata with download URL. The AI tool `export_activity_data` allows conversational data exports with formal evidence citations.

**Architecture Diagram:**

```mermaid
graph TD
    subgraph "Client Layer"
        UI[Frontend App / API Client]
        AIUser[AI Chat Assistant]
    end

    subgraph "API Layer (app.api.v1)"
        ExportRoute[POST /projects/{id}/exports/activities]
        ReportDownload[GET /reports/{id}/download]
        ReportContent[GET /reports/{id}/content?token=...]
    end

    subgraph "Domain Layer (Pure Hexagonal)"
        RepService[reporting/service.py: generate_activity_export]
        TabularGen[reporting/tabular_exporter.py: export_activities_to_csv, export_activities_to_xlsx]
        AITool[ai/tools.py: export_activity_data]
    end

    subgraph "Storage & Database"
        DB[(PostgreSQL / SQLite - reports, usage_events)]
        Storage[(Private Storage - workspaces/.../exports/...csv/xlsx)]
    end

    UI -->|Export Request| ExportRoute
    UI -->|Download| ReportContent
    AIUser -->|Tool Trigger| AITool
    AITool --> RepService
    ExportRoute --> RepService
    RepService --> TabularGen
    TabularGen -->|CSV / XLSX Bytes| RepService
    RepService -->|Persist Report & UsageEvent| DB
    RepService -->|Store Object Privately| Storage
```

**Tech Stack:**
- Backend: Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, `openpyxl`, `csv` (utf-8-sig)
- Storage: `StorageAdapter` (private bucket / directory)
- Frontend: TypeScript, Next.js 16, Node.js test runner

---

## Global Constraints

1. **Architecture Isolation:**
   `backend/app/domains/reporting/` MUST NOT import `fastapi`, `starlette`, `openai`, `app.adapters`, or `app.api` (enforced by `tests/test_architecture.py`).
2. **Deterministic & Filter Respecting:**
   Exports must accurately reflect the selected `version_id`, `status`, `wbs_code`, `search`, and `critical_only` filters.
3. **Explicit Units & Identifiers:**
   Column headers must explicitly state units where applicable: `original_duration_hours`, `remaining_duration_hours`, `total_float_hours`, `free_float_hours`, `percent_complete`.
   Source identifiers (`source_activity_id`, `activity_code`, `wbs_code`) must be clearly exposed.
4. **Private Storage & Short-Lived Access:**
   Export files are stored privately at `workspaces/{workspace_id}/projects/{project_id}/exports/{export_id}.{format}`. Downloads require tenant authentication or short-lived signed JWT tokens.
5. **Usage Metering:**
   Every export generation must record a `usage_events` row with `event_type='report_export'`.

---

## Proposed Tasks

### Task 1: Tabular Export Engine (`tabular_exporter.py`)
- [x] Create `backend/app/domains/reporting/tabular_exporter.py`:
  - `export_activities_to_csv(activities: list[ActivityExportRow]) -> bytes`: CSV export using `csv.writer` with `utf-8-sig` encoding (Excel-friendly).
  - `export_activities_to_xlsx(activities: list[ActivityExportRow], project_code: str, version_label: str) -> bytes`: OpenPyXL workbook with formatted header row, date formats, right-aligned numeric cells, and auto column widths.
- [x] Create `backend/tests/test_tabular_exporter.py`:
  - Test CSV generation, header names, unit columns, quote handling, and UTF-8-BOM prefix (`\xef\xbb\xbf`).
  - Test XLSX generation, valid ZIP/XLSX header (`PK`), sheet title, and row counts.

### Task 2: Activity Export Core Service & Usage Metering
- [x] Update `backend/app/domains/reporting/schemas.py`:
  - Add `ActivityExportRequest` and `ActivityExportRow`.
- [x] Update `backend/app/domains/reporting/service.py`:
  - Implement `generate_activity_export()`: fetches activities based on filters, builds tabular bytes, writes to `StorageAdapter`, inserts `Report` row (`report_type="activity_export"`), and records `UsageEvent(event_type="report_export")`.
- [x] Create `backend/tests/test_activity_export_service.py`:
  - Unit tests for activity export generation, filtering, storage saving, report status lifecycle, and usage event recording.

### Task 3: REST API Endpoint with Tenant Authorization
- [x] Update `backend/app/api/v1/routes.py`:
  - Implement `POST /api/v1/projects/{project_id}/exports/activities` returning `ReportResponse`.
- [x] Update `backend/tests/test_reporting_routes.py`:
  - Test activity export endpoint, filter query validation, CSV and XLSX formats, short-lived download token generation, and streaming content verification.
  - Verify tenant isolation in `backend/tests/test_tenant_isolation.py`.

### Task 4: AI Tool Registration & Evidence Tagging
- [x] Update `backend/app/domains/ai/schemas.py`:
  - Add `ExportActivityDataArgs`.
- [x] Update `backend/app/domains/ai/tools.py`:
  - Register `export_activity_data` tool and handler.
- [x] Update `backend/app/domains/ai/evidence.py`:
  - Add evidence citation formatter: `[EV: export/<id> format=<format>]`.
- [x] Create `backend/tests/test_ai_export_tool.py`:
  - Unit tests for AI tool execution, argument validation, and evidence tagging.

### Task 5: Frontend API Client & Full Monorepo Verification
- [x] Update `frontend/src/lib/api-client.ts`:
  - Add `ActivityExportPayload` and `api.exportActivities(projectId, payload, token)`.
- [x] Update `frontend/src/lib/api-client.test.ts`:
  - Add unit tests for `exportActivities`.
- [x] Verify full monorepo:
  - Run `npm run check` (all 202 backend pytest tests, 41 frontend node tests, ruff, mypy, eslint, tsc - PASSED).
  - Run `npm --prefix frontend run build` (Next.js production build - PASSED).

