/**
 * Typed API client. All backend calls go through here (no scattered raw fetch in components).
 * Server-side only for now: API_BASE_URL is not exposed to the browser.
 */

export interface ProjectListItem {
  id: string;
  workspace_id: string;
  name: string;
  project_code: string | null;
  description: string | null;
  industry: string;
  client_name: string | null;
  contractor_name: string | null;
  currency_code: string | null;
  timezone: string;
  status: string;
  latest_version_id: string | null;
  created_at: string;
}

export interface CreateProjectPayload {
  name: string;
  project_code?: string;
  description?: string;
  industry?: string;
  client_name?: string;
  contractor_name?: string;
  currency_code?: string;
  timezone?: string;
}

export interface UploadSessionPayload {
  filename: string;
  file_size_bytes?: number;
  content_type?: string;
}

export interface UploadSessionResponse {
  file_id: string;
  project_id: string;
  upload_method: string;
  upload_url: string;
  expires_at: string;
  required_headers: Record<string, string>;
  max_size_bytes: number;
}

export interface LiveResponse {
  status: string;
  version: string;
}

export interface ReadyResponse {
  status: "ok" | "degraded";
  checks: Record<string, "ok" | "unavailable">;
}

export type ImportJobStatus =
  | "queued"
  | "processing"
  | "preview_ready"
  | "failed"
  | "confirmed";

export interface ImportError {
  code: string;
  message: string;
  actionable?: string;
}

export interface ImportWarning {
  code: string;
  message: string;
}

export interface PreviewSummary {
  activities: number;
  wbs_nodes: number;
  relationships: number;
  calendars: number;
}

export type DetectedMetadata = Record<string, unknown>;

export interface TabularInspection {
  format: string;
  sheet_names: string[];
  active_sheet: string;
  headers: string[];
  sample_rows: Record<string, unknown>[];
  total_rows: number;
}

export interface ColumnMapping {
  activity_code: string;
  activity_name: string;
  status?: string;
  planned_start?: string;
  planned_finish?: string;
  actual_start?: string;
  actual_finish?: string;
  remaining_duration_hours?: string;
  original_duration_hours?: string;
  total_float_hours?: string;
  percent_complete?: string;
  wbs_code?: string;
  sheet_name?: string;
}

export interface MappingProfileOut {
  id: string;
  workspace_id: string;
  name: string;
  dataset_type: string;
  mapping_config: Record<string, unknown>;
  mapping_version: number;
}

export interface ApplyMappingPayload {
  mapping?: ColumnMapping;
  mapping_profile_id?: string;
  save_profile_name?: string;
}

export interface ActivityStatusDistribution {
  not_started: number;
  in_progress: number;
  complete: number;
  suspended: number;
  unknown: number;
}

export interface ProjectOverviewMetrics {
  project_id: string;
  project_name: string;
  version_id: string;
  version_number: number;
  version_label: string;
  data_date: string | null;
  project_start_date: string | null;
  project_finish_date: string | null;
  source_filename: string | null;
  source_format: string | null;
  total_activities: number;
  status_distribution: ActivityStatusDistribution;
  milestones_count: number;
  critical_activities_count: number;
  near_critical_activities_count: number;
  min_total_float_hours: number | null;
  max_total_float_hours: number | null;
  avg_physical_pct_complete: number | null;
  calendars_count: number;
  wbs_nodes_count: number;
  relationships_count: number;
  warnings_count: number;
}

export interface ActivityListItem {
  id: string;
  source_activity_id: string;
  activity_code: string | null;
  activity_name: string;
  status: string;
  activity_type: string | null;
  wbs_node_id: string | null;
  wbs_code: string | null;
  wbs_name: string | null;
  calendar_id: string | null;
  calendar_name: string | null;
  start_date: string | null;
  finish_date: string | null;
  planned_start: string | null;
  planned_finish: string | null;
  actual_start: string | null;
  actual_finish: string | null;
  remaining_duration_hours: number | null;
  total_float_hours: number | null;
  physical_pct_complete: number | null;
}

