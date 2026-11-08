# Product Requirements Document (PRD)
## Project Intelligence Platform — v1.0

**Status:** Draft baseline for MVP implementation  
**Product type:** Multi-tenant Micro SaaS  
**Initial market:** EPC / Oil & Gas / Industrial Projects  
**Initial user:** Individual Project Control professionals  
**Primary language:** English UI-ready, with Indonesian/English AI response support planned  

---

## 1. Executive summary

Project Intelligence Platform (working name) is a web-based workspace that converts project files into structured project data, performs deterministic analysis, and uses AI tools to explain findings, prepare forecasts/scenarios, and generate work-ready outputs.

The product is not a document chatbot. It is an intelligence layer above Primavera P6 and Excel workflows.

### Core value proposition

**From Project Data to Project Decisions.**

Users upload Primavera P6 XER and Excel/CSV files into a project workspace. The platform validates and versions the data, calculates schedule metrics with deterministic engines, and exposes those calculations to an AI assistant through controlled tool calls. Answers must show supporting evidence and assumptions.

## 2. Problem statement

EPC project professionals commonly work with separate files and manual workflows for schedule updates, progress, cost reports, risks, and management reporting. Analysis requires repeated data cleaning, comparisons, calculations, and narrative writing. This makes it difficult to quickly answer questions such as:

- What changed since the previous schedule update?
- Which activities and relationships are driving milestone exposure?
- Where is schedule variance concentrated?
- Which activities need investigation first?
- What happens if a selected activity is delayed by a given number of days?
- What should be included in this week's project report?

The platform reduces the time between receiving project data and producing a traceable analysis.

## 3. Product goals

### MVP goals

1. Let an individual create a workspace and multiple projects.
2. Import supported Primavera P6 XER files and mapped XLSX/CSV files.
3. Preserve each successful import as an immutable project data version.
4. Show an import preview, validation errors, warnings, and data coverage.
5. Calculate core schedule metrics deterministically.
6. Compare two project versions and identify material changes.
7. Let users ask project-specific questions using AI tool calling.
8. Return answers with source references, calculation methods, and assumptions.
9. Produce a basic schedule analysis report in PDF and exportable tabular data.
10. Enforce project/workspace isolation and usage limits.

### Success measures for private beta

These are internal targets to validate, not public product claims.

| Metric | Beta target | Measurement |
|---|---:|---|
| Successful import | >=95% for supported, tested fixtures | successful imports / valid supported attempts |
| Deterministic calculations | 100% on reference test cases | expected vs actual outputs |
| AI answer evidence coverage | >=95% on curated evaluation set | answers with valid evidence / evaluated answers |
| Time to first analysis | <=5 minutes for normal test files | upload start to first dashboard result |
| Weekly active beta users | >=60% | active users / invited users |
| Free-to-paid conversion | 5–10% initial hypothesis | paid conversions / activated free users |

## 4. Non-goals for v1

- Replacing Primavera P6, Microsoft Project, ERP, or document control systems.
- Writing updates back to P6 or changing the user's source schedule.
- Full resource leveling, cost-loaded scheduling, or automated schedule optimization.
- Probabilistic Monte Carlo forecasting unless a separately tested engine is added.
- Training a proprietary predictive ML model without a suitable historical dataset.
- Enterprise SSO, advanced portfolio governance, complex approval matrices, or white-labeling.
- Native mobile applications.
- Full multi-company collaboration beyond basic workspace membership and ownership foundations.

## 5. Target users and jobs-to-be-done

### Persona A — Planning Engineer / Scheduler

**Job:** Validate schedule updates, examine critical/near-critical activities, compare schedule versions, and explain milestone movement.

**Pain:** Large schedules, repetitive checks, limited time to prepare explanations.

**Success:** Quickly identify changed activities, float changes, logic anomalies, and milestone risks with traceable evidence.

### Persona B — Project Control Engineer

**Job:** Combine schedule and progress evidence into a coherent project status and management narrative.

**Pain:** Data spread across Primavera and Excel reports; repeated manual reconciliation.

**Success:** One workspace for schedule data and supporting reports, with reliable variance analysis and report outputs.

### Persona C — Independent Project Control Consultant

**Job:** Analyze multiple client projects and create reports efficiently.

**Pain:** Different templates, time pressure, confidentiality concerns, and repeated setup.

**Success:** Separate project workspaces, repeatable analysis, version history, and exportable reports.

## 6. Product principles

1. **Numbers come from engines:** LLMs may interpret and explain results but must not invent schedule calculations.
2. **Evidence before narrative:** Each material claim must reference project version, entity, field, and calculation result.
3. **Versioned data:** Never overwrite an imported project version; create a new version and compare explicitly.
4. **Transparent uncertainty:** Distinguish source facts, calculated values, assumptions, and forecasts.
5. **Human control:** v1 is read-only against source project data. No write actions without explicit user confirmation in future versions.
6. **Graceful data quality:** Incomplete or inconsistent data should produce warnings and unavailable metrics, not fabricated values.
7. **Individual-first, SaaS-ready:** A simple solo-user experience backed by workspace-level tenant isolation.

