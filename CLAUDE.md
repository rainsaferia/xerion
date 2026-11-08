# Claude Code Project Instructions — Project Intelligence Platform

You are implementing **Project Intelligence Platform**, an individual-first multi-tenant SaaS workspace for EPC project professionals.

## 1. Read these files first

Before changing code, read:
1. `README.md`
2. `01_PRD.md`
3. `02_SYSTEM_ARCHITECTURE.md`
4. `03_DATA_MODEL.md`
5. `05_AI_AGENT_SPEC.md`
6. `06_API_SPEC.md`
7. `07_UI_UX_SPEC.md`
8. `08_DEVELOPMENT_BACKLOG.md`

Treat them as the current product baseline. If implementation reveals a contradiction or a missing design decision, stop and document the conflict before silently changing product scope.

## 2. Product constraints

- Build a modular monolith plus a separate background worker.
- Initial inputs: Primavera P6 XER, XLSX, CSV.
- First strong capability: Schedule Intelligence.
- Core product loop: Analyze → Predict → Act.
- Preserve immutable project versions.
- Every project query must be tenant-scoped.
- All schedule calculations must be deterministic and tested.
- LLM explains tool outputs; it does not invent calculations.
- The v1 app is read-only against the source Primavera schedule.
- Do not claim broad XER compatibility until verified fixtures pass.
- Do not claim ML prediction or statistical confidence without validated historical data.

## 3. Preferred implementation conventions

### Frontend
- Next.js App Router + TypeScript.
- Use server components where useful; use client components only for interactive UI.
- Typed API client; do not scatter raw fetch calls throughout components.
- Build reusable components for KPI cards, data tables, upload states, evidence panels, and report states.
- All data-heavy tables require server-side pagination/filtering.
- Clearly show project version and data date.

### Backend
- FastAPI with Pydantic request/response schemas.
- SQLAlchemy models and Alembic migrations.
- Domain services separated from API route handlers.
- Parser adapters isolated from canonical domain model.
- Background worker for parsing, analytics batches, and report generation.
- Use structured logging and correlation IDs.

### Data
- PostgreSQL is the system of record for normalized project data.
- Private object storage holds original uploads and generated reports.
- Every confirmed import creates a new immutable project version.
- Preserve source IDs/fields and provenance.
- Avoid nullable numeric fields being coerced to zero.
- Use explicit units and percent-complete basis.

### AI
- Implement an AI provider adapter.
- Use function/tool calling through the selected provider's current supported API.
- Keep all tool execution on the backend.
- Validate tool names, arguments, and project/version scope.
- Do not expose DB, filesystem, shell, arbitrary Python, or unrestricted SQL to the model.
- Persist tool execution metadata and evidence references.
- Return insufficient-data responses when evidence is missing.

## 4. Development workflow

Work in small, testable slices:

1. Inspect repository state and existing conventions.
2. Identify the next backlog ticket and its dependencies.
3. Propose a short implementation plan.
4. Implement only that ticket/slice.
5. Add unit/integration tests.
6. Run lint, type checks, tests, and migration checks.
7. Summarize files changed, commands run, test results, and open risks.
8. Do not start the next major epic without checking the current slice is accepted.

Never replace existing user code or files without inspection. Do not delete data, migrations, or project configuration just to make tests pass.

## 5. Required quality gates

- Tenant isolation test for every project/file/report/AI query path.
- Import tests for valid, malformed, unsupported, duplicate, and large fixtures.
- Parser regression fixtures must be sanitized and legally/contractually usable.
- Deterministic calculation reference tests.
- Version comparison tests including ambiguous activity matching.
- AI tool argument validation and cross-tenant negative tests.
- File upload signature, size, and private-storage tests.
- Report output must reference exact project version and data date.

## 6. XER parser caution

XER is a proprietary Primavera exchange format. Do not assume all versions or exported project variants are identical. Implement based on verified fixtures. Keep raw source identifiers and source field metadata. When an unsupported table/field is encountered, warn or reject safely; do not guess a mapping.

## 7. AI response rules

Every project-specific numerical answer should:
- state the selected project version and data date;
- call one or more backend analytics tools when required;
- cite source activity/WBS/evidence references;
- show units and method;
- separate source data, derived calculation, forecast, scenario, and recommendation;
- state limitations and missing inputs.

A low-float activity is not automatically a root cause. Do not make causal claims without network/logic evidence.

## 8. Security rules

- Never commit `.env` files, tokens, API keys, or real client project files.
- Do not log raw project file content or sensitive report payloads.
- Never trust workspace/project IDs supplied by the LLM or browser without authorization checks.
- Keep storage private and issue short-lived signed URLs.
- Do not return internal storage keys to the browser.

## 9. First task

Start with **Sprint 0 / PI-001** only:
- inspect current repository;
- propose monorepo layout;
- initialize frontend/backend, local Postgres and Redis, lint/test commands, health checks, and CI;
- do not implement schedule analytics or AI until the foundation and data model are reviewed.

If repository already contains code, adapt rather than overwrite.
