# AI Agent & Tool Specification — v1.0

## 1. Product behavior

The AI assistant is a controlled project-analysis interface, not an autonomous system with unrestricted access.

It should:
- understand the user's intent and project context;
- select a supported analytics tool;
- execute the tool through the backend;
- explain its results with evidence;
- clarify missing context or data;
- suggest user-reviewed actions and report outputs.

It must not:
- invent schedule numbers or relationships;
- make up missing baseline/cost/progress values;
- run arbitrary SQL or Python from model-generated text;
- access files or projects outside the authenticated workspace;
- modify the source Primavera project in v1;
- claim that a forecast is a probability-based prediction when it is a deterministic projection.

## 2. Agent architecture

Use one orchestrator with bounded specialist capabilities. Do not create a complex multi-agent swarm in the MVP.

```text
User Question
   |
   v
Context Resolver
   |-- Authenticated user
   |-- Workspace/project access
   |-- Selected data version
   |-- Available datasets / data quality
   v
Intent Router / AI Orchestrator
   |-- Schedule Analysis Tools
   |-- Version Comparison Tools
   |-- Forecast & Scenario Tools
   |-- Report Tools
   v
Tool Argument Validator
   v
Backend Analytics Services
   v
Evidence Builder
   v
Response Composer
   v
Answer + Evidence + Assumptions + Suggested Next Steps
```

## 3. Capability groups

### A. Schedule Analyst

Use for:
- project schedule overview;
- activity lookup and detail;
- WBS-level summaries;
- critical/near-critical activity lists;
- total float distribution;
- relationship inspection;
- schedule quality diagnostics.

### B. Version Comparison Analyst

Use for:
- compare previous and latest versions;
- detect changed dates, float, duration, status, progress, and logic;
- summarize milestone movement;
- list additions/removals/ambiguous matches.

### C. Forecast & Scenario Analyst

Use for:
- report imported forecast milestone dates;
- calculate transparent deterministic forecast indicators;
- run bounded what-if delay scenarios;
- compare scenario outputs.

The first release should not claim statistical prediction unless the model is separately trained and validated against historical projects. When the system only uses current P6 dates/float/logic, label the output as schedule-derived forecast or scenario.

### D. Reporting Analyst

Use for:
- generate a schedule analysis report;
- create executive summary from validated findings;
- export activity/finding tables.

Report tools may create files but must not alter source schedule data.

## 4. Tool catalog

All tools are backend functions exposed to the model through JSON-schema function calling. Use strict schemas where supported. Every tool receives the authenticated workspace/project scope from server context; never trust model-supplied workspace IDs.

### Read-only tools (v1)

| Tool name | Purpose | Required inputs |
|---|---|---|
| `get_project_overview` | Project metadata and KPIs | project version context |
| `list_activities` | Filtered activity list | filters, sort, limit |
| `get_activity_detail` | Activity fields and source evidence | activity source ID or platform ID |
| `get_activity_relationships` | Predecessor/successor detail | activity ID, direction |
| `get_critical_activities` | Activities classified by selected float threshold | threshold hours, limit |
| `get_float_distribution` | Float bands and counts | band configuration |
| `analyze_schedule_quality` | Supported schedule checks | check set |
| `compare_project_versions` | Version difference summary | from version, to version |
| `get_milestone_forecast` | Imported or deterministic milestone forecast | milestone or finish selector, method |
| `simulate_activity_delay` | Bounded delay scenario | activity, delay amount/unit, scenario label |
| `get_data_quality_summary` | Missing/unsupported data summary | project version |

### Output tools (v1)

| Tool name | Purpose | Confirmation |
|---|---|---|
| `create_action_items` | Create user-reviewed action register entries | Explicit user request / confirmation |
| `generate_schedule_report` | Create report artifact | Explicit user request |
| `export_activity_data` | Export filtered activity data | Explicit user request |

These output functions should be invoked only after the user clearly asks for an artifact/action or confirms the assistant's proposal. A suggested follow-up is not authorization to create an artifact.

## 5. Example tool schemas

### get_critical_activities

```json
{
  "type": "function",
  "name": "get_critical_activities",
  "description": "Return activities classified by a configurable total-float threshold for the selected project version. This is a classification, not proof of causation.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "float_threshold_hours": {"type": "number", "minimum": 0},
      "include_negative_float": {"type": "boolean"},
      "limit": {"type": "integer", "minimum": 1, "maximum": 100}
    },
    "required": ["float_threshold_hours", "include_negative_float", "limit"],
    "additionalProperties": false
  }
}
```

### compare_project_versions

```json
{
  "type": "function",
  "name": "compare_project_versions",
  "description": "Compare two confirmed versions of the same project using stable source identifiers; return ambiguous matches separately.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "from_version_number": {"type": "integer", "minimum": 1},
      "to_version_number": {"type": "integer", "minimum": 1},
      "fields": {
        "type": "array",
        "items": {"type": "string", "enum": ["activity_name", "wbs", "status", "start_date", "finish_date", "remaining_duration_hours", "total_float_hours", "physical_pct_complete", "relationships"]}
      },
      "limit": {"type": "integer", "minimum": 1, "maximum": 200}
    },
    "required": ["from_version_number", "to_version_number", "fields", "limit"],
    "additionalProperties": false
  }
}
```

