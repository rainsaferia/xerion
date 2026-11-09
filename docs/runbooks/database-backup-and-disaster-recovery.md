# Database Backup & Disaster Recovery Runbook

## 1. Overview & Objectives

This runbook outlines the standard operating procedures for point-in-time database backups, private storage snapshots, and disaster recovery restoration for the Project Intelligence Platform.

---

## 2. Backup Procedures

### Automated Script Backup
Use [`scripts/backup.py`](file:///e:/Project/project%20intelligence%20v1/scripts/backup.py):

```bash
# 1. Backup Private Storage (Compressed .tar.gz)
python scripts/backup.py \
  --storage-dir /var/lib/docker/volumes/private_storage/_data \
  --storage-out /backups/storage/storage_$(date +%Y%m%d_%H%M%S).tar.gz

# 2. Backup PostgreSQL Database (Custom compressed pg_dump)
python scripts/backup.py \
  --db-url "postgresql://pi_prod_user:${POSTGRES_PASSWORD}@localhost:5432/project_intelligence_prod" \
  --db-out /backups/postgres/db_$(date +%Y%m%d_%H%M%S).dump
```

### Manual pg_dump
```bash
pg_dump -U pi_prod_user -h localhost -d project_intelligence_prod -Fc -f db_backup.dump
```

---

## 3. Disaster Recovery Restoration

In the event of database corruption, accidental deletion, or server disaster:

### Step 1: Drain Traffic and Stop Workers
```bash
docker compose -f docker-compose.prod.yml stop api worker
```

### Step 2: Restore Database
Use [`scripts/restore.py`](file:///e:/Project/project%20intelligence%20v1/scripts/restore.py) or `pg_restore`:

```bash
# Using restore utility
python scripts/restore.py \
  --db-url "postgresql://pi_prod_user:${POSTGRES_PASSWORD}@localhost:5432/project_intelligence_prod" \
  --db-backup /backups/postgres/db_20261108_210000.dump

# Or using native pg_restore CLI
pg_restore -U pi_prod_user -h localhost -d project_intelligence_prod --clean --if-exists /backups/postgres/db_20261108_210000.dump
```

### Step 3: Restore Private Storage
```bash
python scripts/restore.py \
  --storage-archive /backups/storage/storage_20261108_210000.tar.gz \
  --storage-dest /var/lib/docker/volumes/private_storage/_data
```

### Step 4: Verify Data & Re-enable Services
1. Run database sanity checks and Alembic status:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm api uv run alembic current
   ```
2. Start all services and verify health endpoints:
   ```bash
   docker compose -f docker-compose.prod.yml up -d api worker
   curl -f http://localhost:8000/health/ready
   ```

