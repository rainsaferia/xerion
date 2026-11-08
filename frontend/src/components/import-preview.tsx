"use client";

import React, { useState } from "react";
import {
  api,
  type ImportError,
  type ImportJobOut,
  type ImportWarning,
} from "../lib/api-client";
import {
  STATUS_CONFIG,
  canConfirmImport,
  getPreviewSummaryCounts,
  hasBlockingErrors,
} from "../lib/import-preview-model";

export interface ImportPreviewProps {
  job: ImportJobOut;
  token?: string;
  onConfirmed?: (job: ImportJobOut) => void;
  onRetried?: (job: ImportJobOut) => void;
}

export function ImportPreview({ job: initialJob, token, onConfirmed, onRetried }: ImportPreviewProps) {
  const [job, setJob] = useState<ImportJobOut>(initialJob);
  const [isAcknowledged, setIsAcknowledged] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const blocking = hasBlockingErrors(job);
  const isReady = job.status === "preview_ready";
  const confirmAllowed = canConfirmImport(job, isAcknowledged, isSubmitting);
  const counts = getPreviewSummaryCounts(job.preview_summary);

  const handleConfirm = async () => {
    if (!confirmAllowed) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      const updated = await api.confirmImport(job.id, token);
      setJob(updated);
      onConfirmed?.(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to confirm import.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetry = async () => {
    setIsSubmitting(true);
    setActionError(null);
    try {
      const updated = await api.retryImport(job.id, token);
      setJob(updated);
      setIsAcknowledged(false);
      onRetried?.(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to retry import.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const statusMeta = STATUS_CONFIG[job.status] ?? STATUS_CONFIG.queued;

  return (
    <div className="w-full max-w-5xl mx-auto p-6 space-y-6 bg-white dark:bg-slate-900 rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100">
      {/* 1. Header & Status Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-5 border-b border-slate-200 dark:border-slate-800 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">Schedule Import Preview</h1>
            <span
              data-testid="status-badge"
              className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${statusMeta.badgeClass}`}
            >
              {statusMeta.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Job ID: <span className="font-mono text-xs">{job.id}</span>
          </p>
        </div>

        {/* Progress Bar for Queued/Processing */}
        {(job.status === "queued" || job.status === "processing") && (
          <div className="w-full sm:w-48 space-y-1">
            <div className="flex justify-between text-xs text-slate-600 dark:text-slate-400">
              <span>Progress</span>
              <span>{Math.round(job.progress_pct)}%</span>
            </div>
            <div className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 transition-all duration-300"
                style={{ width: `${Math.max(5, job.progress_pct)}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* 2. Detected Metadata */}
      <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-200 dark:border-slate-800">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
          Detected Schedule Metadata
        </h2>
        {job.detected_metadata && Object.keys(job.detected_metadata).length > 0 ? (
          <div
            data-testid="detected-metadata"
            className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4 text-sm"
          >
            {Object.entries(job.detected_metadata).map(([key, value]) => (
              <div key={key} className="space-y-0.5">
                <span className="text-xs text-slate-500 dark:text-slate-400 font-mono capitalize">
                  {key.replace(/_/g, " ")}
                </span>
                <p className="font-medium text-slate-900 dark:text-slate-100 truncate">
                  {value !== null && value !== undefined ? String(value) : "—"}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500 italic">No metadata detected yet.</p>
        )}
      </div>

      {/* 3. Object Counts Summary */}
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
          Extracted Schedule Objects
        </h2>
        <div data-testid="object-counts" className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">Activities</span>
            <p data-testid="count-activities" className="text-2xl font-bold mt-1 text-slate-900 dark:text-slate-100">
              {counts.activities}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">WBS Nodes</span>
            <p data-testid="count-wbs" className="text-2xl font-bold mt-1 text-slate-900 dark:text-slate-100">
              {counts.wbsNodes}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">Relationships</span>
            <p data-testid="count-relationships" className="text-2xl font-bold mt-1 text-slate-900 dark:text-slate-100">
              {counts.relationships}
            </p>
          </div>
          <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">Calendars</span>
            <p data-testid="count-calendars" className="text-2xl font-bold mt-1 text-slate-900 dark:text-slate-100">
              {counts.calendars}
            </p>
          </div>
        </div>
      </div>

      {/* 4. Blocking Errors Alert */}
      {job.errors && job.errors.length > 0 && (
        <div
          data-testid="blocking-errors"
          className="p-4 rounded-lg border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 text-red-900 dark:text-red-200 space-y-3"
        >
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm">Blocking Errors ({job.errors.length})</span>
            <span className="text-xs px-2 py-0.5 rounded bg-red-200 text-red-800 font-mono font-semibold">
              Confirmation Blocked
            </span>
          </div>
          <p className="text-xs text-red-700 dark:text-red-300">
            This file cannot be confirmed because it contains critical structural or format errors.
          </p>
          <div className="space-y-2 mt-2">
            {job.errors.map((err: ImportError, idx: number) => (
              <div key={idx} className="p-3 rounded bg-white/70 dark:bg-slate-900/60 border border-red-200 dark:border-red-900 text-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono font-semibold text-red-800 dark:text-red-400">{err.code}</span>
                </div>
                <p className="text-slate-800 dark:text-slate-200">{err.message}</p>
                {err.actionable && (
                  <p className="mt-1 text-slate-600 dark:text-slate-400 italic">
                    Remedy: {err.actionable}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Warnings */}
      {job.warnings && job.warnings.length > 0 && (
        <div
          data-testid="warnings-box"
          className="p-4 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 text-amber-900 dark:text-amber-200 space-y-2"
        >
          <span className="font-bold text-sm">Non-Blocking Warnings ({job.warnings.length})</span>
          <div className="space-y-1">
            {job.warnings.map((warn: ImportWarning, idx: number) => (
              <p key={idx} className="text-xs text-amber-800 dark:text-amber-300">
                • <span className="font-mono">{warn.code}</span>: {warn.message}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* 6. Action & Confirmation Section */}
      <div className="pt-4 border-t border-slate-200 dark:border-slate-800 space-y-4">
        {actionError && (
          <div className="p-3 text-xs rounded bg-red-100 text-red-800 border border-red-300">
            {actionError}
          </div>
        )}

        {job.status === "confirmed" ? (
          <div
            data-testid="confirmed-state-banner"
            className="p-4 rounded-lg bg-emerald-50 border border-emerald-300 text-emerald-900 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-200 flex items-center justify-between"
          >
            <div>
              <p className="font-semibold text-sm">Import Confirmed</p>
              <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-0.5">
                Schedule version has been locked. You can now explore activities, run schedule quality checks, and ask the AI assistant questions.
              </p>
            </div>
          </div>
        ) : job.status === "failed" ? (
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-500">
              Resolve the issues highlighted in the blocking errors and retry.
            </p>
            <button
              type="button"
              data-testid="retry-button"
              disabled={isSubmitting}
              onClick={handleRetry}
              className="px-4 py-2 text-sm font-medium rounded-lg bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-50 transition"
            >
              {isSubmitting ? "Retrying..." : "Retry Import Job"}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {/* Explicit confirmation checkbox required by PI-014 */}
            <div className="flex items-start gap-3">
              <input
                id="explicit-confirm"
                type="checkbox"
                data-testid="confirm-checkbox"
                checked={isAcknowledged}
                disabled={blocking || !isReady || isSubmitting}
                onChange={(e) => setIsAcknowledged(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-40"
              />
              <label
                htmlFor="explicit-confirm"
                className={`text-xs ${
                  blocking ? "text-slate-400 cursor-not-allowed" : "text-slate-700 dark:text-slate-300 cursor-pointer"
                }`}
              >
                I have reviewed the schedule structure and metadata. I confirm importing this file to create an immutable project version.
              </label>
            </div>

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
              <p className="text-xs text-slate-500">
                {blocking
                  ? "Confirmation is disabled due to blocking errors."
                  : !isReady
                  ? "Import is not ready for review yet."
                  : !isAcknowledged
                  ? "Check the confirmation box above to proceed."
                  : "Ready to confirm."}
              </p>
              <button
                type="button"
                data-testid="confirm-button"
                disabled={!confirmAllowed}
                onClick={handleConfirm}
                className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition shadow-sm"
              >
                {isSubmitting ? "Confirming..." : "Confirm Import & Create Version"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
