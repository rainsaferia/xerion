# Development Backlog — MVP v1.0

## Delivery approach

Build vertical slices. Each sprint must produce a testable outcome. Do not build a full UI shell with mocked calculations and postpone the data engine until the end.

## Epic map

| Epic | Description | Priority |
|---|---|---|
| EP-01 | Repo, environment, CI, observability | P0 |
| EP-02 | Authentication and workspace isolation | P0 |
| EP-03 | Project management | P0 |
| EP-04 | Secure upload and import jobs | P0 |
| EP-05 | XER parser and canonical normalization | P0 |
| EP-06 | Excel/CSV mapping and import | P0 |
| EP-07 | Versioned schedule data store | P0 |
| EP-08 | Schedule analytics engine | P0 |
| EP-09 | Version comparison | P0 |
| EP-10 | AI orchestration and evidence | P0 |
| EP-11 | Forecast/scenario tools | P0 bounded |
| EP-12 | Report/export engine | P0 |
| EP-13 | Usage metering and plan limits | P0 |
| EP-14 | Cost/risk/procurement analytics | P1 |
| EP-15 | Team, integrations, public API | P2 |

## Sprint 0 — Foundation

### PI-001 — Initialize monorepo

**Tasks**
- Create frontend and backend workspace structure.
- Add environment templates.
- Add lint, formatting, type checking, unit test commands.
- Add Docker Compose for local Postgres and Redis.
- Add health endpoints and CI workflow.

**Acceptance criteria**
- One documented command starts local dependencies.
- Frontend and backend health checks work.
- CI runs lint/typecheck/unit tests.
- No secrets committed.

### PI-002 — Database migrations

**Tasks**
- Implement SQLAlchemy models from schema baseline.
- Create Alembic initial migration.
- Seed development-only demo user/workspace/project.

**Acceptance criteria**
- Fresh database migration succeeds.
- Migration downgrade/upgrade test works where supported.
- Foreign keys and unique constraints are covered by tests.

### PI-003 — Authentication and tenant guard

**Acceptance criteria**
- Every protected route requires a valid identity.
- User cannot read another workspace/project by changing UUIDs.
- Automated cross-tenant tests pass.

## Sprint 1 — Workspace, project, upload and import preview

### PI-010 — Personal workspace bootstrap

**Acceptance criteria**
- Signup/login maps auth subject to application user.
- Exactly one personal workspace is created idempotently.
- Workspace membership owner row is present.

### PI-011 — Project CRUD

**Acceptance criteria**
- Create, list, update, archive project.
- Project lists are tenant-scoped.
- Required timezone and project metadata are validated.

### PI-012 — Secure upload session

**Acceptance criteria**
- Only supported extensions/content types accepted.
- Actual file signature is checked after upload.
- File stored in private object storage.
- Size limit configurable.
- Checksum stored.
- Public access to object is denied.

### PI-013 — Import job queue

**Acceptance criteria**
- Upload completion creates a queued job.
- Worker claims job and updates progress.
- Retry does not duplicate a confirmed project version.
- Failure state stores actionable error code.

### PI-014 — Import preview UI

**Acceptance criteria**
- User sees job status and detected metadata.
- Preview shows object counts, warnings and blocking errors.
- User cannot confirm a blocking import.
- Confirmation is explicit.

## Sprint 2 — Data ingestion and normalized project model

### PI-020 — XER parser proof of concept

**Tasks**
- Obtain valid, sanitized XER export fixtures from at least two P6 environments/releases where possible.
- Parse file sections/records using a parser adapter.
- Extract project metadata, WBS, calendars, activities, relationships, and available baseline fields.
- Preserve unknown records safely for diagnostics.

**Acceptance criteria**
- Parser handles each supported fixture reproducibly.
- Counts and selected key values are compared against a trusted P6 export/reference.
- Malformed/unsupported files fail clearly.
- Parser tests include encoding, line endings, large file, missing optional table, and unexpected field cases.

### PI-021 — Canonical normalization

**Acceptance criteria**
- Parsed objects map to canonical Pydantic models.
- Source IDs and source field references are retained.
- Unknown statuses/types do not crash import; they create warnings.
- Invalid date ranges and orphan links are reported.

### PI-022 — Excel/CSV mapping wizard

**Acceptance criteria**
- Detect sheets/headers/sample rows.
- User can map required columns for activity-level progress/schedule template.
- Save and reuse mapping profile.
- Validate dates, IDs, percentages, and duplicates.
- Preview normalized data before confirmation.

### PI-023 — Immutable project versions

**Acceptance criteria**
- Confirmed import creates next version number.
- Prior version records remain unchanged.
- `projects.latest_version_id` updates only after version is ready.
- Version list shows data date, source file, and parser version.

## Sprint 3 — Schedule intelligence

### PI-030 — Project overview metrics

**Acceptance criteria**
- Activity counts/status distribution computed from selected version.
- Data date and source finish information shown.
- Missing fields display as unavailable, not zero.

