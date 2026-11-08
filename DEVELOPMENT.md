# Development Guide

Monorepo layout (modular monolith + separate worker; see `02_SYSTEM_ARCHITECTURE.md`):

```text
backend/    FastAPI + Python (uv). app/{api,core,db,domains,adapters,workers}
frontend/   Next.js App Router + TypeScript (npm)
docker-compose.yml   Local Postgres 16 + Redis 7 (dev-only credentials)
.github/workflows/ci.yml
```

Module boundaries (enforced for `domains/` by `backend/tests/test_architecture.py`):
- `domains/schedule` – deterministic calculations; no parser, AI, or web-framework imports.
- `domains/ingestion`, `domains/ai` – orchestration only.
- `adapters/{p6_xer,llm,storage}` – replaceable edges (parser, LLM provider, object storage).
- The LLM only calls validated backend tools; it never computes schedule numbers.

## Prerequisites
Docker, Node 22+, Python 3.11+ via [uv](https://docs.astral.sh/uv/).

## First run
```bash
cp .env.example .env            # Windows: copy .env.example .env
npm run deps:up                 # starts Postgres + Redis, waits until healthy
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
npm run dev:api                 # http://localhost:8000
npm run dev:web                 # http://localhost:3000
```

Health checks:
- API liveness `GET http://localhost:8000/health`
- API readiness (Postgres + Redis) `GET http://localhost:8000/health/ready` (503 if degraded)
- Frontend `GET http://localhost:3000/api/health`; the home page also shows backend readiness.

## Quality commands (run from repo root)
| Command | Purpose |
|---|---|
| `npm run lint` | ruff check/format-check, ESLint, Prettier check |
| `npm run typecheck` | mypy (strict), `tsc --noEmit` |
| `npm test` | pytest, vitest |
| `npm run check` | all of the above |
| `npm run format` | auto-format both stacks |

CI (`.github/workflows/ci.yml`) runs lint, format check, typecheck, tests, and the frontend build.

## Rules
Never commit `.env`, keys, or real client project files (`*.xer` is git-ignored except under `backend/tests/fixtures`).

