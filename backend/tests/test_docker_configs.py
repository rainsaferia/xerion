"""Tests for production deployment containerization and worker configurations (PI-053 Task 1)."""

from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent


def test_backend_dockerfile_structure() -> None:
    dockerfile_path = ROOT_DIR / "backend" / "Dockerfile"
    assert dockerfile_path.exists(), "backend/Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "FROM python:" in content
    assert "useradd" in content or "adduser" in content, "Must create an unprivileged non-root user"
    assert "USER " in content, "Must switch to non-root user"
    assert "uv" in content, "Must use UV package manager"
    assert "CMD [" in content or "ENTRYPOINT [" in content


def test_frontend_dockerfile_structure() -> None:
    dockerfile_path = ROOT_DIR / "frontend" / "Dockerfile"
    assert dockerfile_path.exists(), "frontend/Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "FROM node:" in content
    assert "USER " in content, "Must switch to non-root user"
    assert "CMD [" in content or "ENTRYPOINT [" in content


def test_docker_compose_prod_topology() -> None:
    compose_path = ROOT_DIR / "docker-compose.prod.yml"
    assert compose_path.exists(), "docker-compose.prod.yml must exist"
    content = compose_path.read_text(encoding="utf-8")

    required_services = ["api:", "worker:", "web:", "postgres:", "redis:"]
    for s in required_services:
        assert s in content, f"Service {s} must be defined in docker-compose.prod.yml"

    assert "healthcheck:" in content, "Production compose must define healthchecks"


def test_worker_main_runnable() -> None:
    worker_main_path = ROOT_DIR / "backend" / "app" / "workers" / "main.py"
    assert worker_main_path.exists()
    content = worker_main_path.read_text(encoding="utf-8")

    assert "run_worker_daemon" in content or "process_next_job" in content
    assert "SIGTERM" in content or "signal" in content, (
        "Worker daemon must handle graceful shutdown signals"
    )
