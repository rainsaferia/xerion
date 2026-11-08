-- Project Intelligence Platform — PostgreSQL starter schema v1.0
-- Apply through Alembic migrations in production; this file is the reference baseline.
-- Assumes application authentication is handled by the backend or an external auth provider.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT,
    preferred_locale TEXT NOT NULL DEFAULT 'en',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_users_email ON users (lower(email));

CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    workspace_type TEXT NOT NULL DEFAULT 'personal'
        CHECK (workspace_type IN ('personal', 'team', 'organization')),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    plan_code TEXT NOT NULL DEFAULT 'free',
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_workspaces_owner ON workspaces(owner_user_id);

CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'owner'
        CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('invited', 'active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX idx_workspace_members_user ON workspace_members(user_id);

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    project_code TEXT,
    description TEXT,
    industry TEXT NOT NULL DEFAULT 'EPC',
    client_name TEXT,
    contractor_name TEXT,
    currency_code CHAR(3),
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'on_hold', 'completed', 'archived')),
    latest_version_id UUID,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_projects_workspace ON projects(workspace_id, status);
CREATE INDEX idx_projects_created_by ON projects(created_by);

CREATE TABLE uploaded_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uploaded_by UUID REFERENCES users(id),
    original_filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    content_type TEXT,
    source_format TEXT NOT NULL CHECK (source_format IN ('xer', 'xlsx', 'csv', 'xml', 'other')),
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    sha256_checksum CHAR(64) NOT NULL,
    storage_status TEXT NOT NULL DEFAULT 'private'
        CHECK (storage_status IN ('private', 'quarantined', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (workspace_id, project_id, sha256_checksum)
);
CREATE INDEX idx_uploaded_files_project ON uploaded_files(project_id, created_at DESC);

CREATE TABLE import_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    dataset_type TEXT NOT NULL CHECK (dataset_type IN ('activity_progress', 'cost', 'risk', 'procurement', 'custom')),
    mapping_config JSONB NOT NULL,
    mapping_version INTEGER NOT NULL DEFAULT 1,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, name, mapping_version)
);

CREATE TABLE import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uploaded_file_id UUID NOT NULL REFERENCES uploaded_files(id),
    mapping_id UUID REFERENCES import_mappings(id),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'preview_ready', 'confirmed', 'failed', 'cancelled')),
    parser_name TEXT,
    parser_version TEXT,
    progress_pct NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    detected_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    preview_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    idempotency_key TEXT,
    requested_by UUID REFERENCES users(id),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workspace_id, idempotency_key)
);
CREATE INDEX idx_import_jobs_project ON import_jobs(project_id, created_at DESC);
CREATE INDEX idx_import_jobs_status ON import_jobs(status, created_at);

CREATE TABLE project_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    import_job_id UUID NOT NULL UNIQUE REFERENCES import_jobs(id),
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    version_label TEXT,
    source_project_id TEXT,
    source_project_code TEXT,
    source_project_name TEXT,
    source_format TEXT NOT NULL,
    source_format_version TEXT,
    parser_version TEXT,
    data_date DATE,
    project_start_date DATE,
    project_finish_date DATE,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('staging', 'ready', 'failed', 'superseded')),
    confirmed_by UUID REFERENCES users(id),
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, version_number)
);
CREATE INDEX idx_project_versions_project ON project_versions(project_id, version_number DESC);

ALTER TABLE projects
    ADD CONSTRAINT fk_projects_latest_version
    FOREIGN KEY (latest_version_id) REFERENCES project_versions(id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE wbs_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    source_wbs_id TEXT,
    wbs_code TEXT,
    wbs_name TEXT NOT NULL,
    parent_wbs_node_id UUID REFERENCES wbs_nodes(id) ON DELETE SET NULL,
    sort_order INTEGER,
    source_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(project_version_id, source_wbs_id)
);
CREATE INDEX idx_wbs_version_parent ON wbs_nodes(project_version_id, parent_wbs_node_id);

CREATE TABLE calendars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    source_calendar_id TEXT,
    calendar_name TEXT NOT NULL,
    calendar_type TEXT,
    timezone TEXT,
    calendar_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    fidelity_status TEXT NOT NULL DEFAULT 'metadata_only'
        CHECK (fidelity_status IN ('metadata_only', 'partially_parsed', 'fully_supported')),
    source_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(project_version_id, source_calendar_id)
);
CREATE INDEX idx_calendars_version ON calendars(project_version_id);