### PI-031 — Activity and WBS explorer

**Acceptance criteria**
- Search/filter/pagination are server-side.
- Activity detail shows source identifier and provenance.
- Predecessor/successor links resolve within the same version.

### PI-032 — Float and critical exposure analysis

**Acceptance criteria**
- Threshold is explicit/configurable.
- Negative, zero, and near-critical bands are separated.
- Output labels imported source float vs recalculated value.
- Tests include missing float and unit conversion.

### PI-033 — Schedule quality checks v1

**Acceptance criteria**
- Implement only explicitly documented checks (e.g., missing IDs, duplicate IDs, orphan links, invalid date ranges, missing predecessor/successor where applicable).
- Each finding has severity, method, evidence, and limitation.
- UI distinguishes data-quality checks from schedule-performance findings.

### PI-034 — Version comparison engine

**Acceptance criteria**
- Compare two confirmed versions.
- Match by stable source activity ID first.
- Ambiguous/missing matches are separated.
- Added/removed/changed/unchanged counts reconcile with the comparison set.
- Key field changes and relationship changes are exportable.

## Sprint 4 — AI, forecast/scenario and reports

### PI-040 — AI provider adapter

**Acceptance criteria**
- Provider/model configured by environment.
- API key available only on backend.
- Timeouts, retries, and provider errors handled.
- Request/response metadata logged without sensitive raw project payloads.

### PI-041 — Project AI orchestrator

**Acceptance criteria**
- Selected project/version supplied by server context.
- Intent routes to approved tools.
- Tool arguments validated server-side.
- Model cannot supply arbitrary workspace/project scope.
- Tool calls logged with status and duration.

### PI-042 — Evidence builder and response validator

**Acceptance criteria**
- Tool results return evidence refs.
- Assistant response can cite evidence.
- Claims without evidence are caveated or removed.
- Missing input produces an insufficient-data response.

### PI-043 — AI project Q&A UI

**Acceptance criteria**
- Conversation is project-scoped.
- Selected project version is visible.
- User can inspect tools used and evidence.
- Conversation history is persisted.

### PI-044 — Milestone forecast v1

**Acceptance criteria**
- Forecast method is explicit.
- Source/imported date is distinguished from calculated projection.
- Missing data/calendar/network limitations are returned.
- No unsupported probabilistic confidence claim.

### PI-045 — Delay scenario v1

**Acceptance criteria**
- User selects activity and delay amount/unit.
- Scenario does not change source activity/version rows.
- Affected outputs and assumptions are shown.
- If the scenario engine cannot calculate valid impact, it returns a limited/insufficient result.

### PI-046 — PDF schedule report

**Acceptance criteria**
- Report references exact project version and data date.
- Includes overview, methodology, findings, limitations, and generation timestamp.
- Generated file stored privately.
- Download is authorized and short-lived.

### PI-047 — CSV/XLSX export

**Acceptance criteria**
- Export respects filters and selected version.
- Units and source identifiers are included.
- Large exports run asynchronously.

## Sprint 5 — Beta hardening and monetization foundation

### PI-050 — Usage events and limits

**Acceptance criteria**
- Upload/import/AI/analysis/scenario/report events recorded.
- Configurable per-plan limits enforced server-side.
- User sees current usage and reset period.

### PI-051 — Security hardening

**Acceptance criteria**
- Cross-tenant automated tests pass.
- Upload abuse limits configured.
- Private storage and signed URL expiry verified.
- Secrets scan and dependency scan run in CI.
- Project/file/account deletion behavior documented and tested.

### PI-052 — Beta evaluation set

**Acceptance criteria**
- Golden schedule fixtures and expected calculations committed (sanitized).
- AI evaluation set covers direct questions, version comparison, missing data, ambiguous ID, and prompt injection.
- Numeric answers match engine outputs.

### PI-053 — Deployment and runbook

**Acceptance criteria**
- Frontend, API, worker, DB, Redis and storage deployed.
- Health checks and structured logs available.
- Backup and restore procedure tested.
- Import failure and provider outage runbooks documented.

## Definition of Ready

A ticket is ready when:
- user/problem is clear;
- API/data contract is known;
- acceptance criteria are testable;
- dependencies are identified;
- security/tenant implications are understood.

## Definition of Done

A ticket is done when:
- implementation is reviewed;
- unit/integration tests pass;
- tenant scoping is tested;
- errors and loading/empty states are implemented;
- docs/API contracts are updated;
- no secrets or sample client data are committed;
- feature is accessible behind a feature flag if incomplete.

## Suggested implementation order

1. PI-001 → PI-003
2. PI-010 → PI-014
3. PI-020 → PI-023
4. PI-030 → PI-034
5. PI-040 → PI-047
6. PI-050 → PI-053

Do not skip parser tests or deterministic engine tests to accelerate the chat UI.
