"""Tests for operational runbook completeness and integrity (PI-053 Task 3)."""

from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
RUNBOOKS_DIR = ROOT_DIR / "docs" / "runbooks"


def test_required_runbooks_exist() -> None:
    expected_runbooks = [
        "deployment-and-operations.md",
        "database-backup-and-disaster-recovery.md",
        "import-failure-triage.md",
        "ai-provider-outage-and-fallback.md",
    ]
    for r in expected_runbooks:
        path = RUNBOOKS_DIR / r
        assert path.exists(), f"Runbook {r} must exist in docs/runbooks/"


def test_runbook_content_requirements() -> None:
    deploy_doc = (RUNBOOKS_DIR / "deployment-and-operations.md").read_text(encoding="utf-8")
    assert "/health" in deploy_doc
    assert "/health/ready" in deploy_doc
    assert "docker-compose.prod.yml" in deploy_doc

    db_doc = (RUNBOOKS_DIR / "database-backup-and-disaster-recovery.md").read_text(encoding="utf-8")
    assert "pg_dump" in db_doc
    assert "pg_restore" in db_doc
    assert "backup.py" in db_doc
    assert "restore.py" in db_doc

    import_doc = (RUNBOOKS_DIR / "import-failure-triage.md").read_text(encoding="utf-8")
    assert "XER" in import_doc
    assert (
        "CORRUPT" in import_doc
        or "UNSUPPORTED" in import_doc
        or "UPLOADED_FILE_NOT_FOUND" in import_doc
    )
    assert "preview_ready" in import_doc

    ai_doc = (RUNBOOKS_DIR / "ai-provider-outage-and-fallback.md").read_text(encoding="utf-8")
    assert "MockAIProviderAdapter" in ai_doc or "fallback" in ai_doc
    assert "RateLimitError" in ai_doc or "circuit" in ai_doc or "timeout" in ai_doc
