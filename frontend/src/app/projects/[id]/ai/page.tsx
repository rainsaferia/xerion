"use client";

import React, { use } from "react";
import { AiAssistantView } from "@/components/ai-assistant-view";

interface AiPageProps {
  params: Promise<{ id: string }>;
}

export default function ProjectAiAssistantPage({ params }: AiPageProps) {
  const resolvedParams = use(params);
  const projectId = resolvedParams.id;

  return (
    <main className="min-h-screen bg-slate-100/70 dark:bg-slate-950 p-6 flex flex-col justify-center">
      <AiAssistantView
        projectId={projectId}
        projectName="Project EPC Schedule"
        activeVersionLabel="Current Active Version"
      />
    </main>
  );
}

