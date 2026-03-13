"""Reasoning Engine — LLM-powered task decomposition and response generation."""

from __future__ import annotations

import json
import logging
from typing import Optional

from models import ActionProposal, ActionType, Intent, Platform, Sentiment

logger = logging.getLogger("clawsocial.reasoning")

# ── LLM system prompt ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a social media management assistant. Given a structured intent, decompose
the task into a sequence of concrete actions the agent should perform.

Return a JSON array of action objects, each with:
- action_type: one of read_comments, reply_comment, schedule_post, publish_post,
  generate_caption, suggest_hashtags, hide_comment, report_comment, post_tweet
- platform: instagram, twitter, facebook, linkedin
- content: any text content for the action (reply text, caption, etc.)  — may be null
- reasoning: why this action is needed

Return ONLY the JSON array.
"""


# ── Fallback decomposition (no LLM) ─────────────────────────────────────

_ENGAGEMENT_STEPS = [
    ActionType.READ_COMMENTS,
    ActionType.REPLY_COMMENT,
]

_PUBLISHING_STEPS = [
    ActionType.GENERATE_CAPTION,
    ActionType.PUBLISH_POST,
]

_SCHEDULING_STEPS = [
    ActionType.GENERATE_CAPTION,
    ActionType.SCHEDULE_POST,
]

_MODERATION_STEPS = [
    ActionType.READ_COMMENTS,
    ActionType.HIDE_COMMENT,
    ActionType.REPORT_COMMENT,
]

_TEMPLATE_REPLIES = {
    Sentiment.POSITIVE: "Thanks for watching! 🙌",
    Sentiment.NEGATIVE: "We appreciate your feedback. We'll do better!",
    Sentiment.NEUTRAL: "Thanks for your comment!",
    Sentiment.SPAM: None,  # no reply for spam
    Sentiment.ABUSIVE: None,
}


def _decompose_fallback(intent: Intent) -> list[ActionProposal]:
    """Rule-based decomposition when LLM is unavailable."""
    proposals: list[ActionProposal] = []

    category = intent.intent.lower()

    if "engagement" in category:
        step_types = _ENGAGEMENT_STEPS
    elif "publish" in category:
        step_types = _PUBLISHING_STEPS
    elif "schedul" in category:
        step_types = _SCHEDULING_STEPS
    elif "moderat" in category:
        step_types = _MODERATION_STEPS
    else:
        step_types = list(intent.actions_allowed) if intent.actions_allowed else [ActionType.READ_COMMENTS]

    for action_type in step_types:
        content: Optional[str] = None
        reasoning = f"Part of {intent.intent} workflow"

        if action_type == ActionType.REPLY_COMMENT:
            content = _TEMPLATE_REPLIES.get(Sentiment.POSITIVE, "Thanks for your comment!")
            reasoning = "Generate a positive reply to engagement"
        elif action_type == ActionType.GENERATE_CAPTION:
            content = "Check out our latest update! 🚀 #trending"
            reasoning = "Generate default caption for publishing"
        elif action_type == ActionType.PUBLISH_POST:
            reasoning = "Publish content to platform"
        elif action_type == ActionType.POST_TWEET:
            reasoning = "Post content to Twitter"

        proposals.append(
            ActionProposal(
                action_type=action_type,
                platform=intent.platform,
                content=content,
                reasoning=reasoning,
            )
        )

    return proposals


async def decompose_task_llm(intent: Intent, llm_client) -> list[ActionProposal]:
    """Use LLM to decompose the intent into action proposals."""
    try:
        response = await llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": intent.model_dump_json()},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        # The LLM might wrap in {"actions": [...]} or return bare array
        data = json.loads(raw)
        if isinstance(data, dict) and "actions" in data:
            data = data["actions"]
        if not isinstance(data, list):
            data = [data]

        proposals = []
        for item in data:
            proposals.append(
                ActionProposal(
                    action_type=item["action_type"],
                    platform=item.get("platform", intent.platform.value),
                    content=item.get("content"),
                    reasoning=item.get("reasoning", ""),
                )
            )
        return proposals
    except Exception as exc:
        logger.warning("LLM decomposition failed (%s), using fallback", exc)
        return _decompose_fallback(intent)


def decompose_task(intent: Intent) -> list[ActionProposal]:
    """Synchronous fallback decomposition (keyword-based)."""
    return _decompose_fallback(intent)


def classify_sentiment(text: str) -> Sentiment:
    """Simple keyword-based sentiment classifier."""
    lower = text.lower()
    spam_words = {"buy now", "click here", "free money", "check my profile", "follow me"}
    abuse_words = {"idiot", "stupid", "hate", "kill", "die"}

    if any(w in lower for w in spam_words):
        return Sentiment.SPAM
    if any(w in lower for w in abuse_words):
        return Sentiment.ABUSIVE
    if any(w in lower for w in {"great", "love", "awesome", "amazing", "beautiful", "best", "thanks"}):
        return Sentiment.POSITIVE
    if any(w in lower for w in {"bad", "worst", "terrible", "ugly", "boring", "dislike"}):
        return Sentiment.NEGATIVE
    return Sentiment.NEUTRAL
