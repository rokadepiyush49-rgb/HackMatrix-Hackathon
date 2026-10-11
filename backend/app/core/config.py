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

    # Investigation Council agents (app.council.agentic) run on Groq. The key stays on the server: it is
    # never returned by the API, logged or shown to the browser. Without a key the council is deterministic.
    groq_api_key: str = Field("", validation_alias="GROQ_API_KEY", repr=False)
    groq_model: str = Field("openai/gpt-oss-120b", validation_alias="GROQ_MODEL")
    groq_base_url: str = Field("https://api.groq.com/openai/v1", validation_alias="GROQ_BASE_URL")
    groq_timeout_s: float = Field(30.0, validation_alias="GROQ_TIMEOUT_S", gt=0, le=300)
    groq_max_retries: int = Field(2, validation_alias="GROQ_MAX_RETRIES", ge=0, le=5)
    # 0 = take the context window from app.council.llm.MODEL_LIMITS (verified per model); set it for other models.
    groq_context_window: int = Field(0, validation_alias="GROQ_CONTEXT_WINDOW", ge=0)
    groq_reasoning_effort: Literal["", "low", "medium", "high"] = Field("low", validation_alias="GROQ_REASONING_EFFORT")
    # auto: agents when a Groq key is set, the deterministic council otherwise. llm: agents (fails over per
    # agent to the deterministic council). deterministic: never call the LLM.
    council_engine: Literal["auto", "llm", "deterministic"] = "auto"
    council_max_calls: int = Field(24, ge=1, le=200)  # LLM calls per investigation, retries included
    council_token_budget: int = Field(120_000, ge=1_000)  # prompt + completion tokens per investigation
    council_deadline_s: float = Field(240.0, gt=0, le=1800)  # whole investigation, rate-limit waits included
    council_max_output_tokens: int = Field(3_000, ge=256, le=32_000)  # per call; gpt-oss reasoning counts here
    council_call_input_tokens: int = Field(6_000, ge=1_000)  # per call; keeps each call under a free-tier TPM
    council_context_fraction: float = Field(0.5, gt=0.05, le=0.95)  # never fill more than this of the window
    council_concurrency: int = Field(2, ge=1, le=8)

    # Account Aggregator (app.integrations.aa). "synthetic" is a labelled demo FIP that works offline and only in
    # demo mode. "setu" talks to Setu's FIU sandbox and needs credentials from Setu's Bridge; live data additionally
    # needs a regulated, Sahamati-certified FIU (docs/integrations/ACCOUNT_AGGREGATOR.md).
    aa_provider: Literal["synthetic", "setu"] = "synthetic"
    aa_setu_base_url: str = ""
    aa_setu_client_id: str = Field("", repr=False)
    aa_setu_client_secret: str = Field("", repr=False)
    aa_setu_product_instance_id: str = ""
    aa_data_life_days: int = Field(30, ge=1, le=365)  # fetched statements are purged after this, or on revocation

    # M2 raises a signal for sessions in the bottom 2% of their role's navigation likelihood. 0.5% (the original
    # value) caught none of 24 insider sessions on unseen worlds 10–11; 2%, chosen on worlds 7–9, caught all 24
    # with no look-alike flagged and left M7's FIN-04 results unchanged (ml/reports/m1_m2_eval.json, ADR 021).
    m2_signal_percentile: float = Field(0.02, gt=0, lt=0.5)
    # Where models and evaluation reports are written; empty = ml/artifacts and ml/reports (experiments set these).
    artifacts_dir: str = ""
    reports_dir: str = ""

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
        return Path(self.artifacts_dir) if self.artifacts_dir else REPO_ROOT / "ml" / "artifacts"

    @property
    def reports_path(self) -> Path:
        return Path(self.reports_dir) if self.reports_dir else REPO_ROOT / "ml" / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
