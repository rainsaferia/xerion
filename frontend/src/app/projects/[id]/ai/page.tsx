"use client";

import Link from "next/link";
import React, { use, useEffect, useState } from "react";
import { AiAssistantView } from "@/components/ai-assistant-view";
import { api, type ProjectOverviewMetrics } from "@/lib/api-client";

interface AiPageProps {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ c?: string }>;
}

export default function ProjectAiAssistantPage({ params, searchParams }: AiPageProps) {
  const resolvedParams = use(params);
  const resolvedSearchParams = searchParams ? use(searchParams) : undefined;
  const projectId = resolvedParams.id;
  const selectedConversationId = resolvedSearchParams?.c;
  const token = process.env.NEXT_PUBLIC_DEV_TOKEN;

  const [overview, setOverview] = useState<ProjectOverviewMetrics | null>(null);

  useEffect(() => {
    let isMounted = true;
    api
      .getProjectOverview(projectId, undefined, token)
      .then((data) => {
        if (isMounted) setOverview(data);
      })
      .catch((err) => {
        console.warn("Could not fetch project overview for header:", err);
      });
    return () => {
      isMounted = false;
    };
  }, [projectId, token]);

  const projectName = overview?.project_name ?? "TEP3-177 Offshore Gas Processing Facility";
  const activeVersionLabel = overview?.version_label ? `V${overview.version_number} (${overview.version_label})` : "V1";
  const dataDate = overview?.data_date ?? undefined;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-blue-600/30 selection:text-blue-200">
      <header className="border-b border-slate-800 bg-slate-950/90 px-6 py-3.5 flex items-center justify-between backdrop-blur-md sticky top-0 z-30">
        <div className="flex items-center space-x-4">
          <Link
            href={`/projects/${projectId}`}
            className="flex items-center space-x-2 text-xs font-medium text-slate-400 hover:text-white transition-colors py-1 px-2.5 rounded-lg hover:bg-slate-800/60"
          >
            <span>&larr;</span>
            <span>Back to Project Dashboard</span>
          </Link>
          <div className="h-4 w-px bg-slate-800" />
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <h1 className="text-sm font-semibold text-slate-200 tracking-tight">
              AI Project Controls Assistant
            </h1>
          </div>
        </div>
        <div className="flex items-center space-x-3 text-xs text-slate-400">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-950/60 text-emerald-400 border border-emerald-800/80 font-medium">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Zero-Hallucination Active
          </span>
          <span className="font-mono text-slate-500 text-[11px] bg-slate-900 px-2 py-1 rounded border border-slate-800">
            {projectName.slice(0, 24)}
          </span>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-6 flex flex-col justify-center max-w-7xl w-full mx-auto">
        <AiAssistantView
          projectId={projectId}
          projectName={projectName}
          activeVersionLabel={activeVersionLabel}
          dataDate={dataDate}
          selectedConversationId={selectedConversationId}
          token={token}
        />
      </main>
    </div>
  );
}
