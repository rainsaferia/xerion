# Project Intelligence Platform — Blueprint v1.0

Dokumen kerja untuk membangun MVP AI Project Intelligence Workspace yang menyasar profesional individual di industri EPC, Oil & Gas, dan industrial projects.

## Product direction

**Positioning:** An AI-powered project intelligence workspace for EPC professionals.

**Promise:** Upload your project data. Understand what's happening. Predict what comes next. Decide what to do.

**MVP focus:** Primavera P6 XER + Excel/CSV ingestion, versioned project data, deterministic schedule analytics, evidence-based AI assistant, transparent schedule forecast/scenario analysis, and exportable reports.

## Isi paket

| File | Isi |
|---|---|
| `01_PRD.md` | Product requirements, personas, scope, user stories, acceptance criteria, metrics |
| `02_SYSTEM_ARCHITECTURE.md` | Architecture, ingestion pipeline, security, AI integration, deployment |
| `03_DATA_MODEL.md` | Domain model, entity relationships, versioning, canonical field mapping |
| `04_DATABASE_SCHEMA.sql` | PostgreSQL starter schema |
| `05_AI_AGENT_SPEC.md` | Agent workflow, tool catalog, evidence contract, safety and approval rules |
| `06_API_SPEC.md` | REST API contract untuk frontend/backend |
| `07_UI_UX_SPEC.md` | Navigation, screen requirements, states, interaction patterns |
| `08_DEVELOPMENT_BACKLOG.md` | Epic, sprint backlog, acceptance criteria, definition of done |
| `CLAUDE.md` | Instruksi kerja untuk Claude Code |

## Urutan implementasi

1. Baca `CLAUDE.md` dan `01_PRD.md`.
2. Validasi `02_SYSTEM_ARCHITECTURE.md` dan `03_DATA_MODEL.md`.
3. Terapkan `04_DATABASE_SCHEMA.sql` sebagai baseline migration, lalu pindahkan ke Alembic migrations.
4. Kerjakan backlog berurutan dalam `08_DEVELOPMENT_BACKLOG.md`.
5. Bangun parser XER dengan test fixtures yang berasal dari file ekspor P6 yang sah dan sudah disanitasi.
6. Jangan mulai AI assistant sebelum deterministic analytics dan evidence contract memiliki test.

## Scope guardrails

- v1 tidak menulis balik atau mengubah file/project Primavera sumber.
- v1 tidak melakukan auto-scheduling atau auto-recovery pada sistem P6 pengguna.
- v1 tidak mengklaim machine-learning prediction yang belum divalidasi.
- v1 tidak mendukung semua variasi template Excel secara otomatis; gunakan mapping wizard.
- Semua hasil perhitungan harus traceable ke project version, data date, input, dan metode.

## Catatan implementasi

Dokumen ini adalah product/engineering baseline, bukan final legal, security, atau compliance certification. Sebelum production, lakukan security review, privacy review, load testing, dan uji import menggunakan beragam file P6 yang representatif.
