# PI-014 Import Preview UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the backend confirmation endpoint and the frontend import preview UI for PI-014, displaying job status, detected metadata, object counts, warnings, and blocking errors, while strictly preventing confirmation of blocking imports and requiring explicit confirmation.

---

### Task 1: Backend Confirmation Domain Logic & API Endpoint

**Files:**
- Modify `backend/app/domains/ingestion/job_service.py`
- Modify `backend/app/api/v1/routes.py`
- Modify `backend/tests/test_import_jobs.py`

**Steps:**
- [ ] Write failing test in `backend/tests/test_import_jobs.py`:
  - `test_confirm_import_job_succeeds_for_preview_ready_job`
  - `test_confirm_import_job_fails_when_blocking_errors_exist`
  - `test_confirm_import_job_is_tenant_isolated`
- [ ] Implement `confirm_import_job(job: ImportJob) -> tuple[bool, str | None]` in `job_service.py`:
  - If `job.errors` is non-empty or `job.status == "failed"`, return `(False, "Cannot confirm an import job with blocking errors.")`.
  - If `job.status == "confirmed"`, return `(True, None)`.
  - If `job.status != "preview_ready"`, return `(False, f"Job cannot be confirmed while in status '{job.status}'.")`.
  - Set `job.status = "confirmed"`, update `finished_at` if not set, and return `(True, None)`.
- [ ] Add `POST /api/v1/imports/{import_job_id}/confirm` in `routes.py`:
  - Protected by `ImportJobAccess`.
  - Calls `confirm_import_job`. If failed, raises `ApiError(400, "CANNOT_CONFIRM_IMPORT", reason)`.
  - Commits session and returns `ImportJobOut`.
- [ ] Run backend tests: `cd backend && uv run pytest tests/test_import_jobs.py` to confirm they pass.
- [ ] Run lint and mypy on backend: `cd backend && uv run ruff check . && uv run mypy`.

---

### Task 2: Frontend API Client Extension

**Files:**
- Modify `frontend/src/lib/api-client.ts`
- Modify `frontend/src/lib/api-client.test.ts`

**Steps:**
- [ ] Define types in `api-client.ts`:
  - `ImportJobStatus = "queued" | "processing" | "preview_ready" | "failed" | "confirmed"`
  - `ImportError = { code: string; message: string; actionable?: string }`
  - `ImportWarning = { code: string; message: string }`
  - `PreviewSummary = { activities: number; wbs_nodes: number; relationships: number; calendars: number }`
  - `DetectedMetadata = Record<string, unknown>`
  - `ImportJobOut = { id: string; status: ImportJobStatus; progress_pct: number; detected_metadata: DetectedMetadata | null; preview_summary: PreviewSummary | null; warnings: ImportWarning[]; errors: ImportError[]; created_at: string; finished_at: string | null }`
- [ ] Add client methods:
  - `getImportJob(id: string, token?: string): Promise<ImportJobOut>`
  - `getImportPreview(id: string, token?: string): Promise<ImportJobOut>`
  - `confirmImport(id: string, token?: string): Promise<ImportJobOut>`
  - `retryImport(id: string, token?: string): Promise<ImportJobOut>`
- [ ] Add unit tests in `frontend/src/lib/api-client.test.ts` for these methods and error handling.
- [ ] Run `npm --prefix frontend test` and `npm --prefix frontend run typecheck`.

---

### Task 3: Import Preview UI Component & Page

**Files:**
- Create `frontend/src/components/import-preview.tsx`
- Create `frontend/src/app/imports/[id]/page.tsx`
- Create `frontend/src/components/import-preview.test.ts`

**Steps:**
- [ ] Build `ImportPreview` component:
  - Status header with status badge (queued, processing, preview_ready, failed, confirmed) and animated progress bar when processing.
  - Detected metadata panel (file format, project code/name, data date).
  - Object counts KPI cards (Activities, WBS Nodes, Logic Relationships, Calendars).
  - Warnings alert box (amber) showing non-blocking warnings.
  - Blocking errors box (red) showing error code, message, and actionable resolution steps.
  - Confirmation controls:
    - Disabled when errors are present or status is not `preview_ready`.
    - Explicit confirmation: requires checking an acknowledgment checkbox ("I have reviewed the detected metadata and schedule object counts") before enabling the "Confirm Import & Create Version" button.
    - Status message / badge once confirmed.
    - Retry button for failed imports.
- [ ] Build route `frontend/src/app/imports/[id]/page.tsx`:
  - Loads import job via API or accepts `initialJob` prop.
  - Handles polling when job is in `queued` or `processing` state.
- [ ] Write tests in `frontend/src/components/import-preview.test.ts` verifying:
  - Renders status and detected metadata.
  - Displays object counts, warnings, and blocking errors.
  - Prevents confirmation when blocking errors are present.
  - Requires explicit confirmation before submission.
- [ ] Run `npm --prefix frontend test` and `npm --prefix frontend run typecheck`.

---

### Task 4: Full Monorepo Quality Gate Verification

**Steps:**
- [ ] Run `npm run check` from monorepo root:
  - Backend ruff check and format check.
  - Frontend eslint.
  - Backend mypy.
  - Frontend tsc.
  - Backend pytest (all 65+ tests).
  - Frontend tests.
- [ ] Verify zero regressions and 100% green status.

