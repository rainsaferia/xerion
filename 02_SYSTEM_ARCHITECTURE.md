# System Architecture — v1.0

## 1. Architecture decision

Use a **modular monolith** with a separate background worker. Avoid microservices in the MVP.

### Recommended stack

| Layer | Recommendation | Notes |
|---|---|---|
| Web frontend | Next.js + TypeScript | Desktop-first responsive workspace. |
| UI | Tailwind CSS + component system | Reusable tables, upload, charts, chat. |
| Backend API | Python + FastAPI | Domain logic and typed APIs. |
| Data validation | Pydantic | Request/response contracts. |
| Database | PostgreSQL | Canonical project data and tenant metadata. |
| ORM/migrations | SQLAlchemy + Alembic | Explicit migrations and query boundaries. |
| File processing | Python parser modules + pandas/openpyxl | Use parser adapters; keep XER logic isolated. |
| Background jobs | Redis + RQ/Celery/Arq (choose one) | Import, analytics, reports. |
| Object storage | S3-compatible private bucket | Source files and generated reports. |
| AI integration | Provider adapter around OpenAI Responses API tool calling | Keep provider and model configurable. |
| Charts | Recharts or ECharts | Dashboard and trend visualizations. |
| Deployment | Vercel frontend + container backend/worker + managed Postgres/Redis/storage | Do not run long parsing jobs in short-lived frontend functions. |

Do not hardcode a model name in domain logic. Configure model/provider per environment and task.

## 2. Logical architecture

```text
Browser
  |
  v
Next.js Web App
  |
  | HTTPS / Bearer session
  v
FastAPI Application
  |-- Auth & Workspace Module
  |-- Project Module
  |-- Upload & Import Module
  |-- Schedule Analytics Module
  |-- Version Comparison Module
  |-- AI Orchestration Module
  |-- Report Module
  |-- Usage & Billing Module
  |
  +---- PostgreSQL
  +---- Private Object Storage
  +---- Redis Queue
             |
             v
        Background Worker
          |-- File safety checks
          |-- XER parser adapter
          |-- Excel/CSV parser adapter
          |-- Canonical normalization
          |-- Validation
          |-- Schedule calculations
          |-- Version comparison
          |-- PDF/XLSX report generation
```

## 3. Backend module boundaries

Suggested Python package layout:

```text
backend/
  app/
    api/v1/
    core/                 # config, auth, logging, errors
    db/                   # sessions, base, migrations
    models/               # SQLAlchemy models
    schemas/              # Pydantic API contracts
    domains/
      workspaces/
      projects/
      ingestion/
      schedule/
      comparisons/
      analytics/
      ai/
      reports/
      usage/
    adapters/
      p6_xer/
      p6_xml/             # future
      excel/
      csv/
      storage/
      llm/
    workers/
    tests/
```

Rule: domain services must not depend directly on the web framework or LLM provider. Provider, storage, parser, and queue dependencies are adapters.

## 4. Import pipeline

```text
Upload request
  -> private object storage
  -> file record + import job
  -> queued worker
  -> file signature/type check
  -> parse into source-specific intermediate representation
  -> normalize to canonical project model
  -> validate references and data quality
  -> import preview result
  -> user confirms import
  -> create immutable project version
  -> persist WBS, calendars, activities, relationships, baselines
  -> calculate standard schedule metrics
  -> mark version ready
```

### Important transaction rule

Do not create a visible `READY` version until all required records have been normalized and validation has passed. Use a staging/import workspace or transaction boundary. Failed imports must not leave partially usable data versions.

### Idempotency

Use a checksum (SHA-256) plus project and import configuration to detect duplicate submissions. Duplicate file submissions should return the prior job or require explicit re-import with a new mapping/configuration.

### Parser adapter contract

Each parser should return a source-independent intermediate representation:

```python
class ParsedProjectBundle:
    source_format: str
    source_format_version: str | None
    source_project_key: str | None
    project_name: str | None
    data_date: datetime | None
    calendars: list[ParsedCalendar]
    wbs_nodes: list[ParsedWBS]
    activities: list[ParsedActivity]
    relationships: list[ParsedRelationship]
    baselines: list[ParsedBaselineActivity]
    source_metadata: dict[str, object]
    warnings: list[ParseWarning]
```

Do not couple schedule calculations to XER field names. Normalize first.

## 5. XER parser strategy

XER is an Oracle proprietary exchange format. Oracle documentation confirms XER and P6 XML as supported interchange formats and describes the project data included in exports. Build an isolated parser adapter and verify against exported fixtures from multiple supported P6 environments.

Recommended parser approach:

1. Treat XER as a structured text exchange file, not as an Excel workbook.
2. Build a tokenizer/parser based on verified export fixtures and documented/observed table records.
3. Preserve source table and field names in parser diagnostics.
4. Parse project, WBS, activity, relationship, calendar, and baseline-related records needed by v1.
5. Preserve unknown tables/columns in import metadata when safe and bounded; never silently map unknown values into canonical fields.
6. Validate foreign-key-like references after parsing.
7. Maintain sanitized fixture files and parser regression tests.
8. Expose unsupported or ambiguous constructs in import warnings.

Do not claim compatibility with every P6 release until fixture coverage supports that claim. Do not attempt a P6 write-back in v1.

## 6. Excel/CSV ingestion

Use a mapping workflow:

