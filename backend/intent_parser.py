"""Intent Parser — connects to ArmorIQ to capture intents.

This module replaces custom LLM parsing by delegating the intent verification
and token generation directly to ArmorIQ.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from armoriq_sdk import ArmorIQClient
except ImportError:  # pragma: no cover - exercised when SDK is unavailable
    ArmorIQClient = None

from config import settings
from models import Intent, Platform

logger = logging.getLogger("clawsocial.intent")


# ── ArmorIQ Client Singleton ───────────────────────────────────────────────

_armoriq_client: Optional[ArmorIQClient] = None

def get_armoriq_client() -> ArmorIQClient:
    if ArmorIQClient is None:
        raise ImportError("armoriq_sdk is not installed")

    global _armoriq_client
    if _armoriq_client is None:
        if not settings.armoriq_development_key:
            raise ValueError("ARMORIQ_DEVELOPMENT_KEY is missing from environment")
        _armoriq_client = ArmorIQClient(
            api_key=settings.armoriq_development_key,
            user_id=settings.armoriq_user_id,
            agent_id=settings.armoriq_agent_id,
        )
    return _armoriq_client


# ── Simple fallback parsing just to know what we are doing locally ───────

def _basic_local_parse(instruction: str) -> Intent:
    """A very basic parse just to populate our local Intent object."""
    text = instruction.lower()
    
    # Platform
    platform = Platform.INSTAGRAM
    if "twitter" in text or "tweet" in text or "x.com" in text:
        platform = Platform.TWITTER
    elif "facebook" in text or "fb" in text:
        platform = Platform.FACEBOOK
    elif "linkedin" in text:
        platform = Platform.LINKEDIN

    # Intent category
    intent_category = "engagement_management"
    if "post" in text or "publish" in text or "tweet" in text:
        intent_category = "content_publishing"
    elif "schedule" in text:
        intent_category = "content_scheduling"
    elif "moderate" in text or "hide" in text or "report" in text:
        intent_category = "community_moderation"

    return Intent(
        intent=intent_category,
        platform=platform,
        actions_allowed=[],  # Will be populated by reasoning/ArmorIQ plan
        content_generation=True,
        publish_allowed=True,
        time_scope="today",
    )


async def capture_intent_armoriq(instruction: str, plan_dict: dict) -> tuple[Intent, str]:
    """Capture the plan with ArmorIQ and return the local Intent + cryptographic intent token."""
    if ArmorIQClient is None:
        logger.warning("armoriq_sdk not installed; using local fallback intent parsing")
        return _basic_local_parse(instruction), ""

    if not settings.armoriq_development_key:
        logger.warning("ARMORIQ_DEVELOPMENT_KEY missing; using local fallback intent parsing")
        return _basic_local_parse(instruction), ""

    client = get_armoriq_client()

    logger.info("Capturing plan with ArmorIQ...")
    
    # Use ArmorIQ to capture the plan
    plan_capture = client.capture_plan(
        llm=settings.llm_model,
        prompt=instruction,
        plan=plan_dict
    )
    
    # Get the cryptographic token (it's returned as an IntentToken object we need as a string)
    intent_token_obj = client.get_intent_token(plan_capture)
    intent_token = getattr(intent_token_obj, "token", str(intent_token_obj))
    logger.info("Received ArmorIQ intent token")

    # Build local intent object for our pipeline state
    intent = _basic_local_parse(instruction)
    
    return intent, intent_token
