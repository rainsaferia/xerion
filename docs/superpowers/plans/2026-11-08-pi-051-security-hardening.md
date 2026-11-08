# Implementation Plan: PI-051 Security Hardening (Sprint 5)

## Overview
Hardens the platform's multi-tenant isolation, file upload defenses, private storage access controls, CI security scanning, and resource deletion lifecycles according to `01_PRD.md`, `02_SYSTEM_ARCHITECTURE.md` (Section 10), and `08_DEVELOPMENT_BACKLOG.md` (PI-051).

---

## Acceptance Criteria
1. **Cross-tenant automated tests pass:**
   - Exhaustive coverage of all workspace entities (workspaces, projects, versions, activities, findings, reports, conversations, messages, files, import jobs, mapping profiles, usage summaries).
   - Any cross-tenant access attempt returns `404 NOT_FOUND` (indistinguishable from nonexistent ID).
2. **Upload abuse limits configured:**
   - Filename sanitization strictly preventing directory traversal (`..`, `/`, `\`), null bytes, control characters, hidden files, and device names.
   - Extension whitelisting (`.xer`, `.xlsx`, `.csv`).
   - Magic bytes verification (`ERMHDR` for XER, `PK\x03\x04` for XLSX, null-byte-free text for CSV).
   - File size limits enforced against server settings and workspace plan limits.
   - MIME sniffing defense headers on content downloads (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: private, no-store`).
3. **Private storage and signed URL expiry verified:**
   - `LocalStorageAdapter` path traversal boundary verified.
   - Signed download tokens verified for expiration, signature tampering, token scope restrictions, and cross-report binding.
4. **Secrets scan and dependency scan run in CI:**
   - `pip-audit` added for backend dependency vulnerability scanning.
   - `npm audit --audit-level=high` added for frontend.
   - `gitleaks` step added to `.github/workflows/ci.yml`.
5. **Project, file, and account deletion behavior documented and tested:**
   - `DELETE /api/v1/projects/{project_id}` implemented (soft delete, cascade storage cleanup, subsequent 404).
   - `DELETE /api/v1/uploads/{file_id}` verified (soft delete + physical file deletion).
   - `DELETE /api/v1/me` implemented (user account deactivation, subsequent 401).
   - Comprehensive documentation in `docs/architecture/security-and-lifecycle.md`.

---

## Tasks Breakdown

### Task 1: Upload Abuse Controls & Download Security Headers
- Add `sanitize_upload_filename(filename: str) -> str` in `backend/app/domains/ingestion/safety.py`.
- Update `create_upload_session` and `upload_file_content` in `backend/app/api/v1/routes.py` to enforce sanitized filenames.
- Add security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: private, no-store, max-age=0`, `Pragma: no-cache`) to file and report download responses.
- Implement tests in `backend/tests/test_upload_security.py`.

### Task 2: Storage Security & Signed URL Expiry Verification
- Add scope bounding in `backend/app/core/auth.py` / `deps.py` to prevent scoped download tokens (`scope: "report_download"`) from authenticating general API endpoints.
- Implement tests in `backend/tests/test_storage_security.py`:
  - Path traversal attempts against `LocalStorageAdapter`.
  - Expired signed download tokens rejected.
  - Tampered signatures rejected.
  - Cross-report token reuse rejected with 403.
  - Scoped download tokens rejected for general API routes.

### Task 3: Deep Cross-Tenant Automated Test Suite
- Implement `backend/tests/test_cross_tenant_deep.py` testing cross-tenant boundaries across:
  - Projects, project versions, activities, schedule quality checks, delay scenarios, milestone forecasts.
  - Reports, download URLs, report content, activity exports.
  - Uploaded files, content upload, complete upload, import jobs, import previews, import confirms.
  - AI conversations, chat messages.
  - Mapping profiles, usage summaries.
  - Asserting all return 404 and leak no data.

### Task 4: Project and Account Deletion Endpoints & Lifecycle Tests
- Add `DELETE /api/v1/projects/{project_id}` in `backend/app/api/v1/routes.py`:
  - Soft-deletes `Project.deleted_at = datetime.now(UTC)`.
  - Cascades soft-deletion to uploaded files and removes underlying files from storage.
- Add `DELETE /api/v1/me` in `backend/app/api/v1/routes.py`:
  - Sets `user.deleted_at = datetime.now(UTC)` and marks user's workspace memberships deactivated.
- Implement tests in `backend/tests/test_lifecycle_deletion.py`.

### Task 5: CI Security Scanning, Documentation & Monorepo Verification
- Add `pip-audit>=2.8.0` to `backend/pyproject.toml` (dev dependencies).
- Update `.github/workflows/ci.yml` with secrets scan (`gitleaks`) and dependency scans (`pip-audit`, `npm audit`).
- Create `docs/architecture/security-and-lifecycle.md`.
- Run full monorepo check: `npm run check` (pytest, node tests, ruff, mypy, eslint, tsc) and `npm --prefix frontend run build`.