export interface ActivityListResponse {
  items: ActivityListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface RelationshipItem {
  relationship_id: string;
  relationship_type: string;
  lag_hours: number;
  is_external: boolean;
  activity_id: string;
  activity_code: string | null;
  activity_name: string;
  status: string;
}

export interface ActivityRelationshipsResponse {
  activity_id: string;
  predecessors: RelationshipItem[];
  successors: RelationshipItem[];
}

export interface ActivityDetail extends ActivityListItem {
  source_status: string | null;
  original_duration_hours: number | null;
  actual_duration_hours: number | null;
  free_float_hours: number | null;
  duration_pct_complete: number | null;
  units_pct_complete: number | null;
  percent_complete_type: string | null;
  source_fields: Record<string, unknown>;
  baselines: Record<string, unknown>[];
}

export interface WBSNodeItem {
  id: string;
  source_wbs_id: string | null;
  wbs_code: string | null;
  wbs_name: string;
  parent_wbs_node_id: string | null;
  sort_order: number | null;
  activity_count: number;
}

export interface ActivityListParams {
  versionId?: string;
  q?: string;
  status?: string;
  wbsId?: string;
  floatMax?: number;
  limit?: number;
  offset?: number;
}

export type FloatBandName =
  | "negative"
  | "zero"
  | "near_critical"
  | "low_float"
  | "high_float"
  | "missing";

export interface FloatBandSummary {
  name: FloatBandName;
  label: string;
  min_hours: number | null;
  max_hours: number | null;
  count: number;
  percentage: number;
}

export interface FloatDistributionResponse {
  project_id: string;
  version_id: string;
  float_source: "imported_source" | "recalculated";
  method: string;
  critical_threshold_hours: number;
  near_critical_threshold_hours: number;
  hours_per_day: number;
  total_activities: number;
  activities_with_float: number;
  activities_missing_float: number;
  min_float_hours: number | null;
  max_float_hours: number | null;
  bands: FloatBandSummary[];
}

export interface FloatDistributionParams {
  versionId?: string;
  criticalThresholdHours?: number;
  nearCriticalThresholdHours?: number;
  hoursPerDay?: number;
}

export interface CriticalExposureItem {
  id: string;
  source_activity_id: string | null;
  activity_code: string | null;
  activity_name: string;
  status: string;
  total_float_hours: number | null;
  total_float_days: number | null;
  free_float_hours: number | null;
  free_float_days: number | null;
  start_date: string | null;
  finish_date: string | null;
  float_band: string;
  is_critical: boolean;
}

export interface CriticalExposureResponse {
  project_id: string;
  version_id: string;
  float_source: "imported_source" | "recalculated";
  method: string;
  critical_threshold_hours: number;
  near_critical_threshold_hours: number;
  hours_per_day: number;
  band: string | null;
  total_exposed: number;
  items: CriticalExposureItem[];
  limit: number;
  offset: number;
}

export interface CriticalExposureParams {
  versionId?: string;
  band?: string;
  criticalThresholdHours?: number;
  nearCriticalThresholdHours?: number;
  hoursPerDay?: number;
  limit?: number;
  offset?: number;
}

export type QualityFindingCategory = "data_quality" | "schedule_performance";
export type QualityFindingSeverity = "info" | "low" | "medium" | "high" | "critical";

export interface QualityFindingItem {
  id: string;
  check_code: string;
  category: QualityFindingCategory;
  title: string;
  severity: QualityFindingSeverity;
  method: string;
  limitation: string;
  entity_type: string;
  entity_id: string | null;
  entity_source_id: string | null;
  entity_code: string | null;
  message: string;
  evidence: Record<string, unknown>[];
}

export interface QualityCheckSummary {
  total_findings: number;
  data_quality_count: number;
  schedule_performance_count: number;
  by_severity: Record<string, number>;
  checks_run: string[];
}

export interface QualityCheckReport {
  project_id: string;
  version_id: string;
  run_id: string | null;
  data_date: string | null;
  summary: QualityCheckSummary;
  findings: QualityFindingItem[];
}

export interface RunQualityChecksPayload {
  version_id?: string;
  selected_checks?: string[];
  persist?: boolean;
}

// Version comparison types (PI-034)
export type DiffCategory =
  | "added"
  | "removed"
  | "changed"
  | "unchanged"
  | "ambiguous";

export type RelationshipChangeType = "added" | "removed" | "modified";

export interface FieldDiff {
  field_name: string;
  old_value: unknown;
  new_value: unknown;
  delta?: unknown;
}

export interface RelationshipDiff {
  direction: "predecessor" | "successor";
  relationship_type: string;
  other_activity_code: string | null;
  other_activity_name: string | null;
  change_type: RelationshipChangeType;
  old_lag_hours: number | null;
  new_lag_hours: number | null;
}

export interface ActivityDiffItem {
  diff_category: DiffCategory;
  activity_code: string | null;
  activity_name: string;
  source_activity_id: string | null;
  match_key: string;
  from_activity_id: string | null;
  to_activity_id: string | null;
  field_changes: FieldDiff[];
  relationship_changes: RelationshipDiff[];
  ambiguous_reason: string | null;
}

export interface ComparisonSummary {
  from_version_total: number;
  to_version_total: number;
  matched: number;
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
  ambiguous: number;
  change_categories: Record<string, number>;
}

export interface VersionComparisonReport {
  project_id: string;
  from_version_id: string;
  to_version_id: string;
  from_version_number: number | null;
  to_version_number: number | null;
  from_data_date: string | null;
  to_data_date: string | null;
  summary: ComparisonSummary;
  items: ActivityDiffItem[];
  total_items: number;
  limit: number;
  offset: number;
}

export interface CompareVersionsParams {
  from_version_id: string;
  to_version_id: string;
  category?: DiffCategory;
  fields?: string[];
  limit?: number;
  offset?: number;
}

// Milestone forecast types (PI-044)
export type ForecastMethod =
  | "imported_schedule_dates"
  | "deterministic_float_indicator";

export interface MilestoneForecastItem {
  activity_id: string;
  source_activity_id: string;
  activity_code: string | null;
  activity_name: string;
  wbs_code: string | null;
  wbs_name: string | null;
  activity_type: string | null;
  status: string;
  source_date: string | null;
  source_date_type: "actual_finish" | "finish_date" | "planned_finish" | "unavailable";
  projected_date: string | null;
  is_calculated_projection: boolean;
  variance_days: number | null;
  total_float_hours: number | null;
  total_float_days: number | null;
  critical_status: "critical" | "near_critical" | "non_critical" | "unknown";
  driving_notes: string | null;
  warnings: string[];
}

export interface MilestoneForecastSummary {
  total_milestones: number;
  completed_milestones: number;
  in_progress_milestones: number;
  not_started_milestones: number;
  critical_milestones: number;
  delayed_or_slipping_milestones: number;
}

export interface MilestoneForecastResponse {
  project_id: string;
  project_version_id: string;
  data_date: string | null;
  method: ForecastMethod;
  method_description: string;
  summary: MilestoneForecastSummary;
  items: MilestoneForecastItem[];
  limitations: string[];
  deterministic_disclaimer: string;
  confidence_level: string | null;
}

export interface MilestoneForecastParams {
  versionId?: string;
  method?: ForecastMethod;
  milestoneId?: string;
  hoursPerDay?: number;
}

// Delay Scenario types (PI-045)
export type DelayUnit = "working_days" | "calendar_days" | "hours";
export type ImpactType =
  | "primary_delay"
  | "direct_successor_push"
  | "float_consumption"
  | "critical_milestone_slip";

export interface DelayScenarioPayload {
  activity_source_id: string;
  delay_value: number;
  delay_unit?: DelayUnit;
  version_id?: string;
  scenario_name?: string;
  hours_per_day?: number;
  persist?: boolean;
}

export interface AffectedScheduleItem {
  activity_id: string;
  source_activity_id: string;
  activity_code: string | null;
  activity_name: string;
  wbs_code: string | null;
  wbs_name: string | null;
  is_milestone: boolean;
  is_target: boolean;
  impact_type: ImpactType;
  source_start_date: string | null;
  source_finish_date: string | null;
  scenario_start_date: string | null;
  scenario_finish_date: string | null;
  delay_working_days: number;
  delay_calendar_days: number;
  original_total_float_hours: number | null;
  scenario_remaining_total_float_hours: number | null;
  notes: string;
}

export interface DelayScenarioSummary {
  target_activity_id: string;
  target_activity_code: string | null;
  delay_applied_working_days: number;
  delay_applied_hours: number;
  delay_applied_calendar_days: number;
  free_float_absorbed_hours: number;
  total_float_absorbed_hours: number;
  critical_path_breached: boolean;
  net_project_delay_working_days: number;
  net_project_delay_calendar_days: number;
  total_affected_activities: number;
  total_affected_milestones: number;
}

export interface DelayScenarioResponse {
  scenario_id: string | null;
  scenario_name: string;
  project_id: string;
  project_version_id: string;
  status: "completed" | "insufficient_data";
  summary: DelayScenarioSummary;
  affected_items: AffectedScheduleItem[];
  assumptions: string[];
  limitations: string[];
  warnings: string[];
  source_unaltered: boolean;
}

// Reporting & Schedule Exports (PI-046)
export type ReportType = "schedule_analysis" | "variance_comparison" | "quality_audit";
export type ReportOutputFormat = "pdf" | "xlsx" | "csv" | "docx";
export type ReportStatus = "queued" | "generating" | "ready" | "failed";

export interface ReportPayload {
  version_id: string;
  report_type?: ReportType;
  format?: ReportOutputFormat;
  options?: Record<string, unknown>;
}

export interface ActivityExportPayload {
  version_id: string;
  format?: "csv" | "xlsx";
  status?: string;
  wbs_code?: string;
  search?: string;
  critical_only?: boolean;
}

export interface ReportResponse {
  id: string;
  project_id: string;
  project_version_id: string;
  report_type: string;
  title: string;
  output_format: string;
  status: ReportStatus | string;
  parameters: Record<string, unknown>;
  created_at: string;
  completed_at?: string | null;
  download_url?: string | null;
}

export interface ReportDownloadUrlResponse {
  download_url: string;
  expires_at: string;
}

// Plans & Usage (PI-050)
export interface PlanQuotasOut {
  max_projects: number;
  max_file_uploads_per_month: number;
  max_imports_per_month: number;
  max_ai_queries_per_month: number;
  max_scenarios_per_month: number;
  max_reports_per_month: number;
  max_upload_size_bytes: number;
}

export interface PlanInfo {
  code: string;
  name: string;
  description: string;
  monthly_price_usd: number;
  quotas: PlanQuotasOut;
  features: string[];
}

export interface UsageMetricSummary {
  metric_name: string;
  display_label: string;
  used: number;
  limit: number | null;
  remaining: number | null;
  unit: string;
  percent_used: number | null;
}

export interface UsageSummaryResponse {
  workspace_id: string;
  plan_code: string;
  plan_name: string;
  billing_period_start: string;
  billing_period_end: string;
  reset_date: string;
  metrics: UsageMetricSummary[];
}

export interface ImportJobOut {
  id: string;
  status: ImportJobStatus;
  progress_pct: number;
  detected_metadata: DetectedMetadata | null;
  preview_summary: PreviewSummary | null;
  warnings: ImportWarning[];
  errors: ImportError[];
  created_at: string;
  finished_at: string | null;
}

// AI Orchestrator types (PI-041, PI-042)
export type ValidationStatus = "verified" | "caveated" | "insufficient_data";

export interface EvidenceReference {
  evidence_id: string;
  project_version_id: string;
  entity_type: string;
  entity_platform_id?: string | null;
  source_identifier?: string | null;
  field_name: string;
  source_value?: unknown;
  normalized_value?: unknown;
  unit?: string | null;
  method: string;
  citation_label: string;
}

export interface ToolExecutionItem {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  status: string;
  duration_ms?: number | null;
  evidence_refs?: Record<string, unknown>[];
}

export interface MessageItem {
  id: string;
  role: string;
  content: string | null;
  tool_executions?: ToolExecutionItem[];
  created_at: string;
}

export interface ConversationResponse {
  id: string;
  project_id: string;
  title?: string | null;
  selected_project_version_id?: string | null;
  status: string;
  messages: MessageItem[];
  created_at: string;
  updated_at: string;
}

export interface CreateConversationPayload {
  title: string;
  version_id?: string;
}

export interface SendMessagePayload {
  message: string;
  version_id?: string;
}

export interface AgentTurnResponse {
  conversation_id: string;
  message: MessageItem;
  tool_executions: ToolExecutionItem[];
  provider: string;
  model: string;
  validation_status?: ValidationStatus;
  evidence_citations?: string[];
  warnings?: string[];
  tokens_used?: number | null;
  latency_ms?: number | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function apiBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.API_BASE_URL ??
    "http://127.0.0.1:8000"
  );
}

