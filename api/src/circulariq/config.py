from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings read from environment variables (and `.env` in local dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "circulariq-api"
    environment: str = "development"
    # Comma-separated list, e.g. "http://localhost:3000,https://myapp.vercel.app"
    cors_origins: str = "http://localhost:3000"

    database_url: str = Field(default="", repr=False)

    anthropic_api_key: str = Field(default="", repr=False)
    # Cheap model by default; use the smart one only where quality really matters.
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    # Answers use model_smart until this many per rolling 24 h, then model_fast.
    smart_answers_per_day: int = 50

    voyage_api_key: str = Field(default="", repr=False)
    embed_model: str = "voyage-4"
    embed_dim: int = 1024
    rerank_model: str = "rerank-3"
    # Voyage tokens-per-minute budget. Accounts without a payment method have low limits;
    # set this (e.g. 10000) to throttle ingestion instead of hitting 429s. 0 = no throttle.
    voyage_tpm: int = 0
    # Requests per minute, same idea (free tier without a card allows only a few). 0 = no throttle.
    voyage_rpm: int = 0

    # Optional Langfuse tracing; tracing is a no-op unless both keys are set.
    langfuse_public_key: str = Field(default="", repr=False)
    langfuse_secret_key: str = Field(default="", repr=False)
    langfuse_host: str = "https://cloud.langfuse.com"

    # Local working directory for downloaded PDFs, manifest and parsed chunks (git-ignored).
    data_dir: Path = Path("data")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
