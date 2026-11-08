# UI/UX Specification — v1.0

## 1. Experience direction

**Visual direction:** premium professional SaaS for engineering/project controls. Clean, precise, data-dense but calm. Dark navy may be used for the main shell or AI workspace, with restrained blue/cyan accents and clear semantic status colors. Avoid generic robot imagery and excessive gradients.

**Primary design principle:** the user should always know which project and which data date/version they are viewing.

## 2. Global application shell

### Desktop layout

- Left navigation sidebar: 240–260 px, collapsible.
- Top bar: workspace selector, project selector/context, version/data date, notifications, profile.
- Main content: fluid, max readable width for reports; wide tables for schedule data.
- AI assistant: dedicated workspace page and optional contextual side panel.

### Global header context

Always show:
- Project name.
- Selected version label/number.
- Data date.
- Version status (latest, historical, staging if applicable).
- Source format/source file reference where relevant.

Never silently switch to a newer project version during a conversation.

## 3. Navigation structure

```text
Workspace
  Overview
  My Projects
  Data Hub

Selected Project
  Overview
  Schedule Intelligence
  Version Comparison
  AI Assistant
  Scenarios
  Reports

Workspace Settings
  Profile & Preferences
  Usage & Plan
  Security & Data
```

Cost Intelligence, Risk Intelligence, Procurement, and Portfolio Intelligence are future modules. They may appear as disabled roadmap placeholders only if this helps communicate product direction; do not create empty navigation clutter in the MVP.

## 4. Screen specifications

### Screen A — Signup / Login

Elements:
- Email and password or auth provider options.
- Forgot password.
- Terms/privacy links.
- Clear indication that project data is private to the user's workspace.

States:
- invalid credentials;
- email verification pending;
- session expired;
- account disabled.

### Screen B — Onboarding

Steps:
1. Welcome and role selection (Planner, Project Control, Consultant, Other).
2. Create first project (name, code optional, timezone, currency optional).
3. Upload first file or use a demo dataset.
4. Explain what the first import will extract.

Allow skipping profile questions. Do not force lengthy onboarding.

### Screen C — My Projects

Display:
- project name/code;
- status;
- latest version;
- data date;
- last analysis timestamp;
- last updated;
- quick action to open/upload.

Actions:
- create project;
- search/filter;
- archive project;
- open recent project.

Empty state: explain that the user should create a project and upload a P6 XER or supported Excel file.

### Screen D — Project Overview

Top KPI cards (only render available metrics):
- activities;
- activities complete/in progress/not started;
- current finish date (source or derived label);
- lowest total float / critical count using configured threshold;
- physical progress only when basis is known;
- last data date.

Charts:
- activity status distribution;
- total float bands;
- progress distribution;
- version history / milestone changes when multiple versions exist.

Below:
- high-priority findings;
- recent imports;
- recent reports;
- suggested questions.

Every card must show data version and calculation/source label on hover or detail view.

### Screen E — Data Hub

Components:
- drag/drop upload area;
- supported formats and file-size cap;
- file list with source format, size, checksum short ID, uploaded date, import status;
- import job details;
- mapping profile selector;
- preview panel with sample rows and normalized columns;
- validation errors/warnings separated by severity;
- confirmation button to create a new version.

Important UX:
- Clearly distinguish "Upload complete" from "Import complete" and "Version confirmed".
- Do not let a user confirm an import with blocking errors.
- Warn when the file appears to belong to a different project.

### Screen F — Schedule Intelligence

Tabs:
- Summary;
- Activities;
- Critical / Low Float;
- Logic & Relationships;
- Quality Checks.

Activity table columns (configurable):
- Activity ID;
- Activity Name;
- WBS;
- Status;
- Start;
- Finish;
- Remaining Duration;
- Total Float;
- Physical % Complete (when valid);
- Change vs previous version.

Filtering:
- activity ID/name search;
- WBS;
- status;
- float range;
- date range;
- progress range.

Activity detail drawer:
- source identifiers;
- current version values;
- predecessor/successor list;
- source field provenance;
- baseline/current values if available;
- related findings.

### Screen G — Version Comparison

- Version A and Version B selectors.
- Data date labels.
- Summary counts: added, removed, changed, unchanged, ambiguous.
- Change categories: dates, duration, float, status, progress, relationships.
- Filterable activity diff table.
- Milestone movement summary only when source/method supports it.
- Export comparison.

### Screen H — AI Assistant

Layout:
- Left: conversation list.
- Center: chat and response blocks.
- Right or expandable panel: selected project version, data sources, evidence, and tool activity.

Question starters:
- Summarize current schedule health.
- Which activities have the lowest float?
- What changed since the previous update?
- Which data is missing for a reliable analysis?
- What happens if an activity is delayed by 10 working days?

AI response block types:
- narrative;
- KPI strip;
- activity table;
- finding list;
- assumptions/limitations;
- evidence list;
- report/action CTA.

AI transparency:
- show "Analyzed version" and data date;
- show tools used in a collapsible "How this was analyzed" section;
- show method and threshold;
- allow clicking an activity evidence reference to open activity detail.

### Screen I — Scenario Lab

v1 supports a bounded activity-delay scenario.

Inputs:
- activity ID;
- delay amount;
- delay unit (working days/calendar days/hours);
- scenario name.

Output:
- baseline/source finish;
- scenario result where calculable;
- affected activities/milestones;
- assumptions;
- limitations;
- save scenario.

Do not present a scenario date when required calendar/network details are unsupported. Explain why the simulation is limited.

### Screen J — Reports

- report type;
- selected version;
- language;
- generation status;
- preview;
- PDF/Excel download;
- report history.

Reports should include project name, code, source data date, version, generated timestamp, methodology notes, and limitations.

### Screen K — Usage & Plan

- plan name;
- active projects count;
- AI query usage;
- import count/bytes;
- report/scenario usage;
- billing period;
- upgrade CTA.

## 5. Responsive behavior

- Desktop: full schedule tables, multi-column dashboards, AI evidence panel.
- Tablet: collapsible sidebar, horizontally scrollable tables, stacked KPI cards.
- Mobile: prioritize project status, upload status, and chat; advanced table editing is not a v1 requirement.

## 6. UI component inventory

- AppShell / Sidebar / Topbar
- WorkspaceSwitcher / ProjectSwitcher
- ProjectVersionBadge / DataDateLabel
- KPIStatCard
- FileDropzone / UploadProgress / ImportStatusBadge
- MappingWizard / DataPreviewTable
- ValidationSummary / WarningList
- ActivityDataTable / ActivityDetailDrawer
- WbsTree
- FloatDistributionChart
- VersionDiffTable
- ChatComposer / ChatMessage / ToolActivity / EvidencePanel
- ScenarioForm / ScenarioResult
- ReportPreview / ExportMenu
- UsageMeter / PlanCard

## 7. UX acceptance criteria

- User can identify project and version on every project page.
- User can see the difference between uploaded, parsed, previewed, confirmed, and failed states.
- Every chart shows its data version and unit.
- No KPI displays a misleading zero when data is unavailable; show "Not available" with explanation.
- Every AI numeric claim can open its evidence or explain why evidence is unavailable.
- User can distinguish a source value from a derived value and scenario result.
- Tables support sorting, filtering, and pagination without loading all activities at once.