## 7. MVP scope and priority

### P0 — Required for MVP

**Identity and workspace**
- Email/password or supported auth-provider login.
- User profile.
- Personal workspace created at signup.
- Create, rename, archive projects.
- Workspace membership foundation, initially owner-only UX.

**Data Hub**
- Upload XER, XLSX, and CSV.
- File type/size validation and checksum.
- Async import job status.
- Import preview and validation summary.
- Excel/CSV column mapping wizard for supported schedule/progress templates.
- Immutable data versions and source file lineage.

**Schedule Intelligence**
- Project and WBS hierarchy.
- Activities and relationships.
- Data date and schedule metadata when available.
- Basic counts, duration, status distribution, progress distribution.
- Baseline/current comparison where baseline data is available.
- Critical/near-critical/negative float classification, with method disclosed.
- Total float distribution.
- Activity detail with predecessor/successor references.
- Schedule quality checks (initial subset, not claim of complete DCMA compliance).
- Version comparison.

**AI Assistant**
- Project-scoped conversational interface.
- Intent routing to read-only analytics tools.
- Answers based on structured tool results.
- Evidence panel and source references.
- Clarification when project/version or required input is ambiguous.
- Conversation history per project.

**Predict and Act (bounded v1)**
- Transparent milestone forecast based on imported schedule forecast dates / deterministic logic where supported.
- Basic what-if delay scenario on selected activity, clearly marked as scenario output.
- Create action items from a finding (manual user confirmation).
- Generate schedule analysis report.

**Output and billing foundation**
- PDF schedule analysis report.
- CSV/XLSX activity export.
- Usage event tracking and configurable plan limits.

### P1 — After MVP validation

- Cost report mapping and cost records.
- Basic EVM with validated PV, EV, AC definitions.
- Progress S-curve.
- Procurement-to-activity mapping.
- Risk register ingestion and cross-file correlation.
- More complete DCMA 14-point checks.
- More advanced what-if scenarios and recovery options.
- DOCX reporting.
- Team collaboration and shared workspace roles.

### P2 — Future platform capabilities

- Multi-project portfolio intelligence.
- External API and webhook integration.
- ERP integration.
- P6 EPPM/Primavera Cloud integration subject to authorized API access.
- Advanced probabilistic forecasting using validated historical data.
- Configurable agent workflows and enterprise approval.
- White-label and PaaS offering.

## 8. Primary user journeys

### Journey 1 — First project import

1. User signs up.
2. Platform creates a personal workspace.
3. User creates a project and enters name, sector, currency (optional), and timezone.
4. User uploads an XER file.
5. Platform validates the extension, size, checksum, and file safety.
6. Import job parses the file in a background worker.
7. Platform displays imported object counts, data date, detected project(s), warnings, and errors.
8. User confirms import.
9. Platform creates project version 1.
10. Schedule engine calculates available KPIs.
11. User lands on project overview and can open the AI assistant.

### Journey 2 — Compare weekly updates

1. User uploads a later XER export into the same project.
2. Platform creates a new import job and preview.
3. User confirms the update is a new version of the same project.
4. Platform creates version 2 without deleting version 1.
5. Comparison engine matches activities using stable source identifiers where possible.
6. UI shows added, removed, changed, and unchanged activities.
7. User asks: "What changed and which changes matter for the finish milestone?"
8. AI calls comparison and milestone-impact tools and returns evidence-backed findings.

### Journey 3 — Ask a project question

1. User opens a project and selects a data version or "latest confirmed version".
2. User asks a natural-language question.
3. Intent router identifies required analysis.
4. AI selects approved read-only tools.
5. Backend validates scope and arguments, executes analytics, and stores tool logs.
6. AI explains tool results.
7. UI renders answer, evidence references, assumptions, and follow-up actions.

### Journey 4 — Generate a report

1. User selects project and version.
2. User selects Schedule Analysis Report.
3. Report service retrieves deterministic metrics and validated findings.
4. AI drafts narrative using only report payload and references.
5. User previews report.
6. User exports PDF.

## 9. Functional requirements

