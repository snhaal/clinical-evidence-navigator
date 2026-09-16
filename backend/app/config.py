"""
Central settings object. Everything is sourced from environment variables
so the same code runs locally (.env) and on Render/Fly.io (dashboard env vars).
Never hardcode a secret here — see .env.example for the required keys.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database (Supabase Postgres + pgvector) -----------------------
    database_url: str = Field(
        ..., description="postgresql+asyncpg://... connection string"
    )

    # --- ClinicalTrials.gov ---------------------------------------------
    clinicaltrials_api_base: str = Field(
        default="https://clinicaltrials.gov/api/v2",
        description="Public API, no key required, but kept configurable in case of schema changes.",
    )

    # --- LLM provider (adapter-based, swappable) ------------------------
    llm_provider: str = Field(default="gemini", description="anthropic | gemini | groq")
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY"),
        description="Google Gemini API key",
    )
    groq_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY"),
        description="Groq API key for fallback",
    )
    llm_provider_api_key: str = Field(
        ...,
        validation_alias=AliasChoices(
            "GEMINI_API_KEY", "LLM_PROVIDER_API_KEY", "GROQ_API_KEY"
        ),
        description="Server-side only. Never exposed to the browser.",
    )
    llm_model: str = Field(default="gemini-3.5-flash-lite")

    llm_max_requests_per_minute: int = Field(
        default=5,
        description=(
            "Global cap on outbound LLM calls per rolling 60s window, shared across every "
            "LLMAdapter instance in the process (app/adapters/rate_limiter.py). The default of 5 "
            "is a conservative fallback; check your real provider quota and override in .env — "
            "Groq's free tier is documented at 30 RPM (25 is a safe cap below that), Gemini's free "
            "tier is unpublished and observed as low as 5 RPM in practice. Applies equally to "
            "Anthropic, whose limits are typically much higher."
        ),
    )

    # --- Cost / abuse controls on the public demo -----------------------
    max_requests_per_ip_per_hour: int = Field(default=20)
    max_patient_profile_chars: int = Field(default=4000)
    max_trials_per_query: int = Field(default=10)

    # --- Misc -------------------------------------------------------------
    app_url: str = Field(default="http://localhost:3000")
    environment: str = Field(default="development")  # development | production
    request_timeout_seconds: int = Field(default=12)


@lru_cache
def get_settings() -> Settings:
    """Cached so we parse the environment once per process."""
    return Settings()
