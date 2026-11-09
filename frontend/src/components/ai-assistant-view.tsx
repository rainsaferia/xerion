"use client";

import React, { useEffect, useState } from "react";
import { MarkdownMessage } from "./markdown-message";
import {
  QUESTION_STARTERS,
  VALIDATION_BADGE_CONFIG,
  formatEvidenceCitation,
  formatToolDuration,
} from "../lib/ai-assistant-model";
import {
  api,
  type ConversationResponse,
  type MessageItem,
  type ToolExecutionItem,
  type ValidationStatus,
} from "../lib/api-client";

export interface AiAssistantViewProps {
  projectId: string;
  projectName?: string;
  activeVersionLabel?: string;
  dataDate?: string;
  selectedConversationId?: string;
  initialConversations?: ConversationResponse[];
  token?: string;
}

let tempCounter = 0;
function buildOptimisticUserMessage(content: string): MessageItem {
  tempCounter += 1;
  return {
    id: `temp-${tempCounter}`,
    role: "user",
    content,
    created_at: "",
  };
}

export function AiAssistantView({
  projectId,
  projectName = "Project Schedule",
  activeVersionLabel = "Latest Confirmed",
  dataDate,
  selectedConversationId,
  initialConversations = [],
  token,
}: AiAssistantViewProps) {
  const [conversations, setConversations] = useState<ConversationResponse[]>(initialConversations);
  const [activeConvId, setActiveConvId] = useState<string | null>(
    selectedConversationId ?? initialConversations[0]?.id ?? null
  );
  const [activeConversation, setActiveConversation] = useState<ConversationResponse | null>(
    initialConversations[0] ?? null
  );
  const [inputMessage, setInputMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({});

  // 1. Load conversations list if not provided
  useEffect(() => {
    if (initialConversations.length > 0) return;
    let isMounted = true;
    const fetchList = async () => {
      try {
        const list = await api.listConversations(projectId, token);
        if (!isMounted) return;
        setConversations(list);
        if (list.length > 0) {
          const target = selectedConversationId
            ? list.find((c) => c.id === selectedConversationId) ?? list[0]
            : list[0];
          setActiveConvId(target.id);
          setActiveConversation(target);
        }
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to load conversations.");
      }
    };
    void fetchList();
    return () => {
      isMounted = false;
    };
  }, [projectId, token, initialConversations.length, selectedConversationId]);

  // 2. Load active conversation details when selection changes
  useEffect(() => {
    if (!activeConvId) return;
    let isMounted = true;
    const fetchConv = async () => {
      setIsLoadingHistory(true);
      setError(null);
      try {
        const fullConv = await api.getConversation(projectId, activeConvId, token);
        if (!isMounted) return;
        setActiveConversation(fullConv);
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to load conversation details.");
      } finally {
        if (isMounted) setIsLoadingHistory(false);
      }
    };
    void fetchConv();
    return () => {
      isMounted = false;
    };
  }, [projectId, activeConvId, token]);

  // 3. Create new conversation
  const handleCreateNewChat = async () => {
    setError(null);
    try {
      const created = await api.createConversation(
        projectId,
        { title: `Analysis Session ${conversations.length + 1}` },
        token
      );
      setConversations((prev) => [created, ...prev]);
      setActiveConvId(created.id);
      setActiveConversation(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create conversation.");
    }
  };

  // 4. Send message
  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend ?? inputMessage).trim();
    if (!text || isSending) return;

    let convId = activeConvId;
    setError(null);
    setIsSending(true);

    try {
      // Create conversation first if none exists
      if (!convId) {
        const newConv = await api.createConversation(
          projectId,
          { title: text.slice(0, 40) },
          token
        );
        convId = newConv.id;
        setActiveConvId(newConv.id);
        setConversations((prev) => [newConv, ...prev]);
      }

      // Optimistic user message append
      const optimisticUserMsg = buildOptimisticUserMessage(text);

      setActiveConversation((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          messages: [...prev.messages, optimisticUserMsg],
        };
      });
      setInputMessage("");

      // Execute agent turn via API
      const turnResponse = await api.sendMessage(
        projectId,
        convId,
        { message: text },
        token,
        { timeoutMs: 300000 }
      );

      // Append assistant message with tool executions
      const assistantMsg: MessageItem = {
        id: turnResponse.message.id,
        role: turnResponse.message.role,
        content: turnResponse.message.content,
        tool_executions: turnResponse.tool_executions,
        created_at: turnResponse.message.created_at,
      };

      setActiveConversation((prev) => {
        if (!prev) return null;
        const filtered = prev.messages.filter((m) => m.id !== optimisticUserMsg.id);
        return {
          ...prev,
          messages: [...filtered, optimisticUserMsg, assistantMsg],
        };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to execute AI turn.");
    } finally {
      setIsSending(false);
    }
  };

  const toggleToolExpanded = (execId: string) => {
    setExpandedTools((prev) => ({
      ...prev,
      [execId]: !prev[execId],
    }));
  };

  return (
    <div className="flex h-210 w-full max-w-7xl mx-auto rounded-2xl border border-slate-800 bg-slate-900/90 shadow-2xl backdrop-blur-xl overflow-hidden text-slate-100 font-sans">
      {/* =========================================================================
          LEFT SIDEBAR: Conversation Sessions
          ========================================================================= */}
      <aside className="w-72 lg:w-80 border-r border-slate-800 flex flex-col bg-slate-950/70 shrink-0">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
            <h2 className="text-xs font-semibold tracking-wider uppercase text-slate-400">
              Conversations
            </h2>
          </div>
          <button
            onClick={handleCreateNewChat}
            data-testid="new-chat-button"
            className="px-3 py-1.5 text-xs font-medium text-blue-400 hover:text-blue-300 hover:bg-blue-950/60 rounded-lg border border-blue-800/80 transition-colors shadow-sm"
          >
            + New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1.5 scrollbar-thin scrollbar-thumb-slate-800">
          {conversations.length === 0 ? (
            <div className="text-center py-8 text-xs text-slate-500">
              No previous conversations. Start a new analysis session.
            </div>
          ) : (
            conversations.map((c) => {
              const isSelected = c.id === activeConvId;
              return (
                <button
                  key={c.id}
                  onClick={() => setActiveConvId(c.id)}
                  data-testid={`conv-item-${c.id}`}
                  className={`w-full text-left p-3 rounded-xl text-xs transition-all flex flex-col gap-1 border ${
                    isSelected
                      ? "bg-slate-800/90 border-blue-500/60 shadow-md text-white ring-1 ring-blue-500/30"
                      : "border-transparent hover:bg-slate-850/60 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <div className="font-medium truncate">{c.title || "Untitled Session"}</div>
                  <div className="text-[10px] text-slate-500">
                    {new Date(c.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* =========================================================================
          CENTER WORKSPACE: Active Conversation & Context Header
          ========================================================================= */}
      <section className="flex-1 flex flex-col bg-slate-900/60 min-w-0">
        {/* Context Topbar */}
        <header className="px-6 py-4 border-b border-slate-800/80 flex items-center justify-between bg-slate-950/50 backdrop-blur-md">
          <div className="min-w-0 pr-4">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-base font-bold tracking-tight text-white truncate max-w-md">{projectName}</h1>
              <span
                data-testid="version-badge"
                className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-blue-950/90 text-blue-300 border border-blue-800"
              >
                Analyzed Version: {activeVersionLabel}
              </span>
              {dataDate && (
                <span className="text-xs font-mono text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/60">
                  Data Date: {dataDate}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Deterministic schedule reasoning powered by validated domain engines.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="px-2.5 py-1 text-[11px] font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800 rounded-md shadow-sm flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              CPM Engine Active
            </span>
          </div>
        </header>

        {/* Error notification banner */}
        {error && (
          <div
            role="alert"
            className="p-3 mx-6 mt-4 text-xs bg-red-950/60 text-red-300 border border-red-900/80 rounded-lg flex items-center justify-between"
          >
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-200 font-bold ml-2"
            >
              ×
            </button>
          </div>
        )}

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin scrollbar-thumb-slate-800">
          {isLoadingHistory ? (
            <div className="flex items-center justify-center h-48 text-xs text-slate-400">
              Loading conversation history...
            </div>
          ) : !activeConversation || activeConversation.messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center max-w-md mx-auto py-12">
              <div className="h-12 w-12 rounded-2xl bg-blue-950/70 text-blue-400 flex items-center justify-center text-xl font-bold mb-4 border border-blue-800 shadow-inner">
                PI
              </div>
              <h3 className="text-base font-semibold text-slate-100">How can I assist your schedule today?</h3>
              <p className="text-xs text-slate-400 mt-1">
                Ask about critical float exposure, schedule quality diagnostics, activity logic,
                or compare changes against baselines.
              </p>
            </div>
          ) : (
            activeConversation.messages.map((msg) => {
              const isUser = msg.role === "user";
              return (
                <div
                  key={msg.id}
                  data-testid={`message-${msg.id}`}
                  className={`flex gap-3.5 ${isUser ? "justify-end" : "justify-start"}`}
                >
                  {!isUser && (
                    <div className="h-8 w-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-xs shrink-0 shadow-md">
                      AI
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] lg:max-w-3xl rounded-2xl p-4 text-sm leading-relaxed space-y-3 ${
                      isUser
                        ? "bg-blue-600 text-white rounded-br-none shadow-md ring-1 ring-blue-400/30"
                        : "bg-slate-950/80 border border-slate-800 rounded-bl-none shadow-lg text-slate-200"
                    }`}
                  >
                    {/* Assistant Header: Validation Status Badge */}
                    {!isUser && (
                      <div className="flex items-center gap-2 pb-2 border-b border-slate-800/80">
                        {renderValidationBadge(msg)}
                      </div>
                    )}

                    {/* Content text: Rendered with MarkdownMessage for Assistant */}
                    {isUser ? (
                      <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                    ) : (
                      <MarkdownMessage content={msg.content ?? ""} />
                    )}

                    {/* How this was analyzed: Tool Executions Accordion */}
                    {!isUser && msg.tool_executions && msg.tool_executions.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-slate-800/80 space-y-2">
                        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                          <span>⚡</span>
                          <span>How this was analyzed ({msg.tool_executions.length} tool
                          {msg.tool_executions.length > 1 ? "s" : ""})</span>
                        </div>

                        {msg.tool_executions.map((te: ToolExecutionItem) => {
                          const isExpanded = !!expandedTools[te.id];
                          return (
                            <div
                              key={te.id}
                              data-testid={`tool-exec-${te.id}`}
                              className="rounded-lg border border-slate-800 bg-slate-900/90 p-2.5 text-xs text-slate-300 shadow-sm"
                            >
                              <div
                                onClick={() => toggleToolExpanded(te.id)}
                                className="flex items-center justify-between cursor-pointer select-none hover:text-white transition-colors"
                              >
                                <div className="flex items-center gap-2">
                                  <span className="font-mono font-semibold text-blue-400">
                                    {te.tool_name}
                                  </span>
                                  <span
                                    className={`px-1.5 py-0.5 text-[10px] rounded font-medium ${
                                      te.status === "completed"
                                        ? "bg-emerald-950 text-emerald-300 border border-emerald-800/60"
                                        : "bg-red-950 text-red-300 border border-red-800/60"
                                    }`}
                                  >
                                    {te.status}
                                  </span>
                                </div>
                                <div className="flex items-center gap-2 text-slate-400 text-[11px]">
                                  <span>{formatToolDuration(te.duration_ms)}</span>
                                  <span>{isExpanded ? "▲" : "▼"}</span>
                                </div>
                              </div>

                              {/* Accordion detail */}
                              {isExpanded && (
                                <div className="mt-2.5 pt-2 border-t border-slate-800 text-[11px] space-y-2">
                                  <div>
                                    <span className="text-slate-400">Input Arguments:</span>
                                    <pre className="mt-1 p-2 bg-slate-950/90 rounded border border-slate-800 font-mono text-[10px] overflow-x-auto text-slate-300">
                                      {JSON.stringify(te.arguments, null, 2)}
                                    </pre>
                                  </div>

                                  {te.evidence_refs && te.evidence_refs.length > 0 && (
                                    <div>
                                      <span className="text-slate-400">Evidence Citations:</span>
                                      <div className="flex flex-wrap gap-1.5 mt-1">
                                        {te.evidence_refs.map((ev, i) => (
                                          <span
                                            key={i}
                                            data-testid="evidence-badge"
                                            className="px-2 py-0.5 rounded bg-blue-950/80 text-blue-300 font-mono text-[10px] border border-blue-800"
                                          >
                                            {formatEvidenceCitation(ev)}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="h-8 w-8 rounded-lg bg-slate-700 text-white flex items-center justify-center font-bold text-xs shrink-0 shadow-md">
                      You
                    </div>
                  )}
                </div>
              );
            })
          )}

          {isSending && (
            <div className="flex gap-3 items-center text-xs text-blue-400 animate-pulse pl-12">
              <span className="h-2 w-2 rounded-full bg-blue-500 animate-ping" />
              <span>Analyzing schedule with deterministic domain tools...</span>
            </div>
          )}
        </div>

        {/* Question Starter Chips */}
        <div className="px-6 py-2.5 border-t border-slate-800/80 flex gap-2 overflow-x-auto bg-slate-950/40">
          {QUESTION_STARTERS.map((q, idx) => (
            <button
              key={idx}
              onClick={() => handleSendMessage(q)}
              disabled={isSending}
              data-testid={`starter-chip-${idx}`}
              className="px-3.5 py-1.5 rounded-full text-xs bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 hover:text-white whitespace-nowrap transition-colors border border-slate-700/70 disabled:opacity-50 shadow-sm"
            >
              {q}
            </button>
          ))}
        </div>

        {/* Chat Composer */}
        <footer className="p-4 border-t border-slate-800/80 bg-slate-950/60 backdrop-blur-md">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleSendMessage();
            }}
            className="flex gap-3"
          >
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Ask about critical activities, float, quality, or comparisons..."
              disabled={isSending}
              data-testid="chat-input"
              className="flex-1 rounded-xl px-4 py-2.5 text-sm bg-slate-950/80 border border-slate-700/80 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/80 focus:border-blue-500 disabled:opacity-50 shadow-inner"
            />
            <button
              type="submit"
              disabled={!inputMessage.trim() || isSending}
              data-testid="send-message-button"
              className="px-5 py-2.5 rounded-xl font-medium text-sm bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isSending ? "Analyzing..." : "Send"}
            </button>
          </form>
        </footer>
      </section>
    </div>
  );
}

function renderValidationBadge(msg: MessageItem) {
  // Infer status from content caveats or default to verified
  let status: ValidationStatus = "verified";
  if (msg.content?.includes("[Audit Caveat]")) {
    status = "caveated";
  } else if (msg.content?.includes("could not be found") || msg.content?.includes("INSUFFICIENT_DATA")) {
    status = "insufficient_data";
  }

  const badge = VALIDATION_BADGE_CONFIG[status];
  return (
    <span
      data-testid="validation-badge"
      className={`px-2 py-0.5 text-[10px] font-semibold rounded-full border flex items-center gap-1.5 ${badge.badgeClass}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${badge.dotClass}`} />
      {badge.label}
    </span>
  );
}
