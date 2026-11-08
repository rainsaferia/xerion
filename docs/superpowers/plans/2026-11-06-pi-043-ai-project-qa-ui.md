# PI-043 — AI Project Q&A UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the AI Assistant Q&A UI for project schedules, providing project-scoped conversation history, active schedule version visibility, transparent tool execution inspection ("How this was analyzed"), and interactive evidence reference badges.

**Architecture:**
- Create pure model helpers in `frontend/src/lib/ai-assistant-model.ts` for validation badges, question starters, and evidence formatting.
- Create interactive client component in `frontend/src/components/ai-assistant-view.tsx` with sidebar conversation list, active version banner, chat stream with tool activity accordions and evidence badges, and message composer with question starter chips.
- Create dynamic App Router page in `frontend/src/app/projects/[id]/ai/page.tsx`.
- Test model logic in `frontend/src/lib/ai-assistant-model.test.ts`.

---

## Global Constraints

- **Project Scoping:** All conversations and message turns must strictly be bound to the active `projectId`.
- **Version Transparency:** Always show which schedule version and data date the AI analyzed.
- **Evidence Inspection:** Every assistant claim must show its validation status badge, tools executed, and clickable evidence tags.
- **Responsive & Professional:** Dark navy / slate styling conforming to `07_UI_UX_SPEC.md` for project controls professionals.

---

### Task 1: UI Model & Helper Functions

**Files:**
- Create: `frontend/src/lib/ai-assistant-model.ts`
- Create: `frontend/src/lib/ai-assistant-model.test.ts`

**Interfaces:**
- Produces: `VALIDATION_BADGE_CONFIG`, `QUESTION_STARTERS`, `formatToolDuration()`, `formatEvidenceCitation()`, `groupMessagesByTurn()`.

- [ ] **Step 1: Write unit tests in `ai-assistant-model.test.ts`**
  - Test validation badge configuration for `verified`, `caveated`, `insufficient_data`.
  - Test duration formatting (ms to readable seconds or ms).
  - Test evidence citation parsing and display formatting.
  - Test question starter suggestions list.
- [ ] **Step 2: Implement `frontend/src/lib/ai-assistant-model.ts`**
  - Implement badge configurations and formatting utilities.
- [ ] **Step 3: Run unit tests**
  - `npm --prefix frontend test`

---

### Task 2: React Interactive Component

**Files:**
- Create: `frontend/src/components/ai-assistant-view.tsx`

**Interfaces:**
- Props: `projectId: string`, `initialConversations?: ConversationResponse[]`, `activeVersionLabel?: string`, `dataDate?: string`, `token?: string`.

- [ ] **Step 1: Implement `AiAssistantView`**
  - Sidebar: conversation list, new conversation button, active selection.
  - Context Header: project title, active version badge (`v1`, `v2`, data date).
  - Message Stream: user bubbles, assistant bubbles with validation status badges.
  - Tool Activity Inspector: collapsible accordion showing tools executed, parameters, status, and duration.
  - Evidence Reference Badges: pill tags showing `[EV: ...]`, field name, and verified values.
  - Chat Composer: input field, send button, disabled while awaiting agent turn, quick question starter chips.
  - Error and loading state management.

---

### Task 3: App Router Page

**Files:**
- Create: `frontend/src/app/projects/[id]/ai/page.tsx`

- [x] **Step 1: Implement `page.tsx`**
  - Reads `params.id` (projectId).
  - Renders `AiAssistantView` with project context.

---

### Task 4: Full Monorepo Verification

- [x] **Step 1: Run frontend tests**
  - `npm --prefix frontend test`
- [x] **Step 2: Run full monorepo check**
  - `npm run check` (pytest, ruff, mypy, eslint, tsc).
- [x] **Step 3: Run Next.js production build**
  - `npm --prefix frontend run build`.
