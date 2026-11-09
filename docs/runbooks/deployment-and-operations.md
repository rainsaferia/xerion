# Production Deployment and Operations Runbook

## 1. System Topology & Architecture

The Project Intelligence Platform runs as a containerized stack managed via [`docker-compose.prod.yml`](file:///e:/Project/project%20intelligence%20v1/docker-compose.prod.yml):

- **Next.js Web Frontend (`web`)**: Reverse-proxied React UI on port `3000`.
- **FastAPI Core API (`api`)**: Asynchronous REST backend on port `8000`.
- **Background Worker (`worker`)**: Daemon process polling Redis queue for asynchronous schedule imports.
- **PostgreSQL 16 (`postgres`)**: Relational database storing multi-tenant entities, project versions, canonical activities, and audit logs.
- **Redis 7 (`redis`)**: In-memory job queue for import tasks and usage event rate limiting.
- **Private Object Storage Volume (`private_storage`)**: Private container filesystem mount for original schedule files (`.xer`, `.xlsx`) and generated PDF reports.

---

## 2. Environment Configuration Reference

Create `.env.prod` with the required production variables:

```bash
# PostgreSQL
POSTGRES_USER=pi_prod_user
POSTGRES_PASSWORD=<strong_random_database_password>
POSTGRES_DB=project_intelligence_prod

# Redis
REDIS_PASSWORD=<strong_random_redis_password>

# Application Security
JWT_SECRET=<min_32_character_cryptographic_secret>
APP_ENV=production
LOG_LEVEL=INFO

# Storage
STORAGE_BACKEND=local
STORAGE_LOCAL_DIR=/app/storage
UPLOAD_MAX_BYTES=52428800

# Next.js Public
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

---

## 3. Deployment Procedure

### Initial Deployment:
1. Clone the repository and configure `.env.prod`.
2. Launch the services:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
   ```
3. Run Alembic migrations to initialize or upgrade the database:
   ```bash
   docker compose -f docker-compose.prod.yml exec api uv run alembic upgrade head
   ```

### Rolling Update:
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --no-deps --build api worker web
```

---

## 4. Health Checks & Observability

### Endpoints:
- **Liveness:** `GET /health` (Returns 200 `{"status": "ok"}`)
- **Readiness:** `GET /health/ready` (Probes active PostgreSQL and Redis connections; returns 200 `{"status": "ok"}` or 503 `{"status": "degraded"}`).

### Monitoring Probes:
```bash
# API readiness check
curl -f http://localhost:8000/health/ready

# Frontend health probe
curl -f http://localhost:3000/api/health
```

### Structured Logs:
Logs are streamed in structured JSON. Stream live logs via:
```bash
# API logs
docker compose -f docker-compose.prod.yml logs -f api

# Worker import logs
docker compose -f docker-compose.prod.yml logs -f worker
```

