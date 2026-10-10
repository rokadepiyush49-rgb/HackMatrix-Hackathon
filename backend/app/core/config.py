"""Runtime configuration, read from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_prefix="SUTRA_", extra="ignore"
    )

    # dev | test run locally with relaxed defaults; staging | prod refuse unsafe configuration.
    env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://localhost:5432/sutra"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Per-statement ceiling for the API (0 = off). Batch jobs leave it off: detection runs long COPYs.
    db_statement_timeout_ms: int = 0

    jwt_secret: str = "change-me-local-dev-only"
    jwt_access_minutes: int = 15
    jwt_refresh_minutes: int = 720

    pii_hmac_key: str = "change-me-local-dev-only"

    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = "var/packs"
    s3_bucket: str = ""
    s3_prefix: str = "packs/"
    s3_kms_key_id: str = ""
    # PMLA Rule 10: records kept for five years. Object Lock enforces it in COMPLIANCE mode.
    evidence_retention_days: int = 1825
    # COMPLIANCE: nobody can shorten or remove the lock. GOVERNANCE: privileged roles can (staging only).
    evidence_lock_mode: Literal["COMPLIANCE", "GOVERNANCE"] = "COMPLIANCE"
    aws_region: str = "ap-south-1"

    # memory:// is per-process; use redis://… when more than one API replica runs.
    rate_limit_storage_uri: str = "memory://"

    # anthropic: first-party API (key or workload identity). bedrock: Claude in Amazon Bedrock via IAM.
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_bedrock_model: str = "anthropic.claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_enabled: bool = True
    anthropic_api_key: str = Field("", validation_alias="ANTHROPIC_API_KEY")

    sim_seed: int = 42
    sim_size: str = "demo"

    demo_password: str = "sutra-demo"

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    demo_mode: bool = True

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        if self.env not in ("staging", "prod"):
            return self
        problems = []
        for name in ("jwt_secret", "pii_hmac_key"):
            value = getattr(self, name)
            if value.startswith("change-me") or len(value) < 32:
                problems.append(f"SUTRA_{name.upper()} must be a random value of at least 32 characters")
        if self.demo_mode:
            problems.append("SUTRA_DEMO_MODE must be false (demo personas share one password)")
        if self.env == "prod" and self.storage_backend != "s3":
            problems.append("SUTRA_STORAGE_BACKEND must be s3 in prod (evidence needs write-once storage)")
        if self.env == "prod" and self.evidence_lock_mode != "COMPLIANCE":
            problems.append("SUTRA_EVIDENCE_LOCK_MODE must be COMPLIANCE in prod")
        if problems:
            raise ValueError("Unsafe configuration for " + self.env + ": " + "; ".join(problems))
        return self

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