| ID | Requirement | Priority | Acceptance summary |
|---|---|---|---|
| FR-001 | User authentication | P0 | Unauthenticated users cannot access workspace/project data. |
| FR-002 | Personal workspace creation | P0 | New account receives one personal workspace. |
| FR-003 | Project CRUD | P0 | User can create, rename, archive and open owned projects. |
| FR-004 | Secure file upload | P0 | Supported files are stored privately and linked to a workspace/project. |
| FR-005 | Async import processing | P0 | Large parsing tasks run outside request/response lifecycle. |
| FR-006 | XER parsing | P0 | Supported fixtures parse into canonical project entities. |
| FR-007 | Excel/CSV mapping | P0 | User can map columns and save mapping profile. |
| FR-008 | Import validation | P0 | Import preview shows errors, warnings, counts and source metadata. |
| FR-009 | Version preservation | P0 | Every confirmed import creates an immutable data version. |
| FR-010 | Schedule calculations | P0 | Core metrics are deterministic and covered by tests. |
| FR-011 | Version comparison | P0 | Added, removed, and changed activities are identified. |
| FR-012 | AI project Q&A | P0 | Answers invoke approved tools when calculations/data are needed. |
| FR-013 | Evidence references | P0 | Material answer claims link to source entities/results. |
| FR-014 | Basic forecast/scenario | P0 | Output clearly marks source facts, assumptions, and scenario results. |
| FR-015 | Report generation | P0 | User can preview and export PDF/CSV/XLSX. |
| FR-016 | Usage tracking | P0 | Import, analytics, AI and report usage are recorded. |
| FR-017 | Cost/EVM analytics | P1 | Requires validated cost/progress data mapping. |
| FR-018 | Risk/procurement cross-analysis | P1 | Requires explicit entity mapping and provenance. |
| FR-019 | Team collaboration | P1 | Workspace roles and member management. |
| FR-020 | Public API | P2 | Tenant-scoped API keys and audit trail. |

## 10. Non-functional requirements

### Security and privacy
- Private object storage; no public file URLs by default.
- TLS in transit and encryption at rest provided by infrastructure.
- Tenant authorization on every backend query and storage operation.
- File validation by magic bytes/content, not extension alone.
- File size, row count, decompression, and parsing time limits.
- No project content in application logs unless explicitly redacted or approved for diagnostics.
- AI provider calls must use only the minimum data needed for the current question.
- Retention and deletion policy must be visible to the user.
- Secrets stored in deployment secret manager, never in client-side code.

### Reliability
- Import jobs must be idempotent by file checksum + project + import configuration.
- Failed jobs must preserve diagnostic details without creating a partial confirmed version.
- Reprocessing must not duplicate activities or relationships.
- Analytics runs must record engine version and input project version.

### Performance targets (initial)
- Dashboard API p95 under 2 seconds for precomputed summary on normal project sizes.
- Upload request returns a job identifier quickly; parsing runs asynchronously.
- AI response latency depends on model/provider; show progress and tool execution state.
- Initial file limits are configurable; begin beta with a conservative cap (e.g., 50 MB) and benchmark before raising it.

### Accessibility/usability
- Responsive web app, desktop-first for schedule tables and dense data.
- Keyboard-accessible forms and tables.
- Clear units, date formats, timezone, and data date.
- Empty states guide the user to upload a project file.

## 11. Data and calculation rules

- Store imported source values and normalized canonical values separately where transformation is needed.
- Preserve original source identifiers such as `task_id`, `proj_id`, `wbs_id`, and relationship identifiers when provided.
- Use UTC timestamps for system events; retain project data date and project timezone as project metadata.
- Do not treat planned progress, physical percent complete, duration percent complete, and units percent complete as interchangeable.
- Do not calculate SPI/CPI without validated PV/EV/AC inputs and stated basis.
- Classify critical activities using a documented rule configured per analysis (e.g., total float threshold); do not silently assume one universal rule.
- Forecast outputs must record method, parameters, input version, and caveats.

## 12. MVP release acceptance

MVP can be released to a limited paid beta when:

1. Authentication, workspace isolation, project creation, and private file access pass security tests.
2. Supported XER and Excel fixtures import reproducibly.
3. Import preview explains warnings and errors.
4. Project version history works and prior versions remain readable.
5. Schedule engine reference tests pass 100%.
6. Baseline/version comparison returns traceable differences.
7. AI tools cannot query another user's project.
8. AI answers show evidence or clearly state insufficient data.
9. Report exports reproduce the selected project/version and data date.
10. Usage and cost controls are enabled.

## 13. Product risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| XER format variation | Import failures | Fixture library from multiple valid P6 exports; parser versioning; explicit unsupported-format errors. |
| Different Excel templates | Bad mapping | Preview + mapping wizard + saved templates. |
| Missing baseline | Misleading variance | Flag unavailable comparisons; do not infer baseline. |
| Inconsistent progress basis | Invalid KPI | Store percent-complete type and basis; suppress unsupported metrics. |
| LLM hallucination | Wrong decision support | Deterministic tools, evidence contract, answer evaluator, refusal when evidence absent. |
| Sensitive project data | Customer trust/security | Tenant isolation, private storage, deletion, least-privilege, audit trail. |
| AI cost growth | Poor unit economics | Usage metering, caching, model routing, bounded tool outputs. |

## 14. Open decisions for beta validation

These can be decided after the technical proof of concept, not before starting:
- Exact max upload size and maximum activity count.
- Supported P6 release range based on fixture testing.
- Whether the first Excel mapping profile targets activity-level progress or a generic schedule template.
- Whether a project can contain multiple P6 projects in one XER import or must be split into separate platform projects.
- Initial paid plan quotas and AI cost ceiling.
- Supported report branding and language options.
