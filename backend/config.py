"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration for ClawSocial."""

    # ── LLM (Gemini) ────────────────────────────────────────
    llm_provider: str = Field("gemini", description="LLM provider (gemini)")
    llm_api_key: str = Field("", description="Gemini API key")
    llm_model: str = Field("gemini-2.5-flash", description="Model identifier")

    # ── OpenClaw ─────────────────────────────────────────────
    openclaw_gateway_url: str = Field(
        "http://localhost:18789",
        description="OpenClaw gateway base URL",
    )
    openclaw_gateway_token: str = Field(
        "",
        description="OpenClaw gateway auth token",
    )
    openclaw_browser_profile: str = Field(
        "openclaw",
        description="Browser profile name for OpenClaw",
    )
    openclaw_cli_path: str = Field(
        "openclaw",
        description="Path to OpenClaw CLI (openclaw.mjs or binary)",
    )

    # ── ArmorIQ ─────────────────────────────────────────────
    armoriq_development_key: str = Field(
        "",
        description="ArmorIQ API key"
    )
    armoriq_user_id: str = Field("admin", description="ArmorIQ User ID")
    armoriq_agent_id: str = Field("clawsocial-agent", description="ArmorIQ Agent ID")

    # ── App ──────────────────────────────────────────────────
    log_level: str = Field("INFO")
    log_file: str = Field("clawsocial.log")
    policy_file: str = Field("backend/default_policy.json")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
