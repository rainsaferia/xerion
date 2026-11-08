import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ImportJobOut } from "./api-client.ts";
import {
  STATUS_CONFIG,
  canConfirmImport,
  formatScheduleCount,
  getPreviewSummaryCounts,
  hasBlockingErrors,
} from "./import-preview-model.ts";

describe("import-preview-model (PI-014 Acceptance Criteria)", () => {
  const baseReadyJob: ImportJobOut = {
    id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    status: "preview_ready",
    progress_pct: 100,
    detected_metadata: {
      project_code: "EPC-FACILITY-001",
      source_format: "xer",
      data_date: "2026-11-05",
    },
    preview_summary: {
      activities: 1250,
      wbs_nodes: 84,
      relationships: 2100,
      calendars: 3,
    },
    warnings: [],
    errors: [],
    created_at: "2026-11-05T10:00:00Z",
    finished_at: "2026-11-05T10:01:00Z",
  };

  it("configures all status badges correctly", () => {
    assert.equal(STATUS_CONFIG.queued.label, "Queued");
    assert.equal(STATUS_CONFIG.processing.label, "Processing");
    assert.equal(STATUS_CONFIG.preview_ready.label, "Ready for Review");
    assert.equal(STATUS_CONFIG.failed.label, "Failed");
    assert.equal(STATUS_CONFIG.confirmed.label, "Confirmed");
  });

  it("formats schedule object counts cleanly", () => {
    assert.equal(formatScheduleCount(1250), "1,250");
    assert.equal(formatScheduleCount(0), "0");
    assert.equal(formatScheduleCount(undefined), "0");

    const counts = getPreviewSummaryCounts(baseReadyJob.preview_summary);
    assert.equal(counts.activities, "1,250");
    assert.equal(counts.wbsNodes, "84");
    assert.equal(counts.relationships, "2,100");
    assert.equal(counts.calendars, "3");
  });

  it("identifies blocking errors when errors array is non-empty", () => {
    const jobWithErrors: ImportJobOut = {
      ...baseReadyJob,
      errors: [
        {
          code: "INVALID_XER_HEADER",
          message: "XER file is missing valid ERMHDR header.",
          actionable: "Export again from Oracle Primavera P6.",
        },
      ],
    };
    assert.equal(hasBlockingErrors(jobWithErrors), true);
  });

  it("identifies blocking errors when status is failed", () => {
    const failedJob: ImportJobOut = {
      ...baseReadyJob,
      status: "failed",
    };
    assert.equal(hasBlockingErrors(failedJob), true);
  });

  it("identifies clean jobs as having no blocking errors", () => {
    assert.equal(hasBlockingErrors(baseReadyJob), false);
  });

  it("PI-014: User cannot confirm a blocking import", () => {
    const jobWithErrors: ImportJobOut = {
      ...baseReadyJob,
      errors: [
        {
          code: "INVALID_XER_HEADER",
          message: "XER file is missing header.",
          actionable: "Fix header.",
        },
      ],
    };
    // Even if user checks the acknowledgment checkbox, canConfirmImport must remain false!
    const allowed = canConfirmImport(jobWithErrors, true, false);
    assert.equal(allowed, false, "Blocking import must NOT be confirmable");
  });

  it("PI-014: User cannot confirm when job status is not preview_ready", () => {
    const queuedJob: ImportJobOut = { ...baseReadyJob, status: "queued" };
    assert.equal(canConfirmImport(queuedJob, true, false), false);

    const processingJob: ImportJobOut = { ...baseReadyJob, status: "processing" };
    assert.equal(canConfirmImport(processingJob, true, false), false);

    const confirmedJob: ImportJobOut = { ...baseReadyJob, status: "confirmed" };
    assert.equal(canConfirmImport(confirmedJob, true, false), false);
  });

  it("PI-014: Confirmation is explicit (must be acknowledged)", () => {
    // When isAcknowledged is false, confirmation is not permitted
    assert.equal(canConfirmImport(baseReadyJob, false, false), false);

    // Once acknowledged with valid ready job, confirmation is permitted
    assert.equal(canConfirmImport(baseReadyJob, true, false), true);
  });

  it("disallows confirmation while submitting", () => {
    assert.equal(canConfirmImport(baseReadyJob, true, true), false);
  });
});

