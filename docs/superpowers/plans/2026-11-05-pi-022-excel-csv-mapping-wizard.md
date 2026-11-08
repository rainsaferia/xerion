# PI-022 Excel/CSV Mapping Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement tabular inspection, mapping profile save/reuse, validation (dates, IDs, percentages, duplicates), and normalized data preview for Excel (XLSX) and CSV schedule files.

---

### Task 1: Tabular Inspector & Reader (`app.adapters.tabular`)

**Files:**
- Create `backend/app/adapters/tabular/__init__.py`
- Create `backend/app/adapters/tabular/reader.py`
- Create `backend/tests/test_tabular_reader.py`

**Steps:**
- [ ] Implement `inspect_tabular_bytes(data: bytes, format_hint: str = "csv") -> TabularInspection`:
  - CSV detection: dialect sniffing (delimiter `,`, `;`, `\t`), encoding fallback (UTF-8, Latin-1), extract headers, sample rows (up to 5), row count.
  - XLSX detection: sheet names, selected sheet extraction, headers, sample rows, row count using `openpyxl`.
- [ ] Implement `read_tabular_rows(data: bytes, format_hint: str, sheet_name: str | None = None) -> list[dict[str, Any]]`:
  - Streams rows as dictionaries matching column header names.
- [ ] Unit tests for CSV sniffing, multi-sheet XLSX inspection, and row streaming.

---

### Task 2: Mapping Profile Domain & Validation Engine (`app.domains.ingestion.mapping`)

**Files:**
- Create `backend/app/domains/ingestion/mapping.py`
- Modify `backend/app/domains/ingestion/__init__.py`

**Steps:**
- [ ] Define `ColumnMappingConfig(BaseModel)`:
  - `activity_code`: str (required)
  - `activity_name`: str (required)
  - `status`: str | None
  - `planned_start`: str | None
  - `planned_finish`: str | None
  - `actual_start`: str | None
  - `actual_finish`: str | None
  - `percent_complete`: str | None
  - `total_float`: str | None
  - `wbs_code`: str | None
  - `sheet_name`: str | None
- [ ] Implement `validate_and_normalize_tabular(rows: list[dict[str, Any]], mapping: ColumnMappingConfig) -> tuple[CanonicalProjectSchedule, list[dict[str, Any]]]`:
  - Validate required columns are mapped and present in rows.
  - Validate and report duplicate activity codes: `DUPLICATE_ACTIVITY_ID`.
  - Validate dates: parse date strings, report `INVALID_DATE_FORMAT` and `INVALID_DATE_RANGE`.
  - Validate percentages: parse numbers/percentages, report `PERCENTAGE_OUT_OF_BOUNDS` if < 0 or > 100.
  - Retain unmapped columns in `source_fields`.
  - Produce a valid `CanonicalProjectSchedule`.
- [ ] Mapping profile persistence helpers:
  - `save_mapping_profile(session, workspace_id, user_id, name, mapping_config, dataset_type) -> ImportMapping`
  - `list_mapping_profiles(session, workspace_id) -> list[ImportMapping]`
  - `get_mapping_profile(session, workspace_id, profile_id) -> ImportMapping | None`

---

### Task 3: API Endpoints for Mapping Wizard

**Files:**
- Modify `backend/app/api/v1/routes.py`
- Modify `backend/tests/test_import_jobs.py` (or new `backend/tests/test_mapping_wizard.py`)

**Steps:**
- [ ] `GET /api/v1/imports/{import_job_id}/inspect`:
  - Inspects uploaded file bytes (CSV/XLSX), returns sheet names, headers, sample rows, detected format.
- [ ] `POST /api/v1/imports/{import_job_id}/mapping`:
  - Applies mapping config (or profile ID), validates rows, generates normalized preview, stores preview summary and warnings, updates `job.status = "preview_ready"`.
  - Optionally saves profile if `save_profile_name` is provided.
- [ ] `GET /api/v1/workspaces/{workspace_id}/mappings`:
  - Lists saved mapping profiles for the workspace.
- [ ] `POST /api/v1/workspaces/{workspace_id}/mappings`:
  - Creates a reusable mapping profile.

---

### Task 4: Integration Tests & Quality Gate

**Files:**
- Create `backend/tests/test_mapping_wizard.py`

**Steps:**
- [ ] Test detecting CSV headers and sample rows.
- [ ] Test detecting XLSX multi-sheet workbook, headers, and sample rows.
- [ ] Test mapping columns and verifying preview summary.
- [ ] Test saving and reusing a mapping profile across jobs.
- [ ] Test reporting duplicate IDs, date errors, and percentage bounds.
- [ ] Verify `npm run check` (quality gate).

