import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  QUESTION_STARTERS,
  VALIDATION_BADGE_CONFIG,
  formatEvidenceCitation,
  formatToolDuration,
  isAssistantMessage,
} from "./ai-assistant-model.ts";

describe("ai-assistant-model", () => {
  it("provides valid badge configuration for all validation statuses", () => {
    assert.equal(VALIDATION_BADGE_CONFIG.verified.label, "Verified Grounded");
    assert(VALIDATION_BADGE_CONFIG.verified.badgeClass.includes("emerald") || VALIDATION_BADGE_CONFIG.verified.badgeClass.includes("green"));

    assert.equal(VALIDATION_BADGE_CONFIG.caveated.label, "Audit Caveat");
    assert(VALIDATION_BADGE_CONFIG.caveated.badgeClass.includes("amber") || VALIDATION_BADGE_CONFIG.caveated.badgeClass.includes("yellow"));

    assert.equal(VALIDATION_BADGE_CONFIG.insufficient_data.label, "Insufficient Data");
    assert(VALIDATION_BADGE_CONFIG.insufficient_data.badgeClass.includes("slate") || VALIDATION_BADGE_CONFIG.insufficient_data.badgeClass.includes("purple"));
  });

  it("provides relevant question starters for EPC projects", () => {
    assert(QUESTION_STARTERS.length >= 4);
    assert(QUESTION_STARTERS.some((q) => q.includes("schedule health")));
    assert(QUESTION_STARTERS.some((q) => q.includes("float")));
  });

  it("formats tool execution duration cleanly", () => {
    assert.equal(formatToolDuration(null), "");
    assert.equal(formatToolDuration(undefined), "");
    assert.equal(formatToolDuration(25), "25ms");
    assert.equal(formatToolDuration(1250), "1.25s");
  });

  it("formats evidence citations from records or labels", () => {
    const refWithLabel = { citation_label: "[EV: A1010 float=0.0h]" };
    assert.equal(formatEvidenceCitation(refWithLabel), "[EV: A1010 float=0.0h]");

    const rawRef = {
      source_identifier: "F200",
      field_name: "total_float_hours",
      normalized_value: 16.0,
      unit: "hours",
    };
    assert.equal(formatEvidenceCitation(rawRef), "[EV: F200 total_float_hours=16h]");
  });

  it("identifies assistant vs user messages correctly", () => {
    assert.equal(isAssistantMessage("assistant"), true);
    assert.equal(isAssistantMessage("user"), false);
    assert.equal(isAssistantMessage("system"), false);
  });
});