interface RequestOptions {
  token?: string;
  acceptStatuses?: number[];
  timeoutMs?: number;
}

function buildHeaders(options?: RequestOptions): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  const token = options?.token ?? process.env.NEXT_PUBLIC_DEV_TOKEN;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(res: Response, path: string, acceptStatuses: number[] = []): Promise<T> {
  if (!res.ok && !acceptStatuses.includes(res.status)) {
    let errorCode: string | undefined;
    let errorMessage = `Request to ${path} failed with status ${res.status}`;
    try {
      const errJson = (await res.json()) as { error?: { code?: string; message?: string } };
      if (errJson?.error?.message) {
        errorMessage = errJson.error.message;
        errorCode = errJson.error.code;
      }
    } catch {
      // response was not JSON
    }
    throw new ApiError(res.status, errorMessage, errorCode);
  }
  return (await res.json()) as T;
}

async function getJson<T>(path: string, options?: RequestOptions): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    method: "GET",
    headers: buildHeaders(options),
    cache: "no-store",
    signal: AbortSignal.timeout(options?.timeoutMs ?? 30000),
  });
  return handleResponse<T>(res, path, options?.acceptStatuses);
}

async function postJson<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  const headers = buildHeaders(options);
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(options?.timeoutMs ?? 30000),
  });
  return handleResponse<T>(res, path, options?.acceptStatuses);
}

