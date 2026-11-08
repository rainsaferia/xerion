/**
 * UI State and Formatting Model for AI Assistant Q&A (PI-043).
 *
 * Rules (07_UI_UX_SPEC.md Screen H, 05_AI_AGENT_SPEC.md):
 * - Clean, professional EPC project controls styling.
 * - Validation badge configuration matching PI-042 verification statuses.
 * - Evidence citation and tool execution formatting.
 */

import type { ValidationStatus } from "./api-client.ts";

export interface ValidationBadgeMeta {
  label: string;
  badgeClass: string;
  dotClass: string;
}

export const VALIDATION_BADGE_CONFIG: Record<ValidationStatus, ValidationBadgeMeta> = {
  verified: {
    label: "Verified Grounded",
    badgeClass: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
    dotClass: "bg-emerald-500",
  },
  caveated: {
    label: "Audit Caveat",
    badgeClass: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800",
    dotClass: "bg-amber-500",
  },
  insufficient_data: {
    label: "Insufficient Data",
    badgeClass: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
    dotClass: "bg-slate-400",
  },
};

export const QUESTION_STARTERS: string[] = [
  "Summarize current schedule health.",
  "Which activities have the lowest float?",
  "Run schedule quality audit checks.",
  "What changed since the previous version?",
  "Are there any open ends or missing successors?",
];

export function formatToolDuration(ms?: number | null): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${Number((ms / 1000).toFixed(2))}s`;
}

export function formatEvidenceCitation(ref: Record<string, unknown>): string {
  if (typeof ref.citation_label === "string" && ref.citation_label.trim()) {
    return ref.citation_label;
  }
  const id = ref.source_identifier || ref.entity_type || "item";
  const field = ref.field_name || "value";
  const val = ref.normalized_value !== undefined ? ref.normalized_value : ref.source_value;
  const unitSuffix = ref.unit === "hours" ? "h" : ref.unit === "days" ? "d" : "";
  return `[EV: ${id} ${field}=${val}${unitSuffix}]`;
}

export function isAssistantMessage(role: string): boolean {
  return role === "assistant";
}

