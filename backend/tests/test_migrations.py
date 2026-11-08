"""Test Alembic migrations (upgrade and downgrade scripts)."""

from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config


def test_alembic_upgrade_and_downgrade_offline(capsys: pytest.CaptureFixture[str]) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))

    # Test upgrade --sql emits non-empty SQL to stdout
    upgrade(cfg, "head", sql=True)
    captured = capsys.readouterr()
    assert "CREATE TABLE users" in captured.out
    assert "CREATE TABLE projects" in captured.out
    assert "CREATE TABLE activities" in captured.out
    assert "0001_initial_schema" in captured.out

    # Test downgrade --sql emits non-empty SQL to stdout
    downgrade(cfg, "0001_initial_schema:base", sql=True)
    captured_down = capsys.readouterr()
    assert "DROP TABLE activities" in captured_down.out
    assert "DROP TABLE projects" in captured_down.out
    assert "DROP TABLE users" in captured_down.out