async function delJson<T>(path: string, options?: RequestOptions): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    method: "DELETE",
    headers: buildHeaders(options),
    cache: "no-store",
    signal: AbortSignal.timeout(options?.timeoutMs ?? 30000),
  });
  return handleResponse<T>(res, path, options?.acceptStatuses);
}

export const api = {
  health: () => getJson<LiveResponse>("/health"),
  // 503 is a valid, informative readiness answer ("degraded"), not a transport error.
  ready: () => getJson<ReadyResponse>("/health/ready", { acceptStatuses: [503] }),

  // Projects & Workspaces
  listProjects: (token?: string) =>
    getJson<ProjectListItem[]>("/api/v1/projects", { token }),

  createProject: (payload: CreateProjectPayload, token?: string) =>
    postJson<ProjectListItem>("/api/v1/projects", payload, { token }),

  createUploadSession: (projectId: string, payload: UploadSessionPayload, token?: string) =>
    postJson<UploadSessionResponse>(`/api/v1/projects/${projectId}/uploads`, payload, { token }),

  completeUpload: (fileId: string, token?: string) =>
    postJson<{ id: string; status: string; import_job_id?: string }>(`/api/v1/uploads/${fileId}/complete`, undefined, { token }),

  uploadScheduleFile: async (
    projectId: string,
    file: File,
    token?: string
  ): Promise<{ fileId: string; importJobId: string }> => {
    // 1. Create upload session with backend
    const session = await api.createUploadSession(
      projectId,
      {
        filename: file.name,
        file_size_bytes: file.size,
        content_type: file.type || "application/octet-stream",
      },
      token
    );

    // 2. Upload file contents directly to backend
    const uploadUrl = session.upload_url.startsWith("http")
      ? session.upload_url
      : `${apiBaseUrl()}${session.upload_url.startsWith("/") ? "" : "/"}${session.upload_url}`;

    const headers: Record<string, string> = {
      ...(session.required_headers || {}),
    };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const uploadRes = await fetch(uploadUrl, {
      method: "PUT",
      headers,
      body: file,
    });

    if (!uploadRes.ok) {
      let msg = `Upload storage failed: HTTP ${uploadRes.status}`;
      try {
        const errJson = (await uploadRes.json()) as { error?: { message?: string } };
        if (errJson?.error?.message) {
          msg = errJson.error.message;
        }
      } catch {
        // non-JSON response
      }
      throw new Error(msg);
    }

    // 3. Complete upload to enqueue parser background job
    const completed = await api.completeUpload(session.file_id, token);
    return {
      fileId: session.file_id,
      importJobId: completed.import_job_id || session.file_id,
    };
  },

  // Import endpoints (PI-013, PI-014)
  getImportJob: (id: string, token?: string) =>
    getJson<ImportJobOut>(`/api/v1/imports/${id}`, { token }),

  getImportPreview: (id: string, token?: string) =>
    getJson<ImportJobOut>(`/api/v1/imports/${id}/preview`, { token }),

  confirmImport: (id: string, token?: string) =>
    postJson<ImportJobOut>(`/api/v1/imports/${id}/confirm`, undefined, { token }),

  retryImport: (id: string, token?: string) =>
    postJson<ImportJobOut>(`/api/v1/imports/${id}/retry`, undefined, { token }),

  // Mapping wizard endpoints (PI-022)
  inspectImportFile: (id: string, sheet?: string, token?: string) => {
    const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
    return getJson<TabularInspection>(`/api/v1/imports/${id}/inspect${query}`, { token });
  },

  applyImportMapping: (id: string, payload: ApplyMappingPayload, token?: string) =>
    postJson<ImportJobOut>(`/api/v1/imports/${id}/mapping`, payload, { token }),

  getWorkspaceMappings: (workspaceId: string, token?: string) =>
    getJson<MappingProfileOut[]>(`/api/v1/workspaces/${workspaceId}/mappings`, { token }),

  // Overview metrics endpoints (PI-030)
  getProjectOverview: (projectId: string, versionId?: string, token?: string) => {
    const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    return getJson<ProjectOverviewMetrics>(`/api/v1/projects/${projectId}/overview${query}`, { token });
  },

  // Activity and WBS explorer endpoints (PI-031)
  getActivities: (projectId: string, params?: ActivityListParams, token?: string) => {
    const qp = new URLSearchParams();
    if (params?.versionId) qp.set("version_id", params.versionId);
    if (params?.q) qp.set("q", params.q);
    if (params?.status) qp.set("status", params.status);
    if (params?.wbsId) qp.set("wbs_id", params.wbsId);
    if (params?.floatMax !== undefined) qp.set("float_max", String(params.floatMax));
    if (params?.limit !== undefined) qp.set("limit", String(params.limit));
    if (params?.offset !== undefined) qp.set("offset", String(params.offset));
    const qs = qp.toString() ? `?${qp.toString()}` : "";
    return getJson<ActivityListResponse>(`/api/v1/projects/${projectId}/activities${qs}`, { token });
  },

  getActivityDetail: (projectId: string, activityId: string, versionId?: string, token?: string) => {
    const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    return getJson<ActivityDetail>(`/api/v1/projects/${projectId}/activities/${activityId}${query}`, { token });
  },

  getActivityRelationships: (projectId: string, activityId: string, versionId?: string, token?: string) => {
    const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    return getJson<ActivityRelationshipsResponse>(
      `/api/v1/projects/${projectId}/activities/${activityId}/relationships${query}`,
      { token }
    );
  },

  getWBS: (projectId: string, versionId?: string, token?: string) => {
    const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    return getJson<WBSNodeItem[]>(`/api/v1/projects/${projectId}/wbs${query}`, { token });
  },

  // Float and critical exposure analytics (PI-032)
  getFloatDistribution: (projectId: string, params?: FloatDistributionParams, token?: string) => {
    const qp = new URLSearchParams();
    if (params?.versionId) qp.set("version_id", params.versionId);
    if (params?.criticalThresholdHours !== undefined)
      qp.set("critical_threshold_hours", String(params.criticalThresholdHours));
    if (params?.nearCriticalThresholdHours !== undefined)
      qp.set("near_critical_threshold_hours", String(params.nearCriticalThresholdHours));
    if (params?.hoursPerDay !== undefined) qp.set("hours_per_day", String(params.hoursPerDay));
    const qs = qp.toString() ? `?${qp.toString()}` : "";
    return getJson<FloatDistributionResponse>(
      `/api/v1/projects/${projectId}/schedule/float-distribution${qs}`,
      { token }
    );
  },

  getCriticalExposure: (projectId: string, params?: CriticalExposureParams, token?: string) => {
    const qp = new URLSearchParams();
    if (params?.versionId) qp.set("version_id", params.versionId);
    if (params?.band) qp.set("band", params.band);
    if (params?.criticalThresholdHours !== undefined)
      qp.set("critical_threshold_hours", String(params.criticalThresholdHours));
    if (params?.nearCriticalThresholdHours !== undefined)
      qp.set("near_critical_threshold_hours", String(params.nearCriticalThresholdHours));
    if (params?.hoursPerDay !== undefined) qp.set("hours_per_day", String(params.hoursPerDay));
    if (params?.limit !== undefined) qp.set("limit", String(params.limit));
    if (params?.offset !== undefined) qp.set("offset", String(params.offset));
    const qs = qp.toString() ? `?${qp.toString()}` : "";
    return getJson<CriticalExposureResponse>(
      `/api/v1/projects/${projectId}/schedule/critical-exposure${qs}`,
      { token }
    );
  },

  // Schedule quality audit endpoints (PI-033)
  runQualityChecks: (projectId: string, payload?: RunQualityChecksPayload, token?: string) =>
    postJson<QualityCheckReport>(
      `/api/v1/projects/${projectId}/schedule/quality-checks`,
      payload ?? {},
      { token }
    ),

  getQualityChecks: (projectId: string, versionId?: string, category?: string, token?: string) => {
    const qp = new URLSearchParams();
    if (versionId) qp.set("version_id", versionId);
    if (category) qp.set("category", category);
    const qs = qp.toString() ? `?${qp.toString()}` : "";
    return getJson<QualityCheckReport>(
      `/api/v1/projects/${projectId}/schedule/quality-checks${qs}`,
      { token }
    );
  },

  // Schedule version comparison engine (PI-034)
  compareVersions: (
    projectId: string,
    payload: {
      from_version_id: string;
      to_version_id: string;
      fields?: string[];
      category_filter?: DiffCategory;
      limit?: number;
      offset?: number;
    },
    token?: string
  ) =>
    postJson<VersionComparisonReport>(
      `/api/v1/projects/${projectId}/versions/compare`,
      payload,
      { token }
    ),

  getComparisonReport: (
    projectId: string,
    params: CompareVersionsParams,
    token?: string
  ) => {
    const qp = new URLSearchParams();
    qp.set("from_version_id", params.from_version_id);
    qp.set("to_version_id", params.to_version_id);
    if (params.category) qp.set("category", params.category);
    if (params.limit !== undefined) qp.set("limit", String(params.limit));
    if (params.offset !== undefined) qp.set("offset", String(params.offset));
    return getJson<VersionComparisonReport>(
      `/api/v1/projects/${projectId}/versions/compare?${qp.toString()}`,
      { token }
    );
  },

  exportComparisonCsvUrl: (
    projectId: string,
    fromVersionId: string,
    toVersionId: string,
    category?: DiffCategory
  ): string => {
    const qp = new URLSearchParams({
      from_version_id: fromVersionId,
      to_version_id: toVersionId,
    });
    if (category) qp.set("category", category);
    return `${apiBaseUrl()}/api/v1/projects/${projectId}/versions/compare/export?${qp.toString()}`;
  },

  // Milestone forecast analytics (PI-044)
  getMilestoneForecast: (
    projectId: string,
    params?: MilestoneForecastParams,
    token?: string
  ) => {
    const qp = new URLSearchParams();
    if (params?.versionId) qp.set("version_id", params.versionId);
    if (params?.method) qp.set("method", params.method);
    if (params?.milestoneId) qp.set("milestone_id", params.milestoneId);
    if (params?.hoursPerDay !== undefined) qp.set("hours_per_day", String(params.hoursPerDay));
    const qs = qp.toString() ? `?${qp.toString()}` : "";
    return getJson<MilestoneForecastResponse>(
      `/api/v1/projects/${projectId}/schedule/forecast${qs}`,
      { token }
    );
  },

  // Delay scenario simulation (PI-045)
  simulateDelayScenario: (
    projectId: string,
    payload: DelayScenarioPayload,
    token?: string
  ) =>
    postJson<DelayScenarioResponse>(
      `/api/v1/projects/${projectId}/schedule/scenarios/delay`,
      payload,
      { token }
    ),

  // AI Orchestrator & Conversation endpoints (PI-041)
  createConversation: (
    projectId: string,
    payload: CreateConversationPayload,
    token?: string
  ) =>
    postJson<ConversationResponse>(
      `/api/v1/projects/${projectId}/ai/conversations`,
      payload,
      { token }
    ),

  listConversations: (projectId: string, token?: string) =>
    getJson<ConversationResponse[]>(
      `/api/v1/projects/${projectId}/ai/conversations`,
      { token }
    ),

  getConversation: (
    projectId: string,
    conversationId: string,
    token?: string
  ) =>
    getJson<ConversationResponse>(
      `/api/v1/projects/${projectId}/ai/conversations/${conversationId}`,
      { token }
    ),

  sendMessage: (
    projectId: string,
    conversationId: string,
    payload: SendMessagePayload,
    token?: string,
    options?: { timeoutMs?: number }
  ) =>
    postJson<AgentTurnResponse>(
      `/api/v1/projects/${projectId}/ai/conversations/${conversationId}/messages`,
      payload,
      { token, timeoutMs: options?.timeoutMs ?? 300000 }
    ),

  // Schedule Reports (PI-046)
  generateScheduleReport: (
    projectId: string,
    payload: ReportPayload,
    token?: string
  ) =>
    postJson<ReportResponse>(
      `/api/v1/projects/${projectId}/reports`,
      payload,
      { token }
    ),

  getReport: (
    reportId: string,
    token?: string
  ) =>
    getJson<ReportResponse>(
      `/api/v1/reports/${reportId}`,
      { token }
    ),

  getReportDownloadUrl: (
    reportId: string,
    token?: string
  ) =>
    getJson<ReportDownloadUrlResponse>(
      `/api/v1/reports/${reportId}/download`,
      { token }
    ),

  // Activity Exports (PI-047)
  exportActivities: (
    projectId: string,
    payload: ActivityExportPayload,
    token?: string
  ) =>
    postJson<ReportResponse>(
      `/api/v1/projects/${projectId}/exports/activities`,
      payload,
      { token }
    ),

  // Plans & Usage (PI-050)
  getPlans: (token?: string) =>
    getJson<PlanInfo[]>("/api/v1/plans", { token }),

  getUsageSummary: (workspaceId?: string, token?: string) => {
    const qp = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return getJson<UsageSummaryResponse>(`/api/v1/usage/summary${qp}`, { token });
  },

  // Lifecycle Deletions (PI-051)
  deleteProject: (projectId: string, token?: string) =>
    delJson<{ status: string; project_id: string }>(
      `/api/v1/projects/${projectId}`,
      { token }
    ),

  deleteAccount: (token?: string) =>
    delJson<{ status: string; user_id: string }>("/api/v1/me", { token }),
};
