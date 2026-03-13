"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration for ClawSocial."""

    # ── LLM ──────────────────────────────────────────────
    llm_provider: str = Field("openai", description="openai | anthropic")
    llm_api_key: str = Field("", description="API key for the LLM provider")
    llm_model: str = Field("gpt-4o-mini", description="Model identifier")

    # ── OpenClaw ─────────────────────────────────────────
    openclaw_gateway_url: str = Field(
        "http://localhost:3000",
        description="OpenClaw gateway base URL",
    )
    openclaw_browser_profile: str = Field(
        "chrome",
        description="Browser profile name for OpenClaw",
    )

    # ── App ──────────────────────────────────────────────
    log_level: str = Field("INFO")
    log_file: str = Field("clawsocial.log")
    policy_file: str = Field("default_policy.json")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
