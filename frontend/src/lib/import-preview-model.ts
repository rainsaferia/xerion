import type {
  ImportJobOut,
  ImportJobStatus,
  PreviewSummary,
} from "./api-client";

export interface StatusBadgeConfig {
  label: string;
  badgeClass: string;
  description: string;
}

export const STATUS_CONFIG: Record<ImportJobStatus, StatusBadgeConfig> = {
  queued: {
    label: "Queued",
    badgeClass: "bg-slate-100 text-slate-800 border-slate-300",
    description: "Import job is waiting in the worker queue.",
  },
  processing: {
    label: "Processing",
    badgeClass: "bg-blue-100 text-blue-800 border-blue-300",
    description: "Worker is extracting schedule tables and metadata.",
  },
  preview_ready: {
    label: "Ready for Review",
    badgeClass: "bg-emerald-100 text-emerald-800 border-emerald-300",
    description: "Parsing complete. Review schedule metrics before confirming.",
  },
  failed: {
    label: "Failed",
    badgeClass: "bg-red-100 text-red-800 border-red-300",
    description: "Job failed with errors. Review actionable guidance below.",
  },
  confirmed: {
    label: "Confirmed",
    badgeClass: "bg-indigo-100 text-indigo-800 border-indigo-300",
    description: "Import has been confirmed and locked as an immutable project version.",
  },
};

export function hasBlockingErrors(job: ImportJobOut): boolean {
  return (job.errors && job.errors.length > 0) || job.status === "failed";
}

export function canConfirmImport(
  job: ImportJobOut,
  isAcknowledged: boolean,
  isSubmitting: boolean = false
): boolean {
  if (isSubmitting) return false;
  if (!isAcknowledged) return false;
  if (job.status !== "preview_ready") return false;
  if (hasBlockingErrors(job)) return false;
  return true;
}

export function formatScheduleCount(count: number | undefined | null): string {
  if (count === undefined || count === null) return "0";
  return count.toLocaleString();
}

export function getPreviewSummaryCounts(summary: PreviewSummary | null): {
  activities: string;
  wbsNodes: string;
  relationships: string;
  calendars: string;
} {
  return {
    activities: formatScheduleCount(summary?.activities),
    wbsNodes: formatScheduleCount(summary?.wbs_nodes),
    relationships: formatScheduleCount(summary?.relationships),
    calendars: formatScheduleCount(summary?.calendars),
  };
}

