import pytest
from app.api.health import get_probes
from app.core.config import Settings
from app.core.health import Probe
from app.main import app
from fastapi.testclient import TestClient


async def _ok(_: Settings) -> None:
    return None


async def _fail(_: Settings) -> None:
    raise ConnectionError("down")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _override(probes: dict[str, Probe]) -> None:
    app.dependency_overrides[get_probes] = lambda: probes


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_liveness(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_ok(client: TestClient) -> None:
    _override({"postgres": _ok, "redis": _ok})
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


def test_readiness_degraded_hides_error_details(client: TestClient) -> None:
    _override({"postgres": _ok, "redis": _fail})
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "unavailable"
    assert "down" not in r.text


def test_request_id_generated_and_echoed(client: TestClient) -> None:
    assert client.get("/health").headers["X-Request-ID"].startswith("req_")
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_unsafe_request_id_replaced(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["X-Request-ID"].startswith("req_")


def test_error_envelope_for_unknown_route(client: TestClient) -> None:
    r = client.get("/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert err["request_id"] == r.headers["X-Request-ID"]
