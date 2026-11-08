# REST API Specification — v1.0

Base path: `/api/v1`  
Auth: Bearer access token/session verified by backend  
Content type: `application/json` except multipart file upload  

## 1. API conventions

- All endpoints are workspace-scoped through authenticated membership. Client-supplied `workspace_id` is never sufficient authorization.
- Project/version identifiers are UUIDs.
- Timestamps are ISO 8601 UTC. Project schedule dates must retain source semantics and are not silently converted between timezones.
- Pagination uses `limit` and `cursor` (preferred) or bounded page/offset for simple lists.
- Standard error envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request could not be processed.",
    "details": [],
    "request_id": "req_xxx"
  }
}
```

## 2. Authentication and account

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/me` | Current user and plan/usage summary |
| PATCH | `/me` | Update display name and locale |
| GET | `/workspaces` | List user's workspaces |
| POST | `/workspaces` | Create workspace (future team path; personal workspace auto-created) |
| GET | `/workspaces/{workspace_id}` | Workspace detail |

## 3. Projects

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/projects` | List projects available to current user |
| POST | `/projects` | Create project |
| GET | `/projects/{project_id}` | Project detail and latest version |
| PATCH | `/projects/{project_id}` | Update project profile |
| POST | `/projects/{project_id}/archive` | Archive project |
| GET | `/projects/{project_id}/versions` | List version history |
| GET | `/projects/{project_id}/versions/{version_id}` | Version metadata and quality summary |

### Create project request

```json
{
  "name": "Gas Processing Facility EPC",
  "project_code": "GPF-001",
  "description": "Project description",
  "industry": "EPC",
  "currency_code": "USD",
  "timezone": "Asia/Makassar"
}
```

## 4. File upload and import

Preferred flow:

1. `POST /projects/{project_id}/uploads` creates an upload record and returns upload strategy.
2. Browser uploads to private storage using an authorized mechanism or sends multipart to backend.
3. `POST /uploads/{file_id}/complete` validates completion and queues import.
4. `GET /imports/{import_job_id}` polls job state.
5. `GET /imports/{import_job_id}/preview` returns preview, warnings, errors, and detected metadata.
6. `POST /imports/{import_job_id}/confirm` confirms import and creates a project version.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/projects/{project_id}/uploads` | Create upload session |
| POST | `/uploads/{file_id}/complete` | Confirm uploaded bytes and queue processing |
| GET | `/uploads/{file_id}` | File metadata |
| DELETE | `/uploads/{file_id}` | Delete or quarantine file according to lifecycle policy |
| GET | `/imports/{import_job_id}` | Import job status |
| GET | `/imports/{import_job_id}/preview` | Import preview |
| POST | `/imports/{import_job_id}/mapping` | Save mapping selection for XLSX/CSV |
| POST | `/imports/{import_job_id}/confirm` | Confirm and create immutable version |
| POST | `/imports/{import_job_id}/retry` | Retry failed job if safe/idempotent |

### Upload session response

```json
{
  "file_id": "uuid",
  "upload_method": "signed_url",
  "upload_url": "short-lived-url",
  "expires_at": "2026-11-03T10:30:00Z",
  "required_headers": {}
}
```

Do not place storage credentials in this response. The signed URL must be short-lived and scoped to one object key.

### Import job response

```json
{
  "id": "uuid",
  "status": "preview_ready",
  "progress_pct": 100,
  "detected_metadata": {
    "source_format": "xer",
    "project_name": "Gas Processing Facility EPC",
    "data_date": "2026-10-31"
  },
  "preview_summary": {
    "activities": 1240,
    "wbs_nodes": 86,
    "relationships": 2081,
    "calendars": 4
  },
  "warnings": [],
  "errors": []
}
```

## 5. Project overview and schedule analytics

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/projects/{project_id}/overview?version_id=` | Dashboard summary |
| GET | `/projects/{project_id}/activities?version_id=&q=&status=&wbs_id=&float_max=&limit=&cursor=` | Activity list/search |
| GET | `/projects/{project_id}/activities/{activity_id}?version_id=` | Activity detail |
| GET | `/projects/{project_id}/activities/{activity_id}/relationships?version_id=` | Predecessors/successors |
| GET | `/projects/{project_id}/wbs?version_id=` | WBS tree |
| GET | `/projects/{project_id}/schedule/float-distribution?version_id=` | Float histogram/bands |
| POST | `/projects/{project_id}/schedule/quality-checks` | Run selected schedule checks |
| POST | `/projects/{project_id}/versions/compare` | Compare two versions |
| POST | `/projects/{project_id}/schedule/scenarios/delay` | Run delay scenario |

### Version compare request

```json
{
  "from_version_id": "uuid",
  "to_version_id": "uuid",
  "fields": ["status", "start_date", "finish_date", "total_float_hours", "physical_pct_complete", "relationships"],
  "limit": 100
}
```

### Delay scenario request

```json
{
  "version_id": "uuid",
  "activity_source_id": "A-1000",
  "delay_value": 10,
  "delay_unit": "working_days",
  "scenario_name": "Equipment delivery +10 working days"
}
```

Response must include method, assumptions, affected activities/milestones, warnings, and evidence refs. If calendar/network fidelity is insufficient, return `insufficient_data` or a limited scenario result rather than a false-precision date.

## 6. AI conversations

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/projects/{project_id}/conversations` | List conversations |
| POST | `/projects/{project_id}/conversations` | Create conversation |
| GET | `/conversations/{conversation_id}` | Conversation detail |
| POST | `/conversations/{conversation_id}/messages` | Send user message and run orchestration |
| GET | `/conversations/{conversation_id}/messages` | Message history |

### Send message request

```json
{
  "content": "Which activities are most exposed to the project finish date?",
  "project_version_id": "uuid"
}
```

### AI response shape

```json
{
  "message_id": "uuid",
  "conversation_id": "uuid",
  "status": "completed",
  "answer": "The following activities have the lowest imported total float...",
  "blocks": [
    {"type": "paragraph", "text": "..."},
    {"type": "activity_table", "items": []},
    {"type": "evidence_list", "items": []}
  ],
  "evidence_refs": [],
  "assumptions": [],
  "limitations": [],
  "tool_executions": [],
  "suggested_actions": []
}
```

The frontend may stream progress states, but final claims and evidence must be validated server-side.

## 7. Reports and exports

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/projects/{project_id}/reports` | Generate a report |
| GET | `/reports/{report_id}` | Report status and metadata |
| GET | `/reports/{report_id}/download` | Short-lived download URL |
| POST | `/projects/{project_id}/exports/activities` | Create CSV/XLSX export |

Report request:

```json
{
  "version_id": "uuid",
  "report_type": "schedule_analysis",
  "format": "pdf",
  "options": {
    "include_activity_appendix": true,
    "language": "en"
  }
}
```

## 8. Usage and plan limits

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/usage/summary` | Usage by billing period |
| GET | `/plans` | Public plan/feature information |

Plan enforcement must occur server-side before expensive import, analytics, AI, and report operations.

## 9. API validation rules

- Reject unknown project/version combinations.
- Verify project belongs to a workspace the user can access.
- Bound every list/query result.
- Validate all numeric thresholds and date ranges.
- Prevent arbitrary object-key or filesystem path input.
- Apply rate limits on upload, AI, and scenario endpoints.
- Return explicit `insufficient_data` domain errors for unavailable calculations.
