import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { ApiError, api, type ImportJobOut } from "./api-client.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function stubFetch(status: number, body: unknown) {
  globalThis.fetch = async () =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;
}

describe("api client", () => {
  it("returns readiness on 200", async () => {
    stubFetch(200, { status: "ok", checks: { postgres: "ok", redis: "ok" } });
    const res = await api.ready();
    assert.equal(res.status, "ok");
  });

  it("treats 503 readiness as a degraded answer, not an error", async () => {
    stubFetch(503, { status: "degraded", checks: { postgres: "unavailable", redis: "ok" } });
    const res = await api.ready();
    assert.equal(res.status, "degraded");
  });

  it("throws ApiError on other failures", async () => {
    stubFetch(500, { error: { code: "SERVER_ERROR", message: "Internal error" } });
    await assert.rejects(
      async () => {
        await api.health();
      },
      (err: unknown) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 500);
        assert.equal(err.code, "SERVER_ERROR");
        return true;
      }
    );
  });

  it("fetches import job preview", async () => {
    const mockJob: ImportJobOut = {
      id: "job-123",
      status: "preview_ready",
      progress_pct: 100,
      detected_metadata: { project_code: "EPC-01" },
      preview_summary: { activities: 50, wbs_nodes: 5, relationships: 45, calendars: 1 },
      warnings: [],
      errors: [],
      created_at: "2026-11-05T00:00:00Z",
      finished_at: "2026-11-05T00:01:00Z",
    };
    stubFetch(200, mockJob);
    const res = await api.getImportPreview("job-123", "mock-token");
    assert.equal(res.id, "job-123");
    assert.equal(res.status, "preview_ready");
    assert.equal(res.preview_summary?.activities, 50);
  });

  it("confirms import job", async () => {
    const confirmedJob: ImportJobOut = {
      id: "job-123",
      status: "confirmed",
      progress_pct: 100,
      detected_metadata: null,
      preview_summary: null,
      warnings: [],
      errors: [],
      created_at: "2026-11-05T00:00:00Z",
      finished_at: "2026-11-05T00:02:00Z",
    };
    stubFetch(200, confirmedJob);
    const res = await api.confirmImport("job-123", "mock-token");
    assert.equal(res.status, "confirmed");
  });

  it("throws ApiError when confirming a job with blocking errors", async () => {
    stubFetch(400, {
      error: {
        code: "CANNOT_CONFIRM_IMPORT",
        message: "Cannot confirm an import job with blocking errors.",
      },
    });
    await assert.rejects(
      async () => {
        await api.confirmImport("job-123", "mock-token");
      },
      (err: unknown) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 400);
        assert.equal(err.code, "CANNOT_CONFIRM_IMPORT");
        return true;
      }
    );
  });

  it("inspects tabular import file", async () => {
    stubFetch(200, {
      format: "csv",
      sheet_names: ["Sheet1"],
      active_sheet: "Sheet1",
      headers: ["Task ID", "Task Name"],
      sample_rows: [{ "Task ID": "A10", "Task Name": "Civil Foundation" }],
      total_rows: 1,
    });
    const res = await api.inspectImportFile("job-csv", undefined, "mock-token");
    assert.equal(res.format, "csv");
    assert.equal(res.headers.length, 2);
    assert.equal(res.sample_rows[0]["Task ID"], "A10");
  });

  it("applies import mapping and returns preview ready job", async () => {
    stubFetch(200, {
      id: "job-csv",
      status: "preview_ready",
      progress_pct: 100,
      preview_summary: { activities: 10, wbs_nodes: 2, relationships: 0, calendars: 0 },
      warnings: [],
      errors: [],
    });
    const res = await api.applyImportMapping(
      "job-csv",
      { mapping: { activity_code: "Task ID", activity_name: "Task Name" } },
      "mock-token"
    );
    assert.equal(res.status, "preview_ready");
    assert.equal(res.preview_summary?.activities, 10);
  });

  it("fetches workspace mapping profiles", async () => {
    stubFetch(200, [
      {
        id: "profile-1",
        workspace_id: "ws-1",
        name: "Standard EPC CSV",
        dataset_type: "activity_progress",
        mapping_config: { activity_code: "Code", activity_name: "Name" },
        mapping_version: 1,
      },
    ]);
    const res = await api.getWorkspaceMappings("ws-1", "mock-token");
    assert.equal(res.length, 1);
    assert.equal(res[0].name, "Standard EPC CSV");
  });

  it("fetches project overview metrics with unavailable fields as null", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      project_name: "Gas Processing Facility",
      version_id: "ver-1",
      version_number: 1,
      version_label: "V1",
      data_date: "2026-11-01",
      project_start_date: "2026-01-15",
      project_finish_date: "2026-12-31",
      source_filename: "schedule.xer",
      source_format: "xer",
      total_activities: 120,
      status_distribution: {
        not_started: 70,
        in_progress: 30,
        complete: 20,
        suspended: 0,
        unknown: 0,
      },
      milestones_count: 5,
      critical_activities_count: 12,
      near_critical_activities_count: 8,
      min_total_float_hours: -24.0,
      max_total_float_hours: 120.0,
      avg_physical_pct_complete: null, // unavailable basis preserved as null
      calendars_count: 2,
      wbs_nodes_count: 14,
      relationships_count: 180,
      warnings_count: 3,
    });

    const res = await api.getProjectOverview("proj-1", "ver-1", "mock-token");
    assert.equal(res.project_id, "proj-1");
    assert.equal(res.total_activities, 120);
    assert.equal(res.status_distribution.complete, 20);
    assert.equal(res.min_total_float_hours, -24.0);
    assert.equal(res.avg_physical_pct_complete, null);
  });

  it("queries activities with search, filter, and pagination parameters", async () => {
    stubFetch(200, {
      items: [
        {
          id: "act-1",
          source_activity_id: "SRC-1",
          activity_code: "ENG-100",
          activity_name: "Design Drawings",
          status: "complete",
          activity_type: null,
          wbs_node_id: "wbs-1",
          wbs_code: "GPF.ENG",
          wbs_name: "Engineering",
          calendar_id: null,
          calendar_name: null,
          start_date: "2026-01-15",
          finish_date: "2026-02-15",
          planned_start: null,
          planned_finish: null,
          actual_start: null,
          actual_finish: null,
          remaining_duration_hours: 0,
          total_float_hours: 0,
          physical_pct_complete: 100,
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });

    const res = await api.getActivities(
      "proj-1",
      { q: "Design", status: "complete", limit: 10, offset: 0 },
      "mock-token"
    );
    assert.equal(res.total, 1);
    assert.equal(res.items[0].activity_code, "ENG-100");
  });

  it("fetches activity detail with raw provenance and baselines", async () => {
    stubFetch(200, {
      id: "act-1",
      source_activity_id: "SRC-1",
      activity_code: "ENG-100",
      activity_name: "Design Drawings",
      status: "complete",
      source_fields: { p6_task_id: 1001, raw_status: "TK_Done" },
      baselines: [{ baseline_label: "Baseline 1", baseline_duration_hours: 160 }],
    });

    const res = await api.getActivityDetail("proj-1", "act-1", undefined, "mock-token");
    assert.equal(res.id, "act-1");
    assert.equal(res.source_fields.p6_task_id, 1001);
    assert.equal(res.baselines.length, 1);
  });

  it("fetches activity relationships within version", async () => {
    stubFetch(200, {
      activity_id: "act-2",
      predecessors: [
        {
          relationship_id: "rel-1",
          relationship_type: "FS",
          lag_hours: 0,
          is_external: false,
          activity_id: "act-1",
          activity_code: "ENG-100",
          activity_name: "Design",
          status: "complete",
        },
      ],
      successors: [],
    });

    const res = await api.getActivityRelationships("proj-1", "act-2", undefined, "mock-token");
    assert.equal(res.activity_id, "act-2");
    assert.equal(res.predecessors.length, 1);
    assert.equal(res.predecessors[0].activity_code, "ENG-100");
  });

  it("fetches WBS tree with activity counts", async () => {
    stubFetch(200, [
      {
        id: "wbs-1",
        source_wbs_id: "W1",
        wbs_code: "GPF",
        wbs_name: "Facility Root",
        parent_wbs_node_id: null,
        sort_order: 1,
        activity_count: 5,
      },
    ]);

    const res = await api.getWBS("proj-1", undefined, "mock-token");
    assert.equal(res.length, 1);
    assert.equal(res[0].activity_count, 5);
  });

  it("fetches float distribution with bands and labels imported source float", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      version_id: "ver-1",
      float_source: "imported_source",
      method: "source_total_float_threshold",
      critical_threshold_hours: 0.0,
      near_critical_threshold_hours: 80.0,
      hours_per_day: 8.0,
      total_activities: 100,
      activities_with_float: 95,
      activities_missing_float: 5,
      min_float_hours: -24.0,
      max_float_hours: 240.0,
      bands: [
        {
          name: "negative",
          label: "Negative (< 0h)",
          min_hours: null,
          max_hours: 0.0,
          count: 4,
          percentage: 4.0,
        },
        {
          name: "zero",
          label: "Zero Float (0h)",
          min_hours: 0.0,
          max_hours: 0.0,
          count: 8,
          percentage: 8.0,
        },
        {
          name: "near_critical",
          label: "Near-Critical (0h - 80h)",
          min_hours: 0.0,
          max_hours: 80.0,
          count: 12,
          percentage: 12.0,
        },
        {
          name: "missing",
          label: "Missing / Unavailable",
          min_hours: null,
          max_hours: null,
          count: 5,
          percentage: 5.0,
        },
      ],
    });

    const res = await api.getFloatDistribution(
      "proj-1",
      {
        versionId: "ver-1",
        criticalThresholdHours: 0.0,
        nearCriticalThresholdHours: 80.0,
        hoursPerDay: 8.0,
      },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-1");
    assert.equal(res.float_source, "imported_source");
    assert.equal(res.total_activities, 100);
    assert.equal(res.activities_missing_float, 5);
    assert.equal(res.bands.length, 4);
    assert.equal(res.bands[0].name, "negative");
    assert.equal(res.bands[0].count, 4);
  });

  it("fetches critical exposure activities with unit conversions", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      version_id: "ver-1",
      float_source: "imported_source",
      method: "source_total_float_threshold",
      critical_threshold_hours: 0.0,
      near_critical_threshold_hours: 80.0,
      hours_per_day: 8.0,
      band: "all_exposed",
      total_exposed: 2,
      items: [
        {
          id: "act-neg",
          source_activity_id: "ACT-01",
          activity_code: "P-101",
          activity_name: "Pipe Rack Erection",
          status: "in_progress",
          total_float_hours: -16.0,
          total_float_days: -2.0,
          free_float_hours: 0.0,
          free_float_days: 0.0,
          start_date: "2026-04-01",
          finish_date: "2026-04-20",
          float_band: "negative",
          is_critical: true,
        },
        {
          id: "act-near",
          source_activity_id: "ACT-02",
          activity_code: "E-201",
          activity_name: "Transformer Installation",
          status: "not_started",
          total_float_hours: 40.0,
          total_float_days: 5.0,
          free_float_hours: 8.0,
          free_float_days: 1.0,
          start_date: "2026-05-01",
          finish_date: "2026-05-15",
          float_band: "near_critical",
          is_critical: false,
        },
      ],
      limit: 50,
      offset: 0,
    });

    const res = await api.getCriticalExposure(
      "proj-1",
      {
        versionId: "ver-1",
        band: "all_exposed",
        hoursPerDay: 8.0,
      },
      "mock-token"
    );

    assert.equal(res.total_exposed, 2);
    assert.equal(res.items.length, 2);
    assert.equal(res.items[0].activity_code, "P-101");
    assert.equal(res.items[0].total_float_hours, -16.0);
    assert.equal(res.items[0].total_float_days, -2.0);
    assert.equal(res.items[0].is_critical, true);
    assert.equal(res.items[1].total_float_days, 5.0);
    assert.equal(res.items[1].is_critical, false);
  });

  it("triggers schedule quality checks and receives categorized report", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      version_id: "ver-1",
      run_id: "run-01",
      data_date: "2026-06-01",
      summary: {
        total_findings: 3,
        data_quality_count: 2,
        schedule_performance_count: 1,
        by_severity: { critical: 1, high: 1, medium: 1, low: 0, info: 0 },
        checks_run: [
          "missing_activity_identifier",
          "orphan_relationships",
          "negative_float",
        ],
      },
      findings: [
        {
          id: "find-1",
          check_code: "orphan_relationships",
          category: "data_quality",
          title: "Orphan Relationship Link",
          severity: "critical",
          method: "relationship_endpoint_id_referential_integrity",
          limitation: "Checks endpoints within version",
          entity_type: "relationship",
          entity_id: "rel-1",
          entity_source_id: "R-100",
          entity_code: null,
          message: "Predecessor activity does not exist in version.",
          evidence: [{ field: "relationship_id", value: "rel-1" }],
        },
        {
          id: "find-2",
          check_code: "negative_float",
          category: "schedule_performance",
          title: "Negative Total Float (-16h)",
          severity: "critical",
          method: "imported_source_total_float_negative_threshold",
          limitation: "Evaluates imported total float",
          entity_type: "activity",
          entity_id: "act-1",
          entity_source_id: "ACT-01",
          entity_code: "P-101",
          message: "Activity has negative float of -16h.",
          evidence: [{ field: "total_float_hours", value: -16.0 }],
        },
      ],
    });

    const res = await api.runQualityChecks(
      "proj-1",
      { version_id: "ver-1", persist: true },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-1");
    assert.equal(res.run_id, "run-01");
    assert.equal(res.summary.total_findings, 3);
    assert.equal(res.summary.data_quality_count, 2);
    assert.equal(res.summary.schedule_performance_count, 1);
    assert.equal(res.findings.length, 2);
    assert.equal(res.findings[0].category, "data_quality");
    assert.equal(res.findings[1].category, "schedule_performance");
  });

  it("fetches schedule quality checks filtered by category", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      version_id: "ver-1",
      run_id: null,
      data_date: "2026-06-01",
      summary: {
        total_findings: 1,
        data_quality_count: 1,
        schedule_performance_count: 0,
        by_severity: { critical: 0, high: 1, medium: 0, low: 0, info: 0 },
        checks_run: ["invalid_date_range"],
      },
      findings: [
        {
          id: "find-3",
          check_code: "invalid_date_range",
          category: "data_quality",
          title: "Inverted Date Range",
          severity: "high",
          method: "chronological_date_order_verification",
          limitation: "Compares date boundaries",
          entity_type: "activity",
          entity_id: "act-inv",
          entity_source_id: "INV-1",
          entity_code: "INV-1",
          message: "Finish date is before start date.",
          evidence: [],
        },
      ],
    });

    const res = await api.getQualityChecks("proj-1", "ver-1", "data_quality", "mock-token");
    assert.equal(res.project_id, "proj-1");
    assert.equal(res.findings.length, 1);
    assert.equal(res.findings[0].category, "data_quality");
  });

  it("compares versions via POST and verifies reconciliation summary and diffs", async () => {
    stubFetch(200, {
      project_id: "proj-100",
      from_version_id: "ver-1",
      to_version_id: "ver-2",
      from_version_number: 1,
      to_version_number: 2,
      from_data_date: "2026-01-01",
      to_data_date: "2026-02-01",
      summary: {
        from_version_total: 10,
        to_version_total: 11,
        matched: 8,
        added: 3,
        removed: 2,
        changed: 5,
        unchanged: 3,
        ambiguous: 0,
        change_categories: { added: 3, removed: 2, changed: 5, unchanged: 3, ambiguous: 0 },
      },
      items: [
        {
          diff_category: "changed",
          activity_code: "ACT-01",
          activity_name: "Piping Works",
          match_key: "source_id:SRC-01",
          from_activity_id: "act-1a",
          to_activity_id: "act-1b",
          field_changes: [
            {
              field_name: "total_float_hours",
              old_value: 16.0,
              new_value: 0.0,
              delta: -16.0,
            },
          ],
          relationship_changes: [],
          ambiguous_reason: null,
        },
      ],
      total_items: 1,
      limit: 100,
      offset: 0,
    });

    const res = await api.compareVersions(
      "proj-100",
      {
        from_version_id: "ver-1",
        to_version_id: "ver-2",
      },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-100");
    assert.equal(res.summary.matched, 8);
    assert.equal(res.summary.from_version_total, 10);
    assert.equal(res.summary.to_version_total, 11);
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].activity_code, "ACT-01");
    assert.equal(res.items[0].field_changes[0].delta, -16.0);
  });

  it("fetches comparison report via GET and builds CSV export URL", async () => {
    stubFetch(200, {
      project_id: "proj-100",
      from_version_id: "ver-1",
      to_version_id: "ver-2",
      from_version_number: 1,
      to_version_number: 2,
      from_data_date: "2026-01-01",
      to_data_date: "2026-02-01",
      summary: {
        from_version_total: 5,
        to_version_total: 5,
        matched: 5,
        added: 0,
        removed: 0,
        changed: 1,
        unchanged: 4,
        ambiguous: 0,
        change_categories: { added: 0, removed: 0, changed: 1, unchanged: 4, ambiguous: 0 },
      },
      items: [],
      total_items: 0,
      limit: 50,
      offset: 0,
    });

    const res = await api.getComparisonReport(
      "proj-100",
      {
        from_version_id: "ver-1",
        to_version_id: "ver-2",
        category: "changed",
      },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-100");
    assert.equal(res.summary.changed, 1);

    const exportUrl = api.exportComparisonCsvUrl("proj-100", "ver-1", "ver-2", "changed");
    assert(exportUrl.includes("/api/v1/projects/proj-100/versions/compare/export"));
    assert(exportUrl.includes("from_version_id=ver-1"));
    assert(exportUrl.includes("to_version_id=ver-2"));
    assert(exportUrl.includes("category=changed"));
  });

  it("handles AI conversation creation, listing, getting, and message turn", async () => {
    // 1. Create conversation
    stubFetch(201, {
      id: "conv-1",
      project_id: "proj-100",
      title: "Schedule Risk Analysis",
      selected_project_version_id: "ver-1",
      status: "active",
      messages: [],
      created_at: "2026-11-06T00:00:00Z",
      updated_at: "2026-11-06T00:00:00Z",
    });
    const created = await api.createConversation(
      "proj-100",
      { title: "Schedule Risk Analysis", version_id: "ver-1" },
      "mock-token"
    );
    assert.equal(created.id, "conv-1");
    assert.equal(created.title, "Schedule Risk Analysis");

    // 2. List conversations
    stubFetch(200, [created]);
    const list = await api.listConversations("proj-100", "mock-token");
    assert.equal(list.length, 1);
    assert.equal(list[0].id, "conv-1");

    // 3. Get single conversation
    stubFetch(200, created);
    const fetched = await api.getConversation("proj-100", "conv-1", "mock-token");
    assert.equal(fetched.id, "conv-1");

    // 4. Send message (agent turn)
    stubFetch(200, {
      conversation_id: "conv-1",
      message: {
        id: "msg-2",
        role: "assistant",
        content: "There are 2 critical activities on the critical path.",
        created_at: "2026-11-06T00:00:05Z",
      },
      tool_executions: [
        {
          id: "exec-1",
          tool_name: "get_critical_activities",
          status: "completed",
          arguments: { band: "critical" },
          output_summary: { count: 2 },
          duration_ms: 12,
          evidence_refs: [
            {
              evidence_id: "ev_1234",
              entity_type: "activity",
              source_identifier: "A1010",
              citation_label: "[EV: A1010 float=0.0h]",
            },
          ],
        },
      ],
      provider: "mock",
      model: "gpt-4o",
      validation_status: "verified",
      evidence_citations: ["[EV: A1010 float=0.0h]"],
      warnings: [],
      tokens_used: 150,
      latency_ms: 320,
    });
    const turn = await api.sendMessage(
      "proj-100",
      "conv-1",
      { message: "Which activities are critical?" },
      "mock-token"
    );
    assert.equal(turn.conversation_id, "conv-1");
    assert.equal(turn.message.role, "assistant");
    assert(turn.message.content?.includes("2 critical activities"));
    assert.equal(turn.tool_executions.length, 1);
    assert.equal(turn.tool_executions[0].tool_name, "get_critical_activities");
    assert.equal(turn.tool_executions[0].evidence_refs?.length, 1);
    assert.equal(turn.validation_status, "verified");
    assert.equal(turn.evidence_citations?.length, 1);
  });

  it("fetches milestone forecast with explicit method and transparent limitations (PI-044)", async () => {
    stubFetch(200, {
      project_id: "proj-1",
      project_version_id: "ver-1",
      data_date: "2026-06-01",
      method: "deterministic_float_indicator",
      method_description: "Deterministic slippage projection based on imported CPM total float.",
      summary: {
        total_milestones: 2,
        completed_milestones: 1,
        in_progress_milestones: 1,
        not_started_milestones: 0,
        critical_milestones: 1,
        delayed_or_slipping_milestones: 1,
      },
      items: [
        {
          activity_id: "act-ms-1",
          source_activity_id: "MS-FOUNDATION",
          activity_code: "M-FOUND",
          activity_name: "Turbine Foundation",
          wbs_code: "1.1",
          wbs_name: "Civil Works",
          activity_type: "finish_milestone",
          status: "in_progress",
          source_date: "2026-07-10",
          source_date_type: "finish_date",
          projected_date: "2026-07-17",
          is_calculated_projection: true,
          variance_days: 5.0,
          total_float_hours: -40.0,
          total_float_days: -5.0,
          critical_status: "critical",
          driving_notes: "Negative float projects completion slip.",
          warnings: [],
        },
      ],
      limitations: [
        "Calendar exceptions and shift patterns were not re-simulated.",
      ],
      deterministic_disclaimer: "Deterministic schedule projection only. No probabilistic Monte Carlo simulation implied.",
      confidence_level: null,
    });

    const res = await api.getMilestoneForecast(
      "proj-1",
      {
        versionId: "ver-1",
        method: "deterministic_float_indicator",
        milestoneId: "MS-FOUNDATION",
      },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-1");
    assert.equal(res.method, "deterministic_float_indicator");
    assert.equal(res.confidence_level, null);
    assert.equal(res.summary.total_milestones, 2);
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].is_calculated_projection, true);
    assert.equal(res.items[0].source_date, "2026-07-10");
    assert.equal(res.items[0].projected_date, "2026-07-17");
    assert.equal(res.items[0].variance_days, 5.0);
    assert(res.limitations.length >= 1);
  });

  it("simulates activity delay scenario with zero mutation and network impact (PI-045)", async () => {
    stubFetch(200, {
      scenario_id: "scen-uuid-01",
      scenario_name: "Turbine generator delay +5d",
      project_id: "proj-1",
      project_version_id: "ver-1",
      status: "completed",
      summary: {
        target_activity_id: "act-1",
        target_activity_code: "A-TURBINE",
        delay_applied_working_days: 5.0,
        delay_applied_hours: 40.0,
        delay_applied_calendar_days: 7,
        free_float_absorbed_hours: 0.0,
        total_float_absorbed_hours: 16.0,
        critical_path_breached: true,
        net_project_delay_working_days: 3.0,
        net_project_delay_calendar_days: 5,
        total_affected_activities: 2,
        total_affected_milestones: 1,
      },
      affected_items: [
        {
          activity_id: "act-1",
          source_activity_id: "ACT-01",
          activity_code: "A-TURBINE",
          activity_name: "Turbine Installation",
          wbs_code: "1.1",
          wbs_name: "Power Island",
          is_milestone: false,
          is_target: true,
          impact_type: "primary_delay",
          source_start_date: "2026-06-01",
          source_finish_date: "2026-07-01",
          scenario_start_date: "2026-06-01",
          scenario_finish_date: "2026-07-08",
          delay_working_days: 5.0,
          delay_calendar_days: 7,
          original_total_float_hours: 16.0,
          scenario_remaining_total_float_hours: -24.0,
          notes: "Primary delay exceeds total float.",
        },
      ],
      assumptions: ["Working schedule assumes 8.0 hr/day."],
      limitations: ["Bounded v1 engine."],
      warnings: [],
      source_unaltered: true,
    });

    const res = await api.simulateDelayScenario(
      "proj-1",
      {
        activity_source_id: "A-TURBINE",
        delay_value: 5.0,
        delay_unit: "working_days",
        scenario_name: "Turbine generator delay +5d",
      },
      "mock-token"
    );

    assert.equal(res.project_id, "proj-1");
    assert.equal(res.status, "completed");
    assert.equal(res.source_unaltered, true);
    assert.equal(res.summary.delay_applied_working_days, 5.0);
    assert.equal(res.summary.critical_path_breached, true);
    assert.equal(res.summary.net_project_delay_working_days, 3.0);
    assert.equal(res.affected_items.length, 1);
    assert.equal(res.affected_items[0].is_target, true);
    assert.equal(res.affected_items[0].scenario_finish_date, "2026-07-08");
  });

  it("generates schedule report (PI-046)", async () => {
    stubFetch(200, {
      id: "report-123",
      project_id: "proj-1",
      project_version_id: "ver-1",
      report_type: "schedule_analysis",
      title: "Schedule Analysis Report",
      output_format: "pdf",
      status: "ready",
      parameters: { version_id: "ver-1" },
      created_at: "2026-11-08T12:00:00Z",
      completed_at: "2026-11-08T12:00:05Z",
      download_url: "/api/v1/reports/report-123/download",
    });

    const res = await api.generateScheduleReport(
      "proj-1",
      {
        version_id: "ver-1",
        report_type: "schedule_analysis",
        format: "pdf",
      },
      "mock-token"
    );

    assert.equal(res.id, "report-123");
    assert.equal(res.project_id, "proj-1");
    assert.equal(res.status, "ready");
    assert.equal(res.output_format, "pdf");
    assert.equal(res.download_url, "/api/v1/reports/report-123/download");
  });

  it("fetches report metadata (PI-046)", async () => {
    stubFetch(200, {
      id: "report-123",
      project_id: "proj-1",
      project_version_id: "ver-1",
      report_type: "schedule_analysis",
      title: "Schedule Analysis Report",
      output_format: "pdf",
      status: "ready",
      parameters: {},
      created_at: "2026-11-08T12:00:00Z",
      download_url: "/api/v1/reports/report-123/download",
    });

    const res = await api.getReport("report-123", "mock-token");
    assert.equal(res.id, "report-123");
    assert.equal(res.status, "ready");
  });

  it("fetches report download url (PI-046)", async () => {
    stubFetch(200, {
      download_url: "/api/v1/reports/report-123/content?token=jwt-short-lived-token",
      expires_at: "2026-11-08T12:15:00Z",
    });

    const res = await api.getReportDownloadUrl("report-123", "mock-token");
    assert.equal(
      res.download_url,
      "/api/v1/reports/report-123/content?token=jwt-short-lived-token"
    );
    assert.equal(res.expires_at, "2026-11-08T12:15:00Z");
  });

  it("exports activities in CSV or XLSX format (PI-047)", async () => {
    stubFetch(200, {
      id: "export-456",
      project_id: "proj-1",
      project_version_id: "ver-1",
      report_type: "activity_export",
      title: "Activity Export - LNG Train (CSV)",
      output_format: "csv",
      status: "ready",
      parameters: { version_id: "ver-1", format: "csv", critical_only: true },
      created_at: "2026-11-08T13:00:00Z",
      download_url: "/api/v1/reports/export-456/download",
    });

    const res = await api.exportActivities(
      "proj-1",
      {
        version_id: "ver-1",
        format: "csv",
        critical_only: true,
      },
      "mock-token"
    );

    assert.equal(res.id, "export-456");
    assert.equal(res.report_type, "activity_export");
    assert.equal(res.output_format, "csv");
    assert.equal(res.status, "ready");
    assert.equal(res.download_url, "/api/v1/reports/export-456/download");
  });

  it("fetches available subscription plans (PI-050)", async () => {
    stubFetch(200, [
      {
        code: "free",
        name: "Free Starter",
        description: "Essential schedule viewing",
        monthly_price_usd: 0,
        quotas: {
          max_projects: 2,
          max_file_uploads_per_month: 10,
          max_imports_per_month: 5,
          max_ai_queries_per_month: 30,
          max_scenarios_per_month: 10,
          max_reports_per_month: 5,
          max_upload_size_bytes: 15728640,
        },
        features: ["2 Active Projects"],
      },
    ]);

    const res = await api.getPlans("mock-token");
    assert.equal(res.length, 1);
    assert.equal(res[0].code, "free");
    assert.equal(res[0].quotas.max_projects, 2);
  });

  it("fetches workspace usage summary (PI-050)", async () => {
    stubFetch(200, {
      workspace_id: "ws-1",
      plan_code: "free",
      plan_name: "Free Starter",
      billing_period_start: "2026-11-01T00:00:00Z",
      billing_period_end: "2026-11-30T23:59:59Z",
      reset_date: "2026-12-01T00:00:00Z",
      metrics: [
        {
          metric_name: "ai_query",
          display_label: "AI Assistant Inquiries",
          used: 12,
          limit: 30,
          remaining: 18,
          unit: "queries",
          percent_used: 40.0,
        },
      ],
    });

    const res = await api.getUsageSummary("ws-1", "mock-token");
    assert.equal(res.workspace_id, "ws-1");
    assert.equal(res.plan_code, "free");
    assert.equal(res.metrics.length, 1);
    assert.equal(res.metrics[0].used, 12);
    assert.equal(res.metrics[0].remaining, 18);
    assert.equal(res.metrics[0].percent_used, 40.0);
  });

  it("deletes a project (PI-051)", async () => {
    stubFetch(200, {
      status: "deleted",
      project_id: "proj-1",
    });

    const res = await api.deleteProject("proj-1", "mock-token");
    assert.equal(res.status, "deleted");
    assert.equal(res.project_id, "proj-1");
  });

  it("deactivates user account (PI-051)", async () => {
    stubFetch(200, {
      status: "deactivated",
      user_id: "user-1",
    });

    const res = await api.deleteAccount("mock-token");
    assert.equal(res.status, "deactivated");
    assert.equal(res.user_id, "user-1");
  });
});
