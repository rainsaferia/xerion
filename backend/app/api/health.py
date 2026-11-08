from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.health import Probe, check_postgres, check_redis, run_probe

router = APIRouter(tags=["health"])


class LiveResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


def get_probes() -> dict[str, Probe]:
    return {"postgres": check_postgres, "redis": check_redis}


@router.get("/health", response_model=LiveResponse)
async def liveness(settings: Annotated[Settings, Depends(get_settings)]) -> LiveResponse:
    """Liveness: process is up. Does not touch dependencies."""
    return LiveResponse(status="ok", version=settings.app_version)


@router.get("/health/ready", response_model=ReadyResponse)
async def readiness(
    settings: Annotated[Settings, Depends(get_settings)],
    probes: Annotated[dict[str, Probe], Depends(get_probes)],
) -> JSONResponse:
    """Readiness: Postgres and Redis reachable. Returns 503 if any dependency is down."""
    results = [await run_probe(name, probe, settings) for name, probe in probes.items()]
    checks = {name: ("ok" if ok else "unavailable") for name, ok in results}
    healthy = all(ok for _, ok in results)
    body = ReadyResponse(status="ok" if healthy else "degraded", checks=checks)
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump())
