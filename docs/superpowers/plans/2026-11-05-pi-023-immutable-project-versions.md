# PI-023 Immutable Project Versions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement immutable project version creation and persistence upon import confirmation, ensuring sequential version numbering, strict record isolation between versions, atomic latest_version_id updating, and version history APIs reporting data date, source file, and parser version.

---

### Task 1: Version Materialization Domain Service (`app.domains.projects.version_service`)

**Files:**
- Create `backend/app/domains/projects/version_service.py`
- Modify `backend/app/domains/projects/__init__.py`

**Steps:**
- [ ] Implement `create_version_from_confirmed_job(session: AsyncSession, job: ImportJob, user_id: uuid.UUID | None) -> ProjectVersion`:
  - Verify job is ready or confirmed, with no blocking errors.
  - Check idempotency: if `ProjectVersion` already exists for `job.id`, return it.
  - Calculate `next_version_number = (max(version_number) for project) + 1`.
  - Create `ProjectVersion(status="staging")`.
  - Materialize canonical entities from normalized schedule bundle / file:
    - Insert `WBSNode` rows and build `{source_id: wbs_node_id}` mapping.
    - Insert `Calendar` rows and build `{source_id: calendar_id}` mapping.
    - Insert `Activity` rows with foreign keys to WBS and Calendar, and build `{source_id: activity_id}` mapping.
    - Insert `ActivityRelationship` rows resolving predecessor and successor UUIDs.
    - Insert `BaselineActivityValue` rows.
  - Compute project dates (`project_start_date`, `project_finish_date`) from min start and max finish.
  - Transition version to `status="ready"`.
  - Update `project.latest_version_id = version.id`.
  - Update `job.status = "confirmed"` and `job.finished_at`.
  - Flush / return version.
- [ ] Implement version query helpers:
  - `list_project_versions(session, project_id) -> list[tuple[ProjectVersion, str]]` (with source filename)
  - `get_project_version(session, project_id, version_id) -> tuple[ProjectVersion, str] | None`

---

### Task 2: API Endpoints for Versions and Confirm Integration

**Files:**
- Modify `backend/app/api/v1/routes.py`

**Steps:**
- [ ] Define response schemas:
  - `ProjectVersionOut`: id, project_id, version_number, version_label, source_filename, source_format, parser_version, data_date, status, activity_count, created_at
  - `ProjectVersionDetailOut`: extends `ProjectVersionOut` with quality_summary, source_metadata, project_start_date, project_finish_date
- [ ] Update `POST /api/v1/imports/{import_job_id}/confirm`:
  - Calls `create_version_from_confirmed_job`.
  - Commits transaction atomically.
  - Returns updated `ImportJobOut` with `project_version_id` reference.
- [ ] Implement `GET /api/v1/projects/{project_id}/versions`:
  - Protected by `ProjectAccess` (tenant-scoped).
  - Returns list of `ProjectVersionOut`.
- [ ] Implement `GET /api/v1/projects/{project_id}/versions/{version_id}`:
  - Protected by `ProjectAccess` (tenant-scoped).
  - Returns `ProjectVersionDetailOut`.

---

### Task 3: Comprehensive Test Suite (`backend/tests/test_project_versions.py`)

**Files:**
- Create `backend/tests/test_project_versions.py`

**Steps:**
- [ ] Test confirmed import creates next sequential version number (V1 -> V2).
- [ ] Test prior version records remain unchanged (verifying separate activity records and counts across V1 and V2).
- [ ] Test `projects.latest_version_id` updates only after version is ready.
- [ ] Test version list API returns data date, source file, parser version, and activity count.
- [ ] Test tenant isolation (cross-tenant user cannot view versions).
- [ ] Verify `test_architecture.py` passes with zero violations.

---

### Task 4: Full Monorepo Quality Gate Verification

**Steps:**
- [ ] Run `npm run check` (quality gate across backend and frontend).