### simulate_activity_delay

```json
{
  "type": "function",
  "name": "simulate_activity_delay",
  "description": "Run a bounded what-if delay scenario against the selected version. Results are scenario estimates and must disclose model limitations.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {
      "activity_source_id": {"type": "string", "minLength": 1},
      "delay_value": {"type": "number", "exclusiveMinimum": 0},
      "delay_unit": {"type": "string", "enum": ["working_days", "calendar_days", "hours"]},
      "scenario_name": {"type": "string", "maxLength": 100}
    },
    "required": ["activity_source_id", "delay_value", "delay_unit", "scenario_name"],
    "additionalProperties": false
  }
}
```

## 6. Tool execution contract

Every tool response should follow a predictable structure:

```json
{
  "status": "ok",
  "project_version_id": "uuid",
  "tool_name": "get_critical_activities",
  "method": "source_total_float_threshold",
  "parameters": {"float_threshold_hours": 40},
  "summary": {"matched_count": 12},
  "items": [],
  "evidence_refs": [],
  "warnings": [],
  "limitations": []
}
```

Error response:

```json
{
  "status": "insufficient_data",
  "code": "BASELINE_NOT_AVAILABLE",
  "message": "A baseline is not available for the selected project version.",
  "required_inputs": ["baseline activity dates"]
}
```

## 7. Evidence contract

Each material finding includes:

- `evidence_id`
- `project_version_id`
- `entity_type`
- `entity_platform_id`
- `source_identifier`
- `field_name`
- `source_value`
- `normalized_value`
- `unit`
- `source_file_id`
- `source_location` (e.g., source table/record or worksheet/row when available)
- `method`
- `calculation_run_id` (if derived)

UI should display evidence as clickable activity/WBS references and source provenance. Do not expose internal storage object keys.

## 8. System instructions for the assistant

Recommended developer instruction baseline:

```text
You are the Project Intelligence Assistant for EPC project professionals.

Use the selected project and project version supplied by the application. Do not assume that a different project or newer version is intended.

For numerical, schedule, variance, forecast, and comparison questions, call the appropriate approved tools. Never calculate or invent project metrics from memory. Do not write SQL or access files directly.

Distinguish:
- source facts imported from Primavera/Excel;
- deterministic calculations performed by the platform;
- scenario assumptions entered by the user;
- forecasts derived from a stated method;
- recommendations that require human judgment.

Cite activity IDs, WBS, project version, data date, and evidence references where available. If the required data is missing, explain exactly what is missing and do not fill the gap with guesses.

A low-float activity is a schedule exposure indicator, not automatically the root cause of delay. Explain dependencies and evidence before making causal claims.

Never change source project data. For report/action creation, require a clear user request or confirmation. Keep recommendations practical, concise, and suitable for an EPC project-control professional.
```

## 9. Intent routing examples

| User asks | Route |
|---|---|
| "Summarize this project." | `get_project_overview` |
| "Which activities have less than 5 days float?" | Convert days to hours using project working-time assumptions or ask if ambiguous; call `get_critical_activities`. |
| "What changed since last week?" | `compare_project_versions` on previous vs latest confirmed version. |
| "Why did the finish date move?" | Version comparison + milestone/relationship/activity evidence; avoid causal claim without network support. |
| "What if activity A-100 is delayed 10 working days?" | `simulate_activity_delay`; disclose calendar/model limitations. |
| "Make a weekly schedule report." | Gather overview/findings then ask confirmation or proceed if request is explicit; call report generator. |
| "Calculate SPI." | Check whether validated PV and EV exist and what progress/cost basis is used; otherwise explain missing inputs. |

## 10. Human approval and write boundaries

v1 permissions:
- Read project data: allowed after access check.
- Run calculations: allowed; logs created.
- Run scenarios: allowed; scenario is separate from source data.
- Generate exports/reports: only after explicit request.
- Create action register entries: explicit user request/confirmation.
- Modify activities, relationships, dates, baselines, or source files: not supported.

Future write-back or system integrations must use a separate approval model with preview, diff, user confirmation, audit log, and rollback/compensation strategy.

## 11. Evaluation and test cases

Create a golden evaluation set with:
- direct fact lookup;
- schedule summary;
- critical/near-critical filter;
- baseline unavailable;
- ambiguous activity identifier;
- previous-vs-current comparison;
- missing data date;
- missing calendar;
- unsupported relationship type;
- what-if scenario with an incomplete network;
- prompt injection text embedded in an uploaded worksheet;
- cross-tenant access attempt.

Scoring:
- tool selection correctness;
- argument correctness;
- numeric consistency with engine;
- evidence validity;
- uncertainty handling;
- no unauthorized action;
- response clarity.
