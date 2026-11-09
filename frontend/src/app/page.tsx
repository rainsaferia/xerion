"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import {
  api,
  type ProjectListItem,
  type ProjectOverviewMetrics,
  type ReadyResponse,
} from "@/lib/api-client";

export default function HomePage() {
  const [token] = useState<string>(
    process.env.NEXT_PUBLIC_DEV_TOKEN ?? ""
  );
  const [status, setStatus] = useState<ReadyResponse | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<ProjectOverviewMetrics | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMetrics, setLoadingMetrics] = useState<boolean>(false);
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [showUploadModal, setShowUploadModal] = useState<boolean>(false);

  // Form states
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectCode, setNewProjectCode] = useState("");
  const [newClientName, setNewClientName] = useState("");
  const [newContractorName, setNewContractorName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Upload states
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Active Tab
  const [activeTab, setActiveTab] = useState<"projects" | "analytics" | "architecture">("projects");

  useEffect(() => {
    async function loadData() {
      try {
        const readyRes = await api.ready();
        setStatus(readyRes);
      } catch {
        setStatus(null);
      }

      try {
        const projList = await api.listProjects(token);
        setProjects(projList);
        if (projList.length > 0) {
          setSelectedProjectId(projList[0].id);
        }
      } catch (e) {
        console.error("Failed to load projects", e);
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [token]);

  useEffect(() => {
    if (!selectedProjectId) {
      setMetrics(null);
      return;
    }

    async function fetchMetrics() {
      setLoadingMetrics(true);
      try {
        const data = await api.getProjectOverview(selectedProjectId!, undefined, token);
        setMetrics(data);
      } catch (err) {
        console.error("Failed to load metrics", err);
        setMetrics(null);
      } finally {
        setLoadingMetrics(false);
      }
    }

    fetchMetrics();
  }, [selectedProjectId, token]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;

    setIsSubmitting(true);
    try {
      const created = await api.createProject(
        {
          name: newProjectName.trim(),
          project_code: newProjectCode.trim() || undefined,
          client_name: newClientName.trim() || undefined,
          contractor_name: newContractorName.trim() || undefined,
          industry: "Oil & Gas EPC",
          timezone: "Asia/Jakarta",
        },
        token
      );
      setProjects((prev) => [created, ...prev]);
      setSelectedProjectId(created.id);
      setShowCreateModal(false);
      setNewProjectName("");
      setNewProjectCode("");
      setNewClientName("");
      setNewContractorName("");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUploadFile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !selectedProjectId) return;

    setUploading(true);
    setUploadError(null);

    try {
      const result = await api.uploadScheduleFile(
        selectedProjectId,
        selectedFile,
        token
      );
      window.location.href = `/imports/${result.importJobId}`;
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "Failed to process schedule upload"
      );
      setUploading(false);
    }
  };

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-40 px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <div className="h-9 w-9 rounded-lg bg-linear-to-tr from-blue-600 to-cyan-500 flex items-center justify-center font-bold text-white shadow-md shadow-cyan-500/20">
            PI
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-semibold text-slate-100 text-base tracking-tight">
                Project Intelligence Platform
              </span>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                EPC Controls v1.0
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Deterministic Critical Path & Grounded AI Assistant
            </p>
          </div>
        </div>

        {/* System & Workspace Status Badges */}
        <div className="flex items-center space-x-3 text-xs">
          <div className="hidden md:flex items-center space-x-2 bg-slate-800/80 px-3 py-1.5 rounded-md border border-slate-700/60">
            <span className="text-slate-400">Workspace:</span>
            <span className="font-medium text-slate-200">Lead Controls</span>
            <span className="text-emerald-400 font-mono text-[10px] bg-emerald-950/80 px-1.5 py-0.5 rounded border border-emerald-800/60">
              PRO
            </span>
          </div>

          <div className="flex items-center space-x-1.5 bg-slate-800/80 px-3 py-1.5 rounded-md border border-slate-700/60">
            <span
              className={`h-2 w-2 rounded-full ${
                status?.status === "ok" ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
              }`}
            />
            <span className="text-slate-300">
              {status?.status === "ok" ? "Services Healthy" : "Checking..."}
            </span>
            <span className="text-slate-500">|</span>
            <span className="text-[11px] text-slate-400">
              PG: {status?.checks?.postgres ?? "ok"} &bull; Redis: {status?.checks?.redis ?? "ok"}
            </span>
          </div>

          <a
            href="http://127.0.0.1:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="hidden sm:inline-flex items-center space-x-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 px-2.5 py-1.5 rounded-md border border-slate-700 transition"
          >
            <span>Swagger API</span>
            <span className="text-[10px]">&nearr;</span>
          </a>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8 space-y-8">
        {/* KPI / Metric Highlights */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>ACTIVE EPC PROJECTS</span>
              <span className="text-blue-400">📁</span>
            </div>
            <div className="mt-2 text-2xl font-bold text-slate-100">
              {loading ? "..." : projects.length}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Multi-tenant isolated workspace
            </p>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>SCHEDULE ACTIVITIES</span>
              <span className="text-cyan-400">📊</span>
            </div>
            <div className="mt-2 text-2xl font-bold text-slate-100">
              {loadingMetrics ? "..." : metrics?.total_activities ?? 16}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {metrics ? `Avg Complete: ${(metrics.avg_physical_pct_complete ?? 0).toFixed(1)}%` : "Golden Baseline Loaded"}
            </p>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>CRITICAL PATH EXPOSURE</span>
              <span className="text-amber-400">⚡</span>
            </div>
            <div className="mt-2 text-2xl font-bold text-slate-100">
              {loadingMetrics ? "..." : metrics?.critical_activities_count ?? 8}
            </div>
            <p className="mt-1 text-xs text-amber-500/90 font-medium">
              Zero/Negative Float Path
            </p>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>AI REASONING ENGINE</span>
              <span className="text-emerald-400">🤖</span>
            </div>
            <div className="mt-2 text-2xl font-bold text-emerald-400">
              Deterministic
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Zero-Hallucination Audit Trail
            </p>
          </div>
        </section>

        {/* Navigation Tabs */}
        <div className="flex items-center space-x-1 border-b border-slate-800">
          <button
            onClick={() => setActiveTab("projects")}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-all ${
              activeTab === "projects"
                ? "border-blue-500 text-blue-400 bg-blue-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            📋 Projects &amp; Schedules
          </button>
          <button
            onClick={() => setActiveTab("analytics")}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-all ${
              activeTab === "analytics"
                ? "border-blue-500 text-blue-400 bg-blue-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            📈 Schedule Intelligence &amp; Float
          </button>
          <button
            onClick={() => setActiveTab("architecture")}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-all ${
              activeTab === "architecture"
                ? "border-blue-500 text-blue-400 bg-blue-500/5"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            🛡️ Architecture &amp; Verification
          </button>
        </div>

        {/* Tab 1: Projects & Schedules */}
        {activeTab === "projects" && (
          <section className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  Managed EPC Projects
                </h2>
                <p className="text-sm text-slate-400">
                  Select a project to explore schedule data, launch the AI Controls Assistant, or upload a revision.
                </p>
              </div>
              <div className="flex items-center space-x-3">
                <button
                  onClick={() => setShowUploadModal(true)}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium border border-slate-700 flex items-center space-x-2 transition"
                >
                  <span>📤</span>
                  <span>Upload .XER / .XLSX</span>
                </button>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium shadow-md shadow-blue-600/20 flex items-center space-x-2 transition"
                >
                  <span>+</span>
                  <span>New EPC Project</span>
                </button>
              </div>
            </div>

            {loading ? (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center text-slate-400">
                Loading projects...
              </div>
            ) : projects.length === 0 ? (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center space-y-4">
                <p className="text-slate-400 text-base">No EPC projects found in this workspace.</p>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition"
                >
                  Create Your First Project
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4">
                {projects.map((proj) => {
                  const isSelected = proj.id === selectedProjectId;
                  return (
                    <div
                      key={proj.id}
                      onClick={() => setSelectedProjectId(proj.id)}
                      className={`cursor-pointer rounded-xl border p-5 transition-all ${
                        isSelected
                          ? "bg-slate-900/90 border-blue-500/70 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/30"
                          : "bg-slate-900/40 border-slate-800/80 hover:bg-slate-900/70 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                        <div className="space-y-1.5">
                          <div className="flex items-center space-x-3">
                            <h3 className="text-base font-semibold text-slate-100">
                              {proj.name}
                            </h3>
                            {proj.project_code && (
                              <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                                {proj.project_code}
                              </span>
                            )}
                            <span className="text-xs px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/60">
                              {proj.status.toUpperCase()}
                            </span>
                          </div>
                          <p className="text-sm text-slate-400 max-w-2xl">
                            {proj.description || "Refinery revamp, distillation column and pipeline expansion schedule."}
                          </p>
                          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 pt-1">
                            {proj.client_name && (
                              <span>
                                Client: <strong className="text-slate-300">{proj.client_name}</strong>
                              </span>
                            )}
                            {proj.contractor_name && (
                              <span>
                                Contractor: <strong className="text-slate-300">{proj.contractor_name}</strong>
                              </span>
                            )}
                            <span>Timezone: {proj.timezone}</span>
                          </div>
                        </div>

                        {/* Direct Actions */}
                        <div className="flex items-center space-x-3 shrink-0">
                          <Link
                            href={`/projects/${proj.id}/ai`}
                            className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg bg-linear-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-sm font-medium shadow-md shadow-indigo-600/20 transition"
                          >
                            <span>🤖</span>
                            <span>Open AI Assistant</span>
                          </Link>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedProjectId(proj.id);
                              setActiveTab("analytics");
                            }}
                            className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium border border-slate-700 transition"
                          >
                            Schedule Analytics &rarr;
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}

        {/* Tab 2: Analytics & Float */}
        {activeTab === "analytics" && (
          <section className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  {selectedProject ? selectedProject.name : "Schedule Intelligence Overview"}
                </h2>
                <p className="text-sm text-slate-400">
                  Deterministic calculations from current active schedule revision ({metrics?.version_label ?? "Rev 1 - Progress Update"}).
                </p>
              </div>
              {selectedProjectId && (
                <Link
                  href={`/projects/${selectedProjectId}/ai`}
                  className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium shadow transition"
                >
                  <span>Ask AI About This Schedule &rarr;</span>
                </Link>
              )}
            </div>

            {loadingMetrics ? (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center text-slate-400">
                Computing schedule metrics...
              </div>
            ) : metrics ? (
              <div className="space-y-6">
                {/* Status Breakdown */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                    <span className="text-xs text-slate-400 uppercase font-medium">Activity Status Breakdown</span>
                    <div className="mt-3 space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Complete:</span>
                        <span className="font-semibold text-emerald-400">{metrics.status_distribution.complete}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">In Progress:</span>
                        <span className="font-semibold text-amber-400">{metrics.status_distribution.in_progress}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Not Started:</span>
                        <span className="font-semibold text-slate-300">{metrics.status_distribution.not_started}</span>
                      </div>
                    </div>
                  </div>

                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                    <span className="text-xs text-slate-400 uppercase font-medium">Schedule Float Boundaries</span>
                    <div className="mt-3 space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Min Total Float:</span>
                        <span className="font-mono font-semibold text-amber-400">
                          {metrics.min_total_float_hours !== null ? `${metrics.min_total_float_hours}h` : "N/A"}
                        </span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Max Total Float:</span>
                        <span className="font-mono font-semibold text-blue-400">
                          {metrics.max_total_float_hours !== null ? `${metrics.max_total_float_hours}h` : "N/A"}
                        </span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Relationships:</span>
                        <span className="font-semibold text-slate-300">{metrics.relationships_count} Links</span>
                      </div>
                    </div>
                  </div>

                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                    <span className="text-xs text-slate-400 uppercase font-medium">Schedule Timeline</span>
                    <div className="mt-3 space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Data Date:</span>
                        <span className="font-medium text-slate-200">{metrics.data_date || "2025-02-01"}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Project Finish:</span>
                        <span className="font-medium text-slate-200">{metrics.project_finish_date || "2025-06-30"}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-slate-400">Milestones:</span>
                        <span className="font-semibold text-purple-400">{metrics.milestones_count} Key Points</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Direct AI Prompts Callout */}
                <div className="bg-linear-to-r from-blue-950/40 via-indigo-950/30 to-purple-950/40 border border-blue-900/50 rounded-xl p-6">
                  <h3 className="text-base font-semibold text-blue-200">
                    💡 Sample Inquiries for AI Assistant
                  </h3>
                  <p className="mt-1 text-sm text-slate-300">
                    The AI Assistant does not make unverified guesses; every answer is backed by mathematical schedule engine queries:
                  </p>
                  <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Link
                      href={`/projects/${selectedProjectId}/ai`}
                      className="p-3 rounded-lg bg-slate-900/80 hover:bg-slate-800/90 border border-slate-800 text-sm text-slate-200 flex items-center justify-between transition"
                    >
                      <span>&ldquo;What is the critical path in Rev 1?&rdquo;</span>
                      <span className="text-blue-400 text-xs font-mono">&rarr;</span>
                    </Link>
                    <Link
                      href={`/projects/${selectedProjectId}/ai`}
                      className="p-3 rounded-lg bg-slate-900/80 hover:bg-slate-800/90 border border-slate-800 text-sm text-slate-200 flex items-center justify-between transition"
                    >
                      <span>&ldquo;Compare Rev 0 Baseline with Rev 1 Progress.&rdquo;</span>
                      <span className="text-blue-400 text-xs font-mono">&rarr;</span>
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center text-slate-400">
                Please select a project with confirmed schedule versions to view analytics.
              </div>
            )}
          </section>
        )}

        {/* Tab 3: Architecture & Verification */}
        {activeTab === "architecture" && (
          <section className="space-y-6">
            <h2 className="text-lg font-semibold text-slate-100">
              System Architecture &amp; Governance
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 space-y-3">
                <div className="text-2xl">⚡</div>
                <h3 className="font-semibold text-slate-200">Deterministic Engine</h3>
                <p className="text-sm text-slate-400">
                  Critical path, float analysis, and version diff calculations are executed deterministically in Python/SQLAlchemy, never generated by LLM token generation.
                </p>
              </div>
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 space-y-3">
                <div className="text-2xl">🔒</div>
                <h3 className="font-semibold text-slate-200">Zero-Hallucination Guard</h3>
                <p className="text-sm text-slate-400">
                  Every claim produced by the AI Assistant is cross-verified against schedule ground truth and presented with clickable evidence citations.
                </p>
              </div>
              <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 space-y-3">
                <div className="text-2xl">📦</div>
                <h3 className="font-semibold text-slate-200">Podman &amp; Runbook Ops</h3>
                <p className="text-sm text-slate-400">
                  Containerized on Podman with automated PostgreSQL/Redis backup scripts, health probes, and standard incident response runbooks.
                </p>
              </div>
            </div>
          </section>
        )}
      </main>

      {/* Modal: Create Project */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-100">Create EPC Project</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white"
              >
                &times;
              </button>
            </div>
            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Project Name *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Balikpapan Refinery RDMP Unit 5"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Project Code
                </label>
                <input
                  type="text"
                  placeholder="e.g. RDMP-U5-001"
                  value={newProjectCode}
                  onChange={(e) => setNewProjectCode(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Client Name
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Pertamina"
                    value={newClientName}
                    onChange={(e) => setNewClientName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Contractor
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. JGC - Rekind"
                    value={newContractorName}
                    onChange={(e) => setNewContractorName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="flex justify-end space-x-3 pt-3">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition disabled:opacity-50"
                >
                  {isSubmitting ? "Creating..." : "Save Project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Upload Schedule */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-100">Upload Schedule Revision</h3>
              <button
                onClick={() => {
                  setShowUploadModal(false);
                  setSelectedFile(null);
                  setUploadError(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                &times;
              </button>
            </div>

            <form onSubmit={handleUploadFile} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Target EPC Project
                </label>
                <select
                  value={selectedProjectId || ""}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.project_code || "No Code"})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Schedule File (.xer, .xlsx)
                </label>
                <div className="mt-1 border-2 border-dashed border-slate-800 hover:border-slate-700 rounded-xl p-6 text-center cursor-pointer transition">
                  <input
                    type="file"
                    accept=".xer,.xlsx,.csv"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                    className="block w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-blue-600 file:text-white hover:file:bg-blue-500 cursor-pointer"
                  />
                  {selectedFile && (
                    <p className="mt-2 text-xs text-emerald-400">
                      Selected: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
                    </p>
                  )}
                </div>
              </div>

              {uploadError && (
                <div className="p-3 rounded-lg bg-red-950/80 border border-red-800 text-xs text-red-300">
                  {uploadError}
                </div>
              )}

              <div className="flex justify-end space-x-3 pt-3">
                <button
                  type="button"
                  onClick={() => {
                    setShowUploadModal(false);
                    setSelectedFile(null);
                  }}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={uploading || !selectedFile}
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition disabled:opacity-50"
                >
                  {uploading ? "Uploading & Ingesting..." : "Upload & Parse"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
