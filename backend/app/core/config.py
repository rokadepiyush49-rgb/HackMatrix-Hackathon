"""Runtime configuration, read from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_prefix="SUTRA_", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://localhost:5432/sutra"

    jwt_secret: str = "change-me-local-dev-only"
    jwt_access_minutes: int = 15
    jwt_refresh_minutes: int = 720

    pii_hmac_key: str = "change-me-local-dev-only"

    storage_backend: str = "local"
    storage_dir: str = "var/packs"

    llm_model: str = "claude-opus-5"
    llm_enabled: bool = True
    anthropic_api_key: str = Field("", validation_alias="ANTHROPIC_API_KEY")

    sim_seed: int = 42
    sim_size: str = "demo"

    demo_password: str = "sutra-demo"

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def artifacts_path(self) -> Path:
        return REPO_ROOT / "ml" / "artifacts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
