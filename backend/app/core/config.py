"""Application settings, loaded from environment variables (never hardcode secrets)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PI_", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    app_version: str = "0.1.0"

    # Dependency URLs. Local defaults match docker-compose.yml (dev-only credentials).
    database_url: str = "postgresql://pi_dev:pi_dev_password@localhost:5432/project_intelligence"
    redis_url: str = "redis://localhost:6379/0"

    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    cors_origins: list[str] = ["http://localhost:3000"]

    # Auth: bearer JWT verification. No secret is committed; when unset, every protected
    # route fails closed with 401. Provider-specific verifiers (e.g. JWKS) can replace this
    # behind app.core.auth.verify_access_token without touching routes.
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None

    # Object storage & file upload limits (PI-012)
    storage_backend: str = "local"
    storage_local_dir: str = ".data/storage"
    upload_max_size_bytes: int = Field(default=100 * 1024 * 1024, gt=0)  # 100MB default

    # Background queue backend (PI-013): "in_memory" or "redis"
    queue_backend: str = "in_memory"

    # AI Provider configuration (PI-040)
    ai_provider: str = "mock"
    ai_model: str = "gpt-4o"
    ai_api_key: SecretStr | None = None
    ai_base_url: str | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    ai_max_retries: int = Field(default=3, ge=0, le=10)


@lru_cache
def get_settings() -> Settings:
    return Settings()