CREATE TABLE activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    source_activity_id TEXT NOT NULL,
    activity_code TEXT,
    activity_name TEXT NOT NULL,
    wbs_node_id UUID REFERENCES wbs_nodes(id) ON DELETE SET NULL,
    calendar_id UUID REFERENCES calendars(id) ON DELETE SET NULL,
    activity_type TEXT,
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('not_started', 'in_progress', 'complete', 'suspended', 'unknown')),
    source_status TEXT,
    planned_start DATE,
    planned_finish DATE,
    start_date DATE,
    finish_date DATE,
    actual_start DATE,
    actual_finish DATE,
    remaining_duration_hours NUMERIC(16,4),
    original_duration_hours NUMERIC(16,4),
    actual_duration_hours NUMERIC(16,4),
    total_float_hours NUMERIC(16,4),
    free_float_hours NUMERIC(16,4),
    physical_pct_complete NUMERIC(7,4),
    duration_pct_complete NUMERIC(7,4),
    units_pct_complete NUMERIC(7,4),
    percent_complete_type TEXT,
    source_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (physical_pct_complete IS NULL OR physical_pct_complete BETWEEN 0 AND 100),
    CHECK (duration_pct_complete IS NULL OR duration_pct_complete BETWEEN 0 AND 100),
    CHECK (units_pct_complete IS NULL OR units_pct_complete BETWEEN 0 AND 100),
    UNIQUE(project_version_id, source_activity_id)
);
CREATE INDEX idx_activities_version ON activities(project_version_id);
CREATE INDEX idx_activities_version_wbs ON activities(project_version_id, wbs_node_id);
CREATE INDEX idx_activities_version_code ON activities(project_version_id, activity_code);
CREATE INDEX idx_activities_version_float ON activities(project_version_id, total_float_hours);
CREATE INDEX idx_activities_version_dates ON activities(project_version_id, start_date, finish_date);

CREATE TABLE activity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    source_relationship_id TEXT,
    predecessor_activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    successor_activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    lag_hours NUMERIC(16,4) NOT NULL DEFAULT 0,
    is_external BOOLEAN NOT NULL DEFAULT FALSE,
    source_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (predecessor_activity_id <> successor_activity_id)
);
CREATE INDEX idx_relationships_version_pred ON activity_relationships(project_version_id, predecessor_activity_id);
CREATE INDEX idx_relationships_version_succ ON activity_relationships(project_version_id, successor_activity_id);

CREATE TABLE baseline_activity_values (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    baseline_source_id TEXT,
    source_activity_id TEXT NOT NULL,
    baseline_start DATE,
    baseline_finish DATE,
    baseline_duration_hours NUMERIC(16,4),
    baseline_pct_complete NUMERIC(7,4),
    baseline_label TEXT,
    source_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(project_version_id, baseline_source_id, source_activity_id)
);
CREATE INDEX idx_baseline_version_activity ON baseline_activity_values(project_version_id, source_activity_id);

CREATE TABLE analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL,
    engine_name TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    method TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    requested_by UUID REFERENCES users(id),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_analysis_runs_project_version ON analysis_runs(project_version_id, created_at DESC);

CREATE TABLE analysis_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    finding_code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    entity_type TEXT,
    entity_source_id TEXT,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_findings_version_severity ON analysis_findings(project_version_id, severity);

CREATE TABLE ai_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES users(id),
    title TEXT,
    selected_project_version_id UUID REFERENCES project_versions(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_conversations_project ON ai_conversations(project_id, updated_at DESC);

CREATE TABLE ai_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID REFERENCES project_versions(id),
    role TEXT NOT NULL CHECK (role IN ('system', 'developer', 'user', 'assistant', 'tool')),
    content TEXT,
    structured_content JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider TEXT,
    model TEXT,
    token_input INTEGER,
    token_output INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_messages_conversation ON ai_messages(conversation_id, created_at);

CREATE TABLE ai_tool_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES ai_messages(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID REFERENCES project_versions(id),
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('requested', 'completed', 'failed', 'rejected')),
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_tool_exec_message ON ai_tool_executions(message_id);

CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    title TEXT NOT NULL,
    output_format TEXT NOT NULL CHECK (output_format IN ('pdf', 'xlsx', 'csv', 'docx')),
    object_key TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'generating', 'ready', 'failed')),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_reports_project ON reports(project_id, created_at DESC);

CREATE TABLE usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('file_upload', 'file_import', 'analysis', 'ai_query', 'scenario', 'report_export')),
    quantity NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit TEXT NOT NULL DEFAULT 'count',
    estimated_cost_usd NUMERIC(18,6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_usage_workspace_time ON usage_events(workspace_id, created_at DESC);

-- Security implementation notes:
-- 1) Every repository method must filter by authenticated workspace membership.
-- 2) Add PostgreSQL RLS policies as defense in depth if application auth maps cleanly to DB sessions.
-- 3) Do not expose service-role credentials to the browser.
-- 4) Validate project_id/workspace_id consistency in service code and, where practical, composite FK constraints.
