"use client";

import Link from "next/link";
import React, { useEffect, useState, use } from "react";
import { ImportPreview } from "@/components/import-preview";
import { api, type ImportJobOut } from "@/lib/api-client";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ImportPreviewPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const jobId = resolvedParams.id;

  const [job, setJob] = useState<ImportJobOut | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    let timer: NodeJS.Timeout | null = null;

    async function fetchJob() {
      try {
        const data = await api.getImportJob(jobId);
        if (!isMounted) return;
        setJob(data);
        setLoading(false);

        // Auto-poll if job is still in progress
        if (data.status === "queued" || data.status === "processing") {
          timer = setTimeout(fetchJob, 1500);
        }
      } catch (err) {
        if (!isMounted) return;
        setFetchError(err instanceof Error ? err.message : "Failed to load import job");
        setLoading(false);
      }
    }

    fetchJob();

    return () => {
      isMounted = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 p-6">
        <div className="text-center space-y-3">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-4 border-slate-300 border-t-blue-600" />
          <p className="text-sm text-slate-500">Loading schedule preview...</p>
        </div>
      </div>
    );
  }

  if (fetchError || !job) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 p-6">
        <div className="max-w-md w-full bg-white dark:bg-slate-900 p-6 rounded-xl border border-red-200 dark:border-red-900 text-center space-y-4">
          <h2 className="text-lg font-bold text-red-600">Failed to Load Import</h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">{fetchError ?? "Import job not found"}</p>
          <Link
            href="/"
            className="inline-block px-4 py-2 text-xs font-medium rounded-lg bg-slate-800 text-white hover:bg-slate-700 transition"
          >
            Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-950 py-10 px-4 sm:px-6">
      <ImportPreview job={job} />
    </div>
  );
}
