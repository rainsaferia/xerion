# Prompt awal untuk Claude Code

Copy prompt di bawah ini setelah membuka folder/repository project di Claude Code.

---

Baca dan ikuti seluruh instruksi pada `CLAUDE.md`. Sebelum coding, baca dokumen product blueprint di folder ini, terutama PRD, system architecture, data model, database schema, dan development backlog.

Saya ingin membangun Project Intelligence Platform: individual-first multi-tenant SaaS untuk profesional EPC yang mengunggah Primavera P6 XER dan Excel/CSV, lalu menggunakan deterministic analytics dan AI tools untuk Analyze, Predict, dan Act.

Untuk sesi pertama, kerjakan **Sprint 0 / PI-001 saja**. Jangan membangun seluruh produk sekaligus.

Langkah kerja:
1. Periksa struktur repository dan kode yang sudah ada. Jangan menghapus atau menimpa file tanpa memahami fungsinya.
2. Bandingkan kondisi repo dengan product blueprint.
3. Usulkan struktur monorepo frontend Next.js + TypeScript dan backend FastAPI + Python, serta local development dependencies PostgreSQL dan Redis.
4. Implementasikan fondasi minimum: environment example, lint/format/typecheck/test commands, health checks, Docker Compose local dependencies, dan CI.
5. Jangan memasukkan secret atau data proyek klien.
6. Jalankan semua checks yang tersedia.
7. Laporkan file yang dibuat/diubah, hasil test, asumsi, dan risiko yang belum terselesaikan.
8. Jangan mulai PI-002 atau sprint berikutnya sebelum saya review hasil PI-001.

Penting: keputusan teknis harus tetap modular. XER parsing, canonical data model, calculation engine, AI orchestration, dan provider adapters nantinya harus terpisah. AI tidak boleh menghitung angka schedule secara bebas; AI hanya memanggil backend tools yang tervalidasi.

Mulai dengan inspeksi repository dan rencana implementasi PI-001. Setelah rencana singkat, kerjakan PI-001.

---