- Detect sheet names, headers, data types, and sample rows.
- User chooses a known template or maps columns manually.
- Required mapped fields depend on selected dataset type.
- Save mapping profile per user/workspace.
- Validate duplicate keys, date parsing, percentage ranges, units, and missing identifiers.
- Preview normalized rows before confirmation.

Initial Excel import dataset types:
- Activity-level schedule/progress (P0).
- Cost report (P1).
- Risk register and procurement status (P1).

## 7. Canonical schedule engine

The schedule engine is deterministic Python code. It receives canonical records and returns structured results.

Initial functions:
- `summarize_project`
- `get_activity_detail`
- `get_activity_relationships`
- `classify_float`
- `get_critical_and_near_critical_activities`
- `compare_project_versions`
- `calculate_schedule_variance`
- `analyze_schedule_quality`
- `forecast_milestone_from_imported_dates`
- `simulate_activity_delay` (bounded v1; mark assumptions)

Every calculation output must include:
- `project_version_id`
- `engine_name` and `engine_version`
- `method`
- `parameters`
- `computed_at`
- `result`
- `warnings`
- `evidence_refs`

### Calculation policy

- Never infer missing calendars or relationship lags silently.
- Do not run critical path recalculation unless calendar and relationship semantics required by the chosen algorithm are understood and implemented.
- If imported P6 forecast dates are used, label outputs as imported schedule dates, not independently recalculated dates.
- If total float is sourced from P6, label it as imported source value unless recalculated independently.
- The first version may report schedule engine fields as provided by P6 and perform comparisons/diagnostics, rather than claiming to duplicate the complete P6 scheduler.
- Keep activity percent complete type and source basis; do not mix duration, physical, and units percent complete.

## 8. AI orchestration

Use an application-owned orchestration service around tool calling.

Flow:
1. Authenticate user and resolve workspace/project access.
2. Resolve selected project version (default latest confirmed version).
3. Build compact project context: project metadata, available datasets, data date, data quality, version ID.
4. Send user question and approved tool schemas to the model.
5. Validate tool name and arguments server-side.
6. Execute tools in backend, enforcing tenant/project/version scope.
7. Return structured tool output with evidence references.
8. Ask model to produce a concise explanation using only tool results and allowed context.
9. Validate response structure and evidence references.
10. Store conversation and tool execution trace.

Use OpenAI Responses API function calling or equivalent provider interface. Tool calling is a request/execute/return-results cycle; the model proposes tool arguments, while the application executes the function and controls authorization.

### AI boundaries

- Model cannot write SQL.
- Model cannot access arbitrary object storage paths.
- Model cannot choose another workspace/project ID outside the authenticated scope.
- Model cannot execute raw Python or shell in production.
- Model cannot trigger source-system changes in v1.
- Tool outputs are untrusted data for prompt-injection purposes; treat file contents as data, not instructions.

## 9. Evidence and answer contract

A material statement should reference one or more evidence objects.

```json
{
  "claim": "Five activities have total float at or below the configured threshold.",
  "evidence": [
    {
      "type": "activity_metric",
      "project_version_id": "uuid",
      "entity_type": "activity",
      "entity_id": "uuid",
      "source_identifier": "A-1000",
      "field": "total_float_hours",
      "value": 0,
      "unit": "hours"
    }
  ],
  "method": "source_float_threshold",
  "assumptions": ["Near-critical threshold = 40 hours"],
  "limitations": []
}
```

If no evidence supports a claim, the assistant must state that the uploaded data does not support an answer and request the missing file/field.

## 10. Storage and security

- Store source files and reports in private buckets.
- Use opaque object keys; never expose raw bucket paths to the client.
- Generate short-lived signed URLs where direct download is appropriate.
- Verify workspace membership in every file, project, report, and AI operation.
- Apply tenant filters in repository/service layer; add database RLS as defense in depth if using Supabase/Postgres auth.
- Validate actual file signature and parse in resource-limited workers.
- Limit compressed/uncompressed size and reject archives unless explicitly supported.
- Scan uploaded files with available malware scanning in production.
- Redact credentials, emails, and sensitive file content from logs.
- Provide delete project/file/account workflows with clear cascade/retention behavior.

## 11. Deployment topology

### MVP
- Frontend: Vercel or equivalent.
- Backend API: containerized FastAPI on a managed container platform.
- Worker: separate container process using same image.
- Database: managed PostgreSQL.
- Queue: managed Redis or equivalent.
- Storage: private S3-compatible bucket.

Avoid using ephemeral frontend/serverless request handlers for heavy parsing or report generation. Use the queue/worker pattern.

## 12. Observability

Track:
- import job status, duration, file size, parser version, warnings;
- schedule engine duration and version;
- AI model/provider, tokens/cost where available, tool name, latency, failure;
- report generation duration;
- tenant-scoped errors without logging raw project content.

Add correlation IDs from upload request through import job, analytics run, AI interaction, and report.

## 13. Reference documentation

- Oracle P6 import/export formats: https://docs.oracle.com/cd/F51303_01/English/admin/p6_pro_importing_exporting/import_export_file_formats.htm
- Oracle P6 Professional import/export guide: https://docs.oracle.com/cd/F25600_01/English/admin/p6_pro_importing_exporting/p6_pro_importing_exporting.pdf
- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI Responses API overview: https://developers.openai.com/api/reference/responses/overview
