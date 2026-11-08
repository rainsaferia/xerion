# PI-021 Canonical Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement canonical Pydantic models and normalization logic in `app.domains.schedule` and `app.domains.ingestion`, converting parsed schedule bundles into normalized schedules while retaining source IDs/fields, creating diagnostic warnings for unknown statuses/types, and validating invalid date ranges and orphan links without crashing.

---

### Task 1: Canonical Pydantic Models (`app.domains.schedule.schemas`)

**Files:**
- Create `backend/app/domains/schedule/schemas.py`
- Modify `backend/app/domains/schedule/__init__.py`

**Steps:**
- [ ] Define canonical Pydantic models using strict types:
  - `CanonicalWBS`: source_id, wbs_code, wbs_name, parent_source_id, sort_order, source_fields
  - `CanonicalCalendar`: source_id, calendar_name, calendar_type, timezone, fidelity_status, source_fields
  - `CanonicalActivity`: source_id, activity_code, activity_name, wbs_source_id, calendar_source_id, status ("not_started", "in_progress", "complete", "suspended", "unknown"), source_status, planned_start, planned_finish, start_date, finish_date, actual_start, actual_finish, durations, float hours, % complete, source_fields
  - `CanonicalRelationship`: source_id, predecessor_source_id, successor_source_id, relationship_type ("FS", "SS", "FF", "SF", "unknown"), source_relationship_type, lag_hours, is_external, source_fields
  - `CanonicalBaseline`: source_activity_id, baseline_source_id, baseline_start, baseline_finish, baseline_duration_hours, baseline_pct_complete, baseline_label, source_fields
  - `NormalizationWarning`: code, message, entity_type, entity_source_id, details
  - `CanonicalProjectSchedule`: source_format, source_format_version, source_project_key, project_name, data_date, calendars, wbs_nodes, activities, relationships, baselines, source_metadata, warnings

---

### Task 2: Normalization Engine & Integrity Validator (`app.domains.ingestion.normalization`)

**Files:**
- Create `backend/app/domains/ingestion/normalization.py`

**Steps:**
- [ ] Implement `normalize_parsed_bundle(bundle_data: dict[str, Any]) -> CanonicalProjectSchedule`:
  - Maps WBS nodes, calendars, activities, relationships, and baselines into canonical models.
  - Converts datetimes/strings to `date` objects for schedule day boundaries (`start_date`, `finish_date`).
  - Preserves source IDs and raw source fields in `source_fields`.
  - Maps activity status safely; maps unrecognized status strings to `"unknown"`, records `source_status`, and appends `NormalizationWarning(code="UNKNOWN_ACTIVITY_STATUS")`.
  - Maps relationship types safely (`FS`, `SS`, `FF`, `SF`); maps unrecognized types to `"unknown"`, records `source_relationship_type`, and appends `NormalizationWarning(code="UNKNOWN_RELATIONSHIP_TYPE")`.
  - Detects invalid date ranges:
    - If `planned_start > planned_finish`, emits `INVALID_DATE_RANGE` warning.
    - If `actual_start > actual_finish`, emits `INVALID_ACTUAL_DATE_RANGE` warning.
  - Detects orphan links:
    - If predecessor not in activity source IDs, emits `ORPHAN_PREDECESSOR_LINK` warning.
    - If successor not in activity source IDs, emits `ORPHAN_SUCCESSOR_LINK` warning.
  - Detects self-loops (`predecessor == successor`), emits `SELF_LOOP_RELATIONSHIP` warning.

---

### Task 3: Comprehensive Test Suite (`backend/tests/test_canonical_normalization.py`)

**Files:**
- Create `backend/tests/test_canonical_normalization.py`

**Steps:**
- [ ] Test mapping parsed XER bundle into canonical Pydantic model (`CanonicalProjectSchedule`).
- [ ] Test retention of source IDs and unmapped fields in `source_fields`.
- [ ] Test unknown activity status: maps to `status="unknown"`, preserves `source_status`, creates warning without crashing.
- [ ] Test unknown relationship type: maps to `relationship_type="unknown"`, preserves `source_relationship_type`, creates warning.
- [ ] Test invalid date ranges: reports `INVALID_DATE_RANGE` and `INVALID_ACTUAL_DATE_RANGE`.
- [ ] Test orphan relationship links: reports `ORPHAN_PREDECESSOR_LINK` and `ORPHAN_SUCCESSOR_LINK`.
- [ ] Test self-loop relationships: reports `SELF_LOOP_RELATIONSHIP`.
- [ ] Verify `test_architecture.py` passes (domain isolation maintained).

---

### Task 4: Monorepo Quality Gate Verification

**Steps:**
- [ ] Run `cd backend && uv run pytest`
- [ ] Run `npm run check` across the monorepo.

