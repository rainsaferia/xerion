# Security Hardening & Entity Lifecycle Specification (PI-051)

## 1. Multi-Tenant Isolation

### 1.1 Core Principles
- **Fail-Closed Membership Authorization**: Access to any project or workspace resource is strictly derived from the authenticated user's active membership in the parent workspace (`WorkspaceMember.status == 'active'`).
- **No Data Leakage / 404 Indistinguishability**: A resource belonging to another tenant returns `404 NOT_FOUND` with error code `NOT_FOUND`, identical to the response for a nonexistent UUID. This completely prevents tenant resource enumeration and UUID probing attacks.
- **Symmetric Isolation**: Isolation is enforced bidirectionally across all tenants, workspaces, and sub-resources (projects, project versions, activities, findings, reports, upload sessions, and AI conversations).

---

## 2. Upload Abuse Protection

### 2.1 Filename Sanitization (`sanitize_upload_filename`)
- **Directory Traversal Defense**: All forward slashes (`/`), backslashes (`\`), and relative path tokens (`..`) are stripped, extracting only the canonical basename.
- **Hidden File Block**: Filenames beginning with `.` (e.g., `.env`, `.bashrc`) are strictly rejected.
- **Device Name Protection**: Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) are rejected before extension validation.
- **Character Filtering**: Control characters (`ord < 32` or `ord == 127`) and binary null bytes (`\x00`) are eliminated.
- **Length Bounds**: Enforced between 1 and 255 characters.

### 2.2 Magic Bytes & File Signature Inspection (`verify_file_signature`)
- **Primavera P6 XER**: Must begin with `ERMHDR` or UTF-8 BOM `\xef\xbb\xbfERMHDR`. Executables or foreign formats disguised as `.xer` are rejected.
- **Microsoft Excel XLSX**: Must begin with ZIP signature `PK\x03\x04`. Plaintext or script files disguised as `.xlsx` are rejected.
- **CSV Data**: Content inspection checks the first 8 KB for binary null bytes (`\x00`) to prevent binary payload masquerading. Must be valid UTF-8 or Latin-1 text.

### 2.3 Quota and Upload Size Limits
- Every upload session checks file size against:
  1. Server maximum upload threshold (`Settings.upload_max_size_bytes`).
  2. Workspace plan definition quota (`PlanQuotas.max_upload_size_bytes`).
- Monthly file upload counters are recorded via `UsageEvent` and capped per subscription plan (`PlanQuotas.max_file_uploads_per_month`).

---

## 3. Storage Security & Download Token Lifecycle

### 3.1 Sandboxed Local Storage (`LocalStorageAdapter`)
- Private object storage keys are strictly resolved relative to the configured base storage directory (`_resolve_path`).
- Paths attempting to traverse out of the sandbox boundary (e.g. `../../etc/passwd` or absolute drive roots) immediately trigger `ValueError("Path traversal detected")`.

### 3.2 Short-Lived Signed JWT Download Tokens
- Downloads of reports and exports can use short-lived, signed JWT tokens (`scope: "report_download"`) generated via `create_report_download_token`:
  - **Expiry**: Default lifetime of 15 minutes (`exp` claim verified against clock).
  - **Integrity**: Signed with HMAC-SHA256 using the server's authentication secret.
  - **Scope Bounding**: Scoped download tokens are rejected if used to access general API endpoints (e.g., `/projects`, `/workspaces`).
  - **Entity Binding**: The token payload contains `report_id`. Attempting to use a token minted for Report A on Report B returns `403 FORBIDDEN`.

### 3.3 Download Security Headers
All file and report download responses include strict HTTP security headers:
- `Content-Disposition: attachment; filename="{safe_filename}"`
- `X-Content-Type-Options: nosniff` (prevents MIME confusion and script execution)
- `X-Frame-Options: DENY` (prevents clickjacking and framing)
- `Cache-Control: private, no-store, max-age=0` (prevents intermediate and browser caching of sensitive project data)
- `Pragma: no-cache`

---

## 4. Deletion Lifecycle & Cascades

### 4.1 Uploaded File Deletion (`DELETE /api/v1/uploads/{file_id}`)
- Soft-deletes `UploadedFile.deleted_at = datetime.now(UTC)`.
- Purges the binary file from object storage (`await storage.delete_object(file.object_key)`).
- Subsequent access returns `404 NOT_FOUND`.

### 4.2 Project Deletion (`DELETE /api/v1/projects/{project_id}`)
- Soft-deletes `Project.deleted_at = datetime.now(UTC)`.
- **Storage Cascade**: Finds all active `UploadedFile` records for the project, soft-deletes them, and permanently deletes their physical objects from storage.
- **Report Cascade**: Purges all generated report artifacts (`Report.object_key`) associated with the project.
- Subsequent access to the project or any child resource returns `404 NOT_FOUND`.

### 4.3 Account Deactivation (`DELETE /api/v1/me`)
- Sets `User.deleted_at = datetime.now(UTC)`.
- Sets all user's active workspace memberships to `status = "suspended"`.
- The user session is immediately invalidated; subsequent requests fail closed with `401 UNAUTHENTICATED` ("Account is deactivated.").

---

## 5. Automated CI Security Scanning

The CI pipeline (`.github/workflows/ci.yml`) enforces continuous security verification:
1. **Secrets Detection**: `gitleaks-action@v2` scans full git history on push and PR to prevent credential leakage.
2. **Python Dependencies**: `pip-audit` checks all backend packages against known CVEs.
3. **Frontend Dependencies**: `npm audit --audit-level=high` ensures no high or critical vulnerabilities exist in node packages.

