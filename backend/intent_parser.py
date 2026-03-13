"""Intent Parser — converts natural language instructions into structured Intent objects."""

from __future__ import annotations

import json
import logging
import re

from models import ActionType, Intent, Platform

logger = logging.getLogger("clawsocial.intent")

# ── Keyword-based fallback mapping ───────────────────────────────────────

_PLATFORM_KEYWORDS: dict[str, Platform] = {
    "instagram": Platform.INSTAGRAM,
    "insta": Platform.INSTAGRAM,
    "ig": Platform.INSTAGRAM,
    "twitter": Platform.TWITTER,
    "tweet": Platform.TWITTER,
    "x.com": Platform.TWITTER,
    "facebook": Platform.FACEBOOK,
    "fb": Platform.FACEBOOK,
    "linkedin": Platform.LINKEDIN,
}

_ACTION_KEYWORDS: dict[str, list[ActionType]] = {
    "reply": [ActionType.READ_COMMENTS, ActionType.REPLY_COMMENT],
    "comment": [ActionType.READ_COMMENTS, ActionType.REPLY_COMMENT],
    "engage": [ActionType.READ_COMMENTS, ActionType.REPLY_COMMENT],
    "respond": [ActionType.READ_COMMENTS, ActionType.REPLY_COMMENT],
    "post": [ActionType.PUBLISH_POST],
    "publish": [ActionType.PUBLISH_POST],
    "schedule": [ActionType.SCHEDULE_POST],
    "moderate": [ActionType.READ_COMMENTS, ActionType.HIDE_COMMENT, ActionType.REPORT_COMMENT],
    "caption": [ActionType.GENERATE_CAPTION],
    "hashtag": [ActionType.SUGGEST_HASHTAGS],
}

_INTENT_CATEGORIES: dict[str, str] = {
    "reply": "engagement_management",
    "comment": "engagement_management",
    "engage": "engagement_management",
    "respond": "engagement_management",
    "post": "content_publishing",
    "publish": "content_publishing",
    "schedule": "content_scheduling",
    "moderate": "community_moderation",
    "caption": "content_generation",
    "hashtag": "content_generation",
}

# ── LLM prompt for parsing ───────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an intent parser for a social media management agent.
Convert the user's natural language instruction into a JSON object with these fields:
- intent (string): task category, one of engagement_management, content_publishing, content_scheduling, community_moderation, content_generation
- platform (string): instagram, twitter, facebook, or linkedin
- actions_allowed (list of strings): read_comments, reply_comment, schedule_post, publish_post, generate_caption, suggest_hashtags, hide_comment, report_comment, delete_post, send_dm, change_profile, post_tweet
- content_generation (bool): whether to generate content
- publish_allowed (bool): whether publishing is authorized
- time_scope (string): execution window, e.g. "today", "next_hour"
Return ONLY valid JSON, no extra text.
"""


async def parse_intent_llm(instruction: str, llm_client) -> Intent:
    """Use an LLM to parse the instruction into an Intent (async)."""
    try:
        response = await llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": instruction},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        return Intent(**data)
    except Exception as exc:
        logger.warning("LLM intent parsing failed (%s), falling back to keyword parser", exc)
        return parse_intent_keywords(instruction)


def parse_intent_keywords(instruction: str) -> Intent:
    """Keyword-based fallback parser (no LLM required)."""
    text = instruction.lower()

    # Detect platform
    platform = Platform.INSTAGRAM  # default
    for keyword, plat in _PLATFORM_KEYWORDS.items():
        if keyword in text:
            platform = plat
            break

    # Detect actions
    actions: list[ActionType] = []
    intent_category = "engagement_management"
    for keyword, action_list in _ACTION_KEYWORDS.items():
        if keyword in text:
            actions.extend(a for a in action_list if a not in actions)
            if keyword in _INTENT_CATEGORIES:
                intent_category = _INTENT_CATEGORIES[keyword]

    if not actions:
        actions = [ActionType.READ_COMMENTS]

    # Content generation / publish flags
    content_gen = any(
        w in text for w in ("generate", "caption", "write", "create", "respond", "reply")
    )
    publish = any(w in text for w in ("post", "publish", "send", "submit", "tweet"))

    # Time scope
    time_scope = "today"
    if "tomorrow" in text:
        time_scope = "tomorrow"
    elif "week" in text:
        time_scope = "this_week"
    elif re.search(r"next\s+hour", text):
        time_scope = "next_hour"

    return Intent(
        intent=intent_category,
        platform=platform,
        actions_allowed=actions,
        content_generation=content_gen,
        publish_allowed=publish,
        time_scope=time_scope,
    )
